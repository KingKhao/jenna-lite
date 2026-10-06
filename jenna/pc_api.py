"""The app's local web server (desktop window + phone through Tailscale) and push-to-talk's way in.

Same assistant as Telegram (same brain, memory, tools) - messages go through Bot.handle_text with the replies
captured for the app, then mirrored into Telegram (if set up) so it's one thread.

Security: listens on 127.0.0.1 only; every /api call needs the key in data/pc_token.txt (header X-Jenna-Token, or
the HttpOnly cookie the first open sets); Host must be localhost or her Tailscale name (blocks DNS rebinding);
through Tailscale the visitor must be the Tailscale account setup allowed; cross-site requests are refused.
"""
import json
import logging
import queue
import re
import secrets
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import live, memory, pc_features, voice
from .settings import APP_PORT, DATA, ROOT, busy, load_config

log = logging.getLogger("jenna")
PORT = APP_PORT
TOKEN_FILE = DATA / "pc_token.txt"
COOKIE = "jenna_lite_key"
APP_HTML = ROOT / "pc" / "app.html"
BRAND_FILES = {"orb.svg": "image/svg+xml", "logo-horizontal.svg": "image/svg+xml", "favicon.ico": "image/x-icon",
               "favicon-32.png": "image/png", "apple-touch-icon.png": "image/png", "app-icon-192.png": "image/png",
               "app-icon-512.png": "image/png"}
GALAXY_FILES = {"three.module.min.js": "text/javascript", "galaxy.js": "text/javascript",
                "galaxy-core.js": "text/javascript", "constellation.js": "text/javascript", "tokens.css": "text/css"}
_audio = {}              # id -> wav path (short-lived, for the app to play)
_audio_pending = {}      # id -> threading.Event: that part of a reply is still being spoken into a wav
_peeks = {}              # id -> (transcript, time): what they'd said when they first went quiet
PEEK_TTL_S = 120
_audio_lock = threading.Lock()
_bot = None


def token():
    """The app key. Exclusive create, because the desktop launcher may make it first (same file, same rule)."""
    try:
        with TOKEN_FILE.open("x", encoding="utf-8") as f:
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    for _ in range(20):
        key = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
        time.sleep(0.1)   # the launcher is mid-write
    return key


def peek_transcript(audio_path):
    """Transcribe what they've said so far while the app keeps listening. The app takes the turn early when it
    sounds finished, and the final request reuses this transcript instead of transcribing again."""
    from . import turntaking
    text = _bot.transcribe_path(audio_path)
    pid = uuid.uuid4().hex[:12]
    now = time.time()
    with _audio_lock:
        for k in [k for k, (_, t) in _peeks.items() if now - t > PEEK_TTL_S]:
            _peeks.pop(k, None)
        _peeks[pid] = (text, now)
    return {"id": pid, "text": text, "finished": turntaking.sounds_finished(text)}


def take_peek(pid):
    with _audio_lock:
        got = _peeks.pop(pid, None)
    return got[0] if got else None


FIRST_PART_MIN = 40      # chars: a 3-word first sentence would leave a gap before the second
PART_MAX = 220


def speech_parts(text):
    """Her reply as speakable pieces: the first sentence on its own (it's what she says first), the rest in groups
    of whole sentences."""
    spoken = voice.clean_for_speech(text)
    if not spoken:
        return []
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", spoken) if s.strip()]
    parts, cur = [], ""
    for s in sentences:
        limit = FIRST_PART_MIN if not parts else PART_MAX
        if cur and (len(cur) >= limit or len(cur) + len(s) > PART_MAX):
            parts.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        parts.append(cur)
    return parts


def _speak_rest(jobs):
    for aid, part in jobs:
        wav = None
        try:
            wav = voice.synthesize_wav(part)
        except Exception:
            log.exception("speech part failed")
        with _audio_lock:
            if wav:
                _audio[aid] = wav
            ev = _audio_pending.pop(aid, None)
        if ev:
            ev.set()


def take_audio(aid, timeout=60):
    """The wav for an audio id, waiting while that part is still being made. None if it's gone or failed."""
    with _audio_lock:
        ev = _audio_pending.get(aid)
    if ev:
        ev.wait(timeout)
    with _audio_lock:
        return _audio.pop(aid, None)


