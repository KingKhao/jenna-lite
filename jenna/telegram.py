"""Telegram + the message pipeline every channel shares.

The Bot is the one place a message from the user is handled - Telegram, the desktop app, the phone app and
push-to-talk all call handle_text(). Telegram itself is optional: with no bot token she runs app-only and send()
just shows things in the open app windows.
"""
import logging
import re
import tempfile
import threading
import time
from pathlib import Path

import requests

from . import brain, brain_vault, live, memory, tools, turntaking
from .settings import busy, get_secret, load_config

log = logging.getLogger("jenna")
API = "https://api.telegram.org/bot{token}/{method}"
AFFIRM = re.compile(r"^\s*(yes|yep|yeah|yup|y|confirm(ed)?|go ahead|do it|approved?|ok(ay)?,? do it|sure,? go)\b", re.I)
NEGATE = re.compile(r"^\s*(no|nope|nah|n|cancel|don'?t|stop|never ?mind)\b", re.I)
COMMANDS = ("/start", "/help", "/brief", "/questions", "/goals", "/reminders", "/skills", "/voice", "/pause",
            "/resume", "/app")
WHISPER_DEFAULT = "base.en"
_cap = threading.local()   # set while the app is talking to her: replies go to the app, not Telegram


def help_text():
    me = load_config().get("assistant_name") or "Jenna"
    return (f"Hi, I'm {me}. Just talk to me normally - text or voice notes.\n\n"
            "/brief - my morning check-in, now\n/questions - a few get-to-know-you questions\n"
            "/goals - your goals\n/reminders - what's coming up\n/skills - your skills (/name text runs one)\n"
            "/voice - voice reply settings\n/app - the link to open me on this phone\n"
            "/pause - emergency stop: tools and scheduled messages off\n/resume - back on\n/help - this")