def _speakable(out, early=None):
    """Make audio for each reply the app should speak, sentence by sentence: only the first part is made before
    answering, so she starts talking about a second in; the rest is made while that plays."""
    for item in out:
        if item.get("type") == "text" and item.get("speak"):
            parts = speech_parts(item["text"])
            if not parts:
                continue
            wav = None
            if early and early.get("text") == parts[0]:   # made while she was still writing
                early["done"].wait(30)
                wav, early["used"] = early.get("wav"), True
            if not wav:
                wav = voice.synthesize_wav(parts[0])
            if not wav:
                continue
            aid = uuid.uuid4().hex[:12]
            jobs = [(uuid.uuid4().hex[:12], p) for p in parts[1:]]
            with _audio_lock:
                _audio[aid] = wav
                for jid, _ in jobs:
                    _audio_pending[jid] = threading.Event()
            item["audio"] = f"/api/audio/{aid}"
            item["audio_more"] = [f"/api/audio/{jid}" for jid, _ in jobs]
            if jobs:
                threading.Thread(target=_speak_rest, args=(jobs,), name="speech", daemon=True).start()
    if early and early.get("done") and not early.get("used"):   # her checks changed the reply: drop that audio
        def toss():
            early["done"].wait(30)
            if early.get("wav"):
                Path(early["wav"]).unlink(missing_ok=True)
        threading.Thread(target=toss, daemon=True).start()
    return out


def _mirror(kind, text, out):
    """Copy the app exchange into the Telegram chat so there's one history."""
    if not (_bot and _bot.enabled and _bot.owner) or not load_config().get("pc_mirror_to_telegram", True):
        return
    replies = "\n\n".join(i["text"] for i in out if i.get("type") == "text")
    label = {"voice": "(said in the app)", "text": "(typed in the app)"}.get(kind, "(in the app)")
    try:
        _bot.send(f"You {label}: {text}\n\n{replies}".strip()[:3900], chat_id=_bot.owner, quiet=True)
    except Exception:
        log.exception("telegram mirror failed")


def _share(user_text, result, origin, source):
    """Show this exchange live in the OTHER open app windows (e.g. the phone, while they typed on the PC)."""
    live.publish("user", user_text, source, origin=origin)
    for i in result:
        if i.get("type") == "text":
            live.publish("assistant", i["text"], source, origin=origin)
        elif i.get("type") == "confirm":
            live.publish("assistant", i["summary"], source, origin=origin, kind="confirm", extra={"confirm_id": i["id"]})


def _early_speech():
    """Listens to her reply while she writes it and starts making the first part's audio as soon as that part is
    complete. _speakable uses it only if the final reply still starts the same."""
    from . import humanize
    early = {}

    def on_text(so_far):
        if early:
            return
        parts = speech_parts(humanize.clean(so_far))
        if len(parts) < 2:   # the first part isn't finished until a second one has begun
            return
        early["text"], early["done"] = parts[0], threading.Event()

        def make():
            try:
                early["wav"] = voice.synthesize_wav(parts[0])
            finally:
                early["done"].set()
        threading.Thread(target=make, name="early-speech", daemon=True).start()
    return early, on_text


def handle_message(text, from_voice=False, speak=False, origin=None, source="app"):
    from . import brain
    early, on_text = _early_speech() if speak else ({}, None)
    brain.set_text_listener(on_text)
    try:
        with busy(), live.conversation(), _bot.capture() as out:
            _bot.handle_text(text, from_voice=from_voice)
    finally:
        brain.set_text_listener(None)
    result = list(out)
    if speak:
        for i in result:
            if i.get("type") == "text":
                i["speak"] = True
    _mirror("voice" if from_voice else "text", text, result)
    _share(text, result, origin, source)
    return _speakable(result, early)


def handle_confirm(aid, yes, speak=False, origin=None):
    with busy(), live.conversation(), _bot.capture() as out:
        _bot.handle_callback({"id": "", "data": f"{'yes' if yes else 'no'}:{aid}", "message": {}}, typed=True)
    result = list(out)
    if speak:
        for i in result:
            if i.get("type") == "text":
                i["speak"] = True
    _mirror("confirm", "Yes" if yes else "No", result)
    _share("Yes" if yes else "No", result, origin, "app")
    return _speakable(result)


# Browser hardening on every response. The app is one page with an inline script, so script-src keeps
# 'unsafe-inline' (all message text is escaped before display); the page can only talk to this server.
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; worker-src 'self'; "
                                "manifest-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; "
                                "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "microphone=(self), autoplay=(self), camera=(), geolocation=(), interest-cohort=()",
}
JSON_POSTS = {"/api/notes", "/api/skills", "/api/voices", "/api/push/subscribe", "/api/push/test", "/api/settings",
              "/api/history/clear"}


class Handler(BaseHTTPRequestHandler):
    server_version = "JennaLite"

    def end_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, *a):
        pass

    def _ok_origin(self):
        host = (self.headers.get("Host") or "").lower()
        local = (f"127.0.0.1:{PORT}", f"localhost:{PORT}")
        remote = [h.lower() for h in load_config().get("pc_remote_hosts", [])]
        if host in local:
            origins = (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")
        elif host in remote:
            # reached through `tailscale serve`: Tailscale vouches for who the visitor is - it must be the owner
            who = (self.headers.get("Tailscale-User-Login") or "").lower()
            allowed = [u.lower() for u in load_config().get("pc_remote_users", [])]
            if not who or (allowed and who not in allowed):
                return False
            origins = (f"https://{host}",)
        else:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin in origins

    def _local(self):
        """This PC only (setup steps that change Telegram / Tailscale can't be done from the phone)."""
        return (self.headers.get("Host") or "").lower() in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _authed(self):
        return self._ok_origin() and secrets.compare_digest(self.headers.get("X-Jenna-Token", ""), token())

    def _key_ok(self, q):
        """The app key from ?t= (first open) or the HttpOnly cookie that first open set (keeps the key out of the
        address bar, history and the home-screen shortcut)."""
        given = (q.get("t") or [""])[0]
        if not given:
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    given = v
        return bool(given) and secrets.compare_digest(given, token())

    def _query_authed(self, q):
        return self._ok_origin() and self._key_ok(q)

    def _cookie_header(self):
        secure = "" if self._local() else "; Secure"
        return f"{COOKIE}={token()}; Path=/; HttpOnly; SameSite=Strict; Max-Age=34560000{secure}"

    def _origin_id(self):
        return (self.headers.get("X-Client-Id") or "")[:40] or None

    def _events(self):
        """Server-Sent Events: new messages from anywhere, pushed to this open window, with a ping every 20 s."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = live.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    ev = q.get(timeout=20)
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass   # the window closed: normal end of a stream
        finally:
            live.unsubscribe(q)

    def _send_file(self, path, ctype, extra_headers=None):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if "Cache-Control" not in (extra_headers or {}):
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 25_000_000:
            raise ValueError("too big")
        return self.rfile.read(n) if n else b""

    # ---------------- GET ----------------
    def _feature_get(self, u):
        q = parse_qs(u.query)
        if u.path == "/api/today":
            return pc_features.today()
        if u.path == "/api/notes":
            return {"notes": pc_features.list_notes(min(90, int((q.get("days") or ["14"])[0])))}
        if u.path == "/api/skills":
            return {"skills": pc_features.list_skills()}
        if u.path == "/api/constellation":
            return pc_features.constellation()
        if u.path == "/api/search":
            return {"messages": pc_features.history((q.get("q") or [""])[0], 150)}
        if u.path == "/api/diagnostics":
            return {"checks": pc_features.diagnostics()}
        if u.path == "/api/logs":
            return pc_features.logs((q.get("level") or ["problems"])[0])
        if u.path == "/api/voices":
            return pc_features.voices()
        if u.path == "/api/brain":
            from . import brain_vault
            return brain_vault.stats()
        if u.path == "/api/settings":
            return pc_features.settings()
        if u.path == "/api/push/key":
            return {"key": live.public_key()}
        if u.path == "/api/connections":
            from . import connections
            return connections.overview()
        if u.path == "/api/setup":
            from . import onboarding
            return onboarding.status()
        if u.path == "/api/setup/qr":
            link = pc_features.phone_link()
            from . import onboarding
            return {"link": link, "svg": onboarding.qr_svg(link) if link else ""}
        return None

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            q = parse_qs(u.query)
            if not self._query_authed(q):
                return self._json(403, {"error": "open the app from its Desktop icon (or the link from /app on Telegram)"})
            body = APP_HTML.read_text(encoding="utf-8").replace("__TOKEN__", token()).encode("utf-8")
            self.send_response(200)
            self.send_header("Set-Cookie", self._cookie_header())
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(body)
        if u.path.startswith("/brand/") or u.path == "/favicon.ico":   # her logo files: public, no data, exact files only
            name = "favicon.ico" if u.path == "/favicon.ico" else u.path[len("/brand/"):]
            if name not in BRAND_FILES:
                return self._json(404, {"error": "not found"})
            return self._send_file(ROOT / "pc" / "brand" / name, BRAND_FILES[name], {"Cache-Control": "max-age=86400"})
        if u.path.startswith("/galaxy/"):   # the galaxy's code: public, no data, exact files only
            name = u.path[len("/galaxy/"):]
            if name not in GALAXY_FILES:
                return self._json(404, {"error": "not found"})
            return self._send_file(ROOT / "pc" / "galaxy" / name, GALAXY_FILES[name])
        if u.path in ("/sw.js", "/api/events", "/api/voices/preview", "/manifest.json", "/icon.png"):
            q = parse_qs(u.query)   # loaded by the browser itself (no custom headers) -> key in ?t= or the cookie
            if not self._query_authed(q):
                return self._json(403, {"error": "forbidden"})
            if u.path == "/sw.js":
                return self._send_file(ROOT / "pc" / "sw.js", "application/javascript", {"Service-Worker-Allowed": "/"})
            if u.path == "/api/events":
                return self._events()
            if u.path == "/icon.png":   # phone home-screen icon and notification icon
                big = (q.get("s") or [""])[0] == "512"
                return self._send_file(ROOT / "pc" / "brand" / ("app-icon-512.png" if big else "app-icon-192.png"), "image/png")
            if u.path == "/manifest.json":
                me = load_config().get("assistant_name") or "Jenna"
                return self._json(200, {"name": me, "short_name": me, "display": "standalone", "start_url": "/",
                                        "scope": "/", "background_color": "#05070c", "theme_color": "#05070c",
                                        "icons": [{"src": "/icon.png", "sizes": "192x192", "type": "image/png"},
                                                  {"src": "/icon.png?s=512", "sizes": "512x512", "type": "image/png"}]})
            try:
                wav = pc_features.preview_voice((q.get("voice") or ["af_heart"])[0], (q.get("speed") or ["1.0"])[0])
            except Exception as e:
                return self._json(400, {"error": str(e)[:120]})
            self._send_file(wav, "audio/wav")
            return Path(wav).unlink(missing_ok=True)
        if not self._authed():
            return self._json(403, {"error": "forbidden"})
        try:
            got = self._feature_get(u)
        except Exception as e:
            log.exception("app request failed: %s", u.path)
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        if got is not None:
            return self._json(200, got)
        if u.path == "/api/history":
            n = int((parse_qs(u.query).get("n") or ["40"])[0])
            return self._json(200, {"messages": memory.display_history(min(n, 200))})
        if u.path == "/api/status":
            cfg = load_config()
            return self._json(200, {"name": cfg.get("assistant_name"), "owner": cfg.get("owner_name"),
                                    "setup_done": bool(cfg.get("setup_done")), "voice": cfg.get("voice"),
                                    "model": cfg.get("model"), "telegram": bool(_bot and _bot.enabled and _bot.owner),
                                    "mic": mic_status(), "local": self._local(), "ptt_key": cfg.get("push_to_talk_key", "f8").upper()})
        if u.path.startswith("/api/audio/"):
            wav = take_audio(u.path.rsplit("/", 1)[-1])
            if not wav or not Path(wav).exists():
                return self._json(404, {"error": "gone"})
            data = Path(wav).read_bytes()
            Path(wav).unlink(missing_ok=True)
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        return self._json(404, {"error": "not found"})

    # ---------------- POST ----------------
    def _feature_post(self, u, d):
        if u.path == "/api/notes":
            n = pc_features.save_note(d.get("text", ""), d.get("source", "typed"))
            live.publish("note", d.get("text", ""), "app", origin=self._origin_id(), kind="note")
            return {"note": n}
        if u.path == "/api/skills":
            if d.get("delete"):
                return {"deleted": pc_features.delete_skill(d["delete"]), "skills": pc_features.list_skills()}
            return {"skill": pc_features.save_skill(d), "skills": pc_features.list_skills()}
        if u.path == "/api/voices":
            return pc_features.set_voice(d)
        if u.path == "/api/settings":
            return pc_features.save_settings(d)
        if u.path == "/api/history/clear":
            memory.clear_history()
            return {"cleared": True}
        if u.path == "/api/push/subscribe":
            return {"devices": live.add_subscription(d)}
        if u.path == "/api/push/test":
            live.notify(load_config().get("assistant_name") or "Jenna", "Notifications are working - I'll buzz you when I need you.")
            return {"sent": True}
        return None

    def _connections_post(self, u, d):
        from . import connections
        act = u.path.rsplit("/", 1)[1]
        if act == "connect":
            return connections.connect(str(d.get("id", "")), d.get("fields") or {})
        if act == "disconnect":
            return connections.disconnect(str(d.get("id", "")))
        return None

    def _setup_post(self, u, d):
        from . import onboarding
        step = u.path.rsplit("/", 1)[1]
        acts = {"profile": lambda: onboarding.save_profile(d), "finish": onboarding.finish,
                "pull": lambda: onboarding.pull_model(d.get("model")), "model": lambda: onboarding.use_model(d.get("model")),
                "telegram": lambda: onboarding.telegram_connect(d.get("token", "")),
                "telegram-remove": onboarding.telegram_remove,
                "phone": onboarding.phone_enable, "phone-off": onboarding.phone_disable}
        if step not in acts:
            return None
        return acts[step]()

    def do_POST(self):
        if not self._authed():
            return self._json(403, {"error": "forbidden"})
        u = urlparse(self.path)
        try:
            if u.path in JSON_POSTS:
                try:
                    return self._json(200, self._feature_post(u, json.loads(self._body() or b"{}")))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
            if u.path.startswith("/api/connections/"):
                try:
                    got = self._connections_post(u, json.loads(self._body() or b"{}"))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, got) if got is not None else self._json(404, {"error": "not found"})
            if u.path.startswith("/api/setup/"):
                if not self._local():
                    return self._json(403, {"error": "Do setup on the PC itself."})
                try:
                    got = self._setup_post(u, json.loads(self._body() or b"{}"))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                return self._json(200, got) if got is not None else self._json(404, {"error": "not found"})
            if u.path == "/api/chat":
                d = json.loads(self._body() or b"{}")
                text = (d.get("text") or "").strip()[:8000]
                if not text:
                    return self._json(400, {"error": "empty"})
                if d.get("mode") == "note":
                    n = pc_features.save_note(text, "typed")
                    live.publish("note", text, "app", origin=self._origin_id(), kind="note")
                    return self._json(200, {"note": n, "messages": []})
                return self._json(200, {"messages": handle_message(text, speak=bool(d.get("speak")), origin=self._origin_id())})
            if u.path in ("/api/voice/peek", "/api/voice"):
                q = parse_qs(u.query)
                ext = re.sub(r"[^a-z0-9]", "", (q.get("ext") or ["webm"])[0].lower())[:5] or "webm"
                body = self._body()
                if u.path == "/api/voice/peek":
                    p = Path(tempfile.gettempdir()) / f"jenna_lite_peek_{uuid.uuid4().hex[:8]}.{ext}"
                    p.write_bytes(body)
                    return self._json(200, peek_transcript(p))
                speak = (q.get("speak") or ["1"])[0] == "1"
                spec = (q.get("spec") or [""])[0]
                heard = take_peek(spec) if spec else None   # already transcribed while they paused
                if heard is None:
                    p = Path(tempfile.gettempdir()) / f"jenna_lite_{uuid.uuid4().hex[:8]}.{ext}"
                    p.write_bytes(body)
                    heard = _bot.transcribe_path(p)
                if not heard:
                    return self._json(200, {"heard": "", "messages": [{"type": "text", "text":
                                            "I couldn't make that out - try again a little closer to the mic?"}]})
                if (q.get("mode") or [""])[0] == "note":
                    n = pc_features.save_note(heard, "spoken")
                    live.publish("note", heard, "app", origin=self._origin_id(), kind="note")
                    return self._json(200, {"heard": heard, "note": n, "messages": []})
                return self._json(200, {"heard": heard, "messages": handle_message(heard, from_voice=True, speak=speak,
                                                                                   origin=self._origin_id())})
            if u.path == "/api/confirm":
                d = json.loads(self._body() or b"{}")
                return self._json(200, {"messages": handle_confirm(str(d.get("id", "")), bool(d.get("yes")),
                                                                   speak=bool(d.get("speak")), origin=self._origin_id())})
        except Exception as e:
            log.exception("app request failed")
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        return self._json(404, {"error": "not found"})


def mic_status():
    try:
        import sounddevice as sd
        names = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        real = [n for n in names if "steam" not in n.lower() and "sound mapper" not in n.lower()
                and "primary sound capture" not in n.lower()]
        return {"ok": bool(real), "devices": sorted(set(real))[:6]}
    except Exception as e:
        return {"ok": False, "devices": [], "error": str(e)[:120]}


def serve(bot):
    global _bot
    _bot = bot
    token()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        log.error("app server couldn't start on port %s: %s", PORT, e)
        return
    log.info("app server on http://127.0.0.1:%s", PORT)
    srv.serve_forever()