class Bot:
    def __init__(self):
        self.token = get_secret("telegram_token")
        self.offset = memory.get_state().get("telegram_offset", 0)
        self._whisper = None
        self._whisper_lock = threading.Lock()

    @property
    def enabled(self):
        return bool(self.token)

    # ---------- raw API ----------
    def api(self, method, http_timeout=30, **params):
        if not self.token:
            raise RuntimeError("Telegram isn't set up")
        r = requests.post(API.format(token=self.token, method=method), json=params, timeout=http_timeout)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
        return data["result"]

    @property
    def owner(self):
        return load_config().get("telegram_user_id")

    # ---------- app capture ----------
    def capture(self):
        class _Ctx:
            def __enter__(self):
                _cap.out = []
                return _cap.out

            def __exit__(self, *_exc):
                _cap.out = None
        return _Ctx()

    @staticmethod
    def _captured():
        return getattr(_cap, "out", None)

    def send(self, text, buttons=None, chat_id=None, quiet=False):
        cap = self._captured()
        if cap is not None and chat_id is None:
            if text:
                cap.append({"type": "text", "text": text})
            return
        if text and not quiet:   # show it live in the open app windows (and buzz the phone if she started it)
            try:
                live.publish("assistant", text, "telegram" if self.enabled else "app",
                             kind="confirm" if buttons else "message",
                             extra={"confirm_id": buttons[0][0]["callback_data"].split(":", 1)[1]} if buttons else None)
            except Exception:
                log.exception("live publish failed")
        chat_id = chat_id or self.owner
        if not self.enabled or not chat_id or not text:
            return
        chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)]
        for n, chunk in enumerate(chunks):
            params = {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True}
            if buttons and n == len(chunks) - 1:
                params["reply_markup"] = {"inline_keyboard": buttons}
            try:
                self.api("sendMessage", **params)
            except Exception:
                log.exception("sendMessage failed")

    def typing(self):
        if self._captured() is not None or not self.enabled or not self.owner:
            return
        try:
            self.api("sendChatAction", chat_id=self.owner, action="typing", http_timeout=10)
        except Exception as e:
            log.debug("typing indicator failed: %r", e)

    def ask_confirmation(self, pending):
        cap = self._captured()
        if cap is not None:
            cap.append({"type": "confirm", "id": pending["id"], "summary": pending["summary"]})
            return
        self.send("Need your OK:\n\n" + pending["summary"],
                  buttons=[[{"text": "Yes, do it", "callback_data": f"yes:{pending['id']}"},
                            {"text": "No", "callback_data": f"no:{pending['id']}"}]])

    # ---------- voice ----------
    def transcribe(self, file_id):
        info = self.api("getFile", file_id=file_id)
        url = f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}"
        path = Path(tempfile.gettempdir()) / f"jenna_lite_voice_{file_id[-10:]}.oga"
        path.write_bytes(requests.get(url, timeout=60).content)
        return self.transcribe_path(path)

    def transcribe_path(self, path):
        """Speech -> text for any audio file (Telegram .oga, app .webm, push-to-talk .wav). Runs on the CPU."""
        path = Path(path)
        try:
            with self._whisper_lock:
                want = load_config().get("whisper_model", WHISPER_DEFAULT)
                if self._whisper is None or getattr(self, "_whisper_name", None) != want:
                    from faster_whisper import WhisperModel
                    self._whisper = WhisperModel(want, device="cpu", compute_type="int8")
                    self._whisper_name = want
                segments, _ = self._whisper.transcribe(str(path), vad_filter=True)
                return " ".join(s.text.strip() for s in segments).strip()
        finally:
            path.unlink(missing_ok=True)

    def send_voice(self, text):
        """Speak `text` as a Telegram voice note (text goes along as the caption). Falls back to plain text."""
        from . import voice
        cap = self._captured()
        if cap is not None:   # the app speaks it itself
            cap.append({"type": "text", "text": text, "speak": True})
            return
        if not self.enabled:
            return self.send(text)
        ogg = None
        try:
            self.api("sendChatAction", chat_id=self.owner, action="record_voice", http_timeout=10)
            ogg = voice.synthesize(text)
            if not ogg:
                return self.send(text)
            caption = text if len(text) <= 1000 else ""
            with open(ogg, "rb") as f:
                r = requests.post(API.format(token=self.token, method="sendVoice"),
                                  data={"chat_id": self.owner, **({"caption": caption} if caption else {})},
                                  files={"voice": ("voice.ogg", f, "audio/ogg")}, timeout=60).json()
            if not r.get("ok"):
                raise RuntimeError(r.get("description"))
            live.publish("assistant", text, "telegram")
            if not caption:
                self.send(text)
        except Exception:
            log.exception("sendVoice failed")
            self.send(text)
        finally:
            if ogg:
                Path(ogg).unlink(missing_ok=True)

    def send_photo(self, path, caption=""):
        """A finished picture to Telegram (falls back to a document for very large files)."""
        if not self.enabled or not self.owner:
            return
        with open(path, "rb") as fh:
            r = requests.post(API.format(token=self.token, method="sendPhoto"), timeout=120,
                              data={"chat_id": self.owner, **({"caption": caption[:1000]} if caption else {})},
                              files={"photo": (Path(path).name, fh)}).json()
        if not r.get("ok"):
            with open(path, "rb") as fh:
                requests.post(API.format(token=self.token, method="sendDocument"), timeout=180,
                              data={"chat_id": self.owner}, files={"document": (Path(path).name, fh)})

    def send_video(self, path, caption=""):
        """A finished video to Telegram (bots can send up to 50 MB; a short clip is a few MB)."""
        if not self.enabled or not self.owner:
            return
        with open(path, "rb") as fh:
            requests.post(API.format(token=self.token, method="sendVideo"), timeout=300,
                          data={"chat_id": self.owner, "supports_streaming": "true", **({"caption": caption[:1000]} if caption else {})},
                          files={"video": (Path(path).name, fh, "video/mp4")})

    def save_photo(self, file_id):
        """Keep the user's latest photo so she can edit it (edit_photo)."""
        from .settings import DATA
        info = self.api("getFile", file_id=file_id)
        media = DATA / "media"
        media.mkdir(parents=True, exist_ok=True)
        path = media / f"photo_{time.strftime('%Y%m%d_%H%M%S')}{Path(info['file_path']).suffix or '.jpg'}"
        path.write_bytes(requests.get(f"https://api.telegram.org/file/bot{self.token}/{info['file_path']}", timeout=60).content)
        memory.set_state(last_photo=str(path))
        return path

    def reply(self, text, from_voice=False):
        if memory.get_state().get("voice_next_reply"):   # she chose to answer out loud (reply_with_voice)
            memory.set_state(voice_next_reply=False)
            return self.send_voice(text)
        mode = load_config().get("voice_replies", "mirror")
        if mode == "always" or (mode == "mirror" and from_voice):
            return self.send_voice(text)
        return self.send(text)

    # ---------- commands ----------
    def voice_command(self, text):
        from . import voice
        from .settings import update_config
        arg = (text.split(maxsplit=1)[1:] or [""])[0].strip().lower()
        if arg in ("on", "always"):
            update_config(voice_replies="always")
            return self.send_voice("Okay! I'll answer everything out loud from now on.")
        if arg == "off":
            update_config(voice_replies="off")
            return self.send("Voice off - text only. (/voice mirror to answer voice notes with voice again.)")
        if arg == "mirror":
            update_config(voice_replies="mirror")
            return self.send("Got it - voice notes get a voice note back, text gets text.")
        if arg in voice.KOKORO_VOICES:
            update_config(voice=arg)
            return self.send_voice(f"Hi, this is my {arg.title()} voice. How do I sound?")
        cfg = load_config()
        return self.send(f"Voice replies: {cfg.get('voice_replies')} | voice: {cfg.get('voice')}\n\n/voice on - always "
                         "talk\n/voice mirror - talk back when you send a voice note\n/voice off - text only\n\nVoices: "
                         + ", ".join(voice.KOKORO_VOICES) + "\n(the app's Menu > Voice has them all, with previews)")

    def command(self, cmd, text):
        """A built-in /command. Returns True if it was one."""
        if cmd in ("/start", "/help"):
            self.send(help_text())
        elif cmd == "/voice":
            self.voice_command(text)
        elif cmd == "/brief":
            self.typing()
            self.send(brain.morning_message())
        elif cmd == "/questions":
            self.typing()
            qs = brain.generate_questions(3)
            msg = "A few questions for you:\n" + "\n".join(f"{i + 1}. {q['text']}" for i, q in enumerate(qs))
            memory.append_history("assistant", msg)
            self.send(msg)
        elif cmd == "/goals":
            self.send(tools.call("list_goals", {})[0])
        elif cmd == "/reminders":
            self.send(tools.call("list_reminders", {})[0])
        elif cmd == "/skills":
            from . import pc_features
            self.send("Your skills (type /name and some text):\n" + "\n".join(
                f"/{s['command']} - {s['description']}" for s in pc_features.list_skills()))
        elif cmd == "/app":
            from . import pc_features
            link = pc_features.phone_link()
            self.send(f"Open me on this phone (first time only - after that use the home-screen icon):\n{link}" if link
                      else "Phone access isn't set up yet. On your PC: Menu > Phone setup.")
        elif cmd == "/pause":
            from . import security
            security.set_paused(True, text[len("/pause"):].strip())
            log.warning("PAUSED via /pause")
            self.send("Paused. My tools and scheduled messages are off. I can still chat, and reminders you set still "
                      "come through. Send /resume to turn me back on.")
        elif cmd == "/resume":
            from . import security
            was = security.paused()
            security.set_paused(False)
            self.send("Back on." if was else "I wasn't paused.")
        else:
            return False
        return True

    # ---------- the shared message pipeline ----------
    def handle_text(self, text, from_voice=False):
        cmd = text.strip().split()[0].lower() if text.strip().startswith("/") else ""
        if cmd in COMMANDS:
            return self.command(cmd, text)
        if cmd:
            from . import pc_features
            skill = pc_features.get_skill(cmd)
            if skill:   # one of their skills, e.g. /humanize <text>
                target = text.strip()[len(cmd):].strip() or memory.last_assistant_message()
                if not target:
                    return self.send(f"Give me some text after /{skill['command']} and I'll run it.")
                self.typing()
                out = brain.run_skill(skill, target)
                memory.append_history("user", text)
                memory.append_history("assistant", out)
                return self.send(out)
        pid = tools.latest_pending()
        if pid and (AFFIRM.search(text) or NEGATE.search(text)) and len(text.split()) <= 6:
            return self.handle_callback({"id": "", "data": f"{'yes' if AFFIRM.search(text) else 'no'}:{pid}",
                                         "message": {}}, typed=True)
        if self.ending_now(text):
            return self.sign_off(text)
        self.typing()
        with busy():
            reply, pendings = brain.respond(text, voice=from_voice)
        self.reply(reply, from_voice=from_voice)
        for p in pendings:
            self.ask_confirmation(p)
        try:
            brain_vault.log_exchange(text, reply, from_voice)
        except Exception:
            log.exception("couldn't log the conversation to the Brain")
        threading.Thread(target=self._learn, args=(text,), name="learn", daemon=True).start()

    @staticmethod
    def _learn(text):
        try:
            n = brain.extract_answers(text)
            if n:
                log.info("saved %d get-to-know answer(s)", n)
        except Exception:
            log.exception("answer extraction failed")

    def ending_now(self, text):
        """A plain goodbye, and nothing open that an 'okay' could be answering."""
        if tools.latest_pending():
            return False
        last, age = turntaking.last_assistant(memory._read_json("history.json", [])[-12:])
        return turntaking.is_sign_off(text, last, age)

    def sign_off(self, text):
        """Stay quiet: a person lets a 'thanks, bye' end the conversation."""
        log.info("sign-off, staying quiet: %s", text[:80])
        memory.append_history("user", text, signoff=True)
        cap = self._captured()
        if cap is not None:
            cap.append({"type": "ended"})

    def handle_callback(self, cq, typed=False):
        if not typed and self.enabled:
            try:
                self.api("answerCallbackQuery", callback_query_id=cq["id"], http_timeout=10)
            except Exception as e:
                log.debug("answerCallbackQuery failed: %r", e)
        verdict, _, aid = (cq.get("data") or "").partition(":")
        action = tools.take_pending(aid)
        msg = cq.get("message", {})
        if not typed and msg.get("message_id"):   # remove the buttons so they can't be tapped twice
            try:
                self.api("editMessageReplyMarkup", chat_id=msg["chat"]["id"], message_id=msg["message_id"],
                         reply_markup={"inline_keyboard": []}, http_timeout=10)
            except Exception as e:
                log.debug("couldn't clear buttons: %r", e)
        if not action:
            return self.send("That request expired - ask me again if you still want it.")
        self.typing()
        with busy():
            if verdict == "yes":
                result, _ = tools.call(action["tool"], action["args"], allow_risky=True)
                reply, pendings = brain.after_confirmation(action["summary"], result, approved=True)
            else:
                reply, pendings = brain.after_confirmation(action["summary"], "", approved=False)
        self.send(reply)
        for p in pendings:
            self.ask_confirmation(p)

    # ---------- Telegram updates ----------
    def try_pair(self, update):
        """The first person to send the pairing code from setup becomes the owner; everyone else is ignored."""
        msg = update.get("message") or {}
        code = memory.get_state().get("pairing_code")
        uid = (msg.get("from") or {}).get("id")
        if code and uid and (msg.get("text") or "").strip() == code and (msg.get("chat") or {}).get("type") == "private":
            from .settings import update_config
            update_config(telegram_user_id=uid)
            memory.set_state(pairing_code=None)
            me = load_config().get("assistant_name") or "Jenna"
            self.send(f"Paired! I'm {me} - I'll only ever listen to you here. Say hi, or type /help.", chat_id=uid)
            live.publish("assistant", "Telegram is connected.", "app", kind="paired")
            log.info("paired with a telegram user")

    def process(self, update):
        owner = self.owner
        if not owner:
            return self.try_pair(update)
        with live.conversation():   # everything sent while answering is a reply, not a notification
            if "callback_query" in update:
                cq = update["callback_query"]
                if cq.get("from", {}).get("id") == owner:
                    self.handle_callback(cq)
                return
            msg = update.get("message") or {}
            if (msg.get("chat") or {}).get("type") != "private" or (msg.get("from") or {}).get("id") != owner:
                return   # only the owner, only in the private chat
            if msg.get("voice") or msg.get("audio"):
                self.typing()
                text = self.transcribe((msg.get("voice") or msg.get("audio"))["file_id"])
                if not text:
                    return self.send("I couldn't make out that voice note - try again?")
                live.publish("user", text, "telegram voice")
                self.send(f'(heard: "{text}")', quiet=True)
                return self.handle_text(text, from_voice=True)
            if msg.get("photo"):
                best = max(msg["photo"], key=lambda p: p.get("file_size", 0))
                self.save_photo(best["file_id"])
                caption = (msg.get("caption") or "").strip()
                live.publish("user", "[photo] " + caption, "telegram")
                return self.handle_text((caption or "I sent you a photo.") + " [They just sent a photo (saved). To change "
                                        "it, use edit_photo with their instruction.]")
            if msg.get("text"):
                live.publish("user", msg["text"], "telegram")
                return self.handle_text(msg["text"])

    def run_forever(self):
        if not self.enabled:
            log.info("telegram not set up - app only")
            while not self.token:   # setup can add it later without a restart
                time.sleep(15)
                self.token = get_secret("telegram_token")
        log.info("telegram polling started")
        while True:
            if not self.token:   # removed in settings: wait quietly until a new one is added
                time.sleep(15)
                self.token = get_secret("telegram_token")
                continue
            try:
                updates = self.api("getUpdates", http_timeout=70, offset=self.offset, timeout=50)
                for u in updates:
                    self.offset = u["update_id"] + 1
                    memory.set_state(telegram_offset=self.offset)
                    try:
                        with busy():
                            self.process(u)
                    except Exception:
                        log.exception("failed handling update")
                        self.send("Sorry - something went wrong on my end handling that. It's in my log.")
            except requests.RequestException:
                time.sleep(5)   # offline / Telegram hiccup
            except Exception as e:
                log.warning("polling error: %s", e)
                self.token = get_secret("telegram_token")   # removed or replaced in settings
                time.sleep(10)
