"""The first-run setup (and the Menu pages that redo parts of it): who you are, who she is, her Brain, Telegram,
and phone access through Tailscale. The app's setup screen calls these through /api/setup/*.

Nothing here runs without the user clicking the button for it. Telegram's token goes to Windows Credential Manager;
Tailscale is only ever pointed at her own app on this PC.
"""
import json
import logging
import re
import secrets
import shutil
import subprocess
import threading
from pathlib import Path

import requests

from . import brain_vault, memory, pc_features
from .settings import ROOT, delete_secret, get_secret, load_config, set_secret, update_config

log = logging.getLogger("jenna")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PRESETS = {p.stem: p for p in sorted((ROOT / "personalities").glob("*.md"))}


def _preset_info(p):
    text = p.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    meta = dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l) if m else {}
    return {"id": p.stem, "label": meta.get("label", p.stem).strip(), "blurb": meta.get("blurb", "").strip(),
            "text": (m.group(2) if m else text).strip()}


# ---------------- status ----------------
def status():
    cfg = load_config()
    name, vram = pc_features.gpu()
    models = pc_features.ollama_models()
    rec, _ = pc_features.recommended_model(vram)
    from . import voice
    return {"setup_done": bool(cfg.get("setup_done")), "owner_name": cfg.get("owner_name"),
            "assistant_name": cfg.get("assistant_name"), "home_city": cfg.get("home_city"), "units": cfg.get("units"),
            "personality": cfg.get("personality"), "presets": [_preset_info(p) for p in PRESETS.values()],
            "brain_dir": str(brain_vault.vault()), "brain_default": str(brain_vault.default_dir()),
            "gpu": name, "vram_gb": vram, "model": cfg.get("model"), "recommended_model": rec,
            "ollama": models is not None, "model_ready": bool(models) and pc_features.has_model(cfg["model"], models),
            "voice_ready": voice.available(), "pull": dict(_pull),
            "telegram": telegram_status(), "phone": phone_status()}


# ---------------- step 1: you, her, her Brain ----------------
def save_profile(d):
    owner = " ".join(str(d.get("owner_name", "")).split())[:40]
    me = " ".join(str(d.get("assistant_name", "")).split())[:30] or "Jenna"
    if not owner:
        raise ValueError("Tell her what to call you.")
    preset = d.get("personality") if d.get("personality") in PRESETS else "warm-friend"
    folder = Path(str(d.get("brain_dir") or brain_vault.default_dir()).strip().strip('"')).expanduser()
    if not folder.is_absolute():
        raise ValueError("The Brain folder needs a full path, like C:\\Users\\you\\Documents\\Jenna Brain.")
    units = "metric" if d.get("units") == "metric" else "us"
    update_config(owner_name=owner, assistant_name=me, personality=preset, brain_dir=str(folder),
                  home_city=" ".join(str(d.get("home_city", "")).split())[:60], units=units)
    brain_vault.create(folder)
    custom = str(d.get("personality_text") or "").strip()
    text = custom or _preset_info(PRESETS[preset])["text"]
    text = text.replace("{{owner}}", owner).replace("{{assistant}}", me)
    from . import brain
    pf = brain.personality_file()
    if custom or not pf.exists() or d.get("reset_personality"):
        pf.write_text(text[:brain.PERSONALITY_MAX] + "\n", encoding="utf-8")
    log.info("setup: profile saved, Brain at %s", folder)
    return status()


# ---------------- the AI model ----------------
_pull = {"model": "", "status": "", "done": True, "pct": 0, "error": ""}


def pull_model(name=None):
    """Download a model through Ollama in the background (the app polls status() for progress)."""
    cfg = load_config()
    name = name or cfg["model"]
    if not re.fullmatch(r"[a-z0-9._-]+(:[a-z0-9._-]+)?", name):
        raise ValueError("unknown model name")
    if not _pull["done"]:
        return dict(_pull)
    _pull.update(model=name, status="starting", done=False, pct=0, error="")

    def go():
        try:
            with requests.post(cfg["ollama_url"] + "/api/pull", json={"model": name, "stream": True}, stream=True,
                               timeout=(10, 600)) as r:
                for line in r.iter_lines():
                    if not line:
                        continue
                    ev = json.loads(line)
                    if ev.get("error"):
                        raise RuntimeError(ev["error"])
                    _pull["status"] = ev.get("status", "")
                    if ev.get("total"):
                        _pull["pct"] = int(100 * ev.get("completed", 0) / ev["total"])
            _pull.update(status="ready", pct=100)
        except Exception as e:
            log.exception("model download failed")
            _pull["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        finally:
            _pull["done"] = True
    threading.Thread(target=go, name="model-pull", daemon=True).start()
    return dict(_pull)


def use_model(name):
    _, vram = pc_features.gpu()
    rec, ctx = pc_features.recommended_model(vram)
    allowed = {"qwen3:4b": 8192, "qwen3:8b": 8192, "qwen3:14b": 12288}
    if name not in allowed:
        raise ValueError("pick qwen3:4b, qwen3:8b or qwen3:14b")
    update_config(model=name, num_ctx=allowed[name] if name != rec else ctx)
    return status()


# ---------------- Telegram (optional) ----------------
def telegram_status():
    cfg = load_config()
    if not get_secret("telegram_token"):
        return {"state": "off"}
    st = memory.get_state()
    return {"state": "paired" if cfg.get("telegram_user_id") else "waiting", "bot": st.get("telegram_bot", ""),
            "code": "" if cfg.get("telegram_user_id") else st.get("pairing_code", "")}


def telegram_connect(token):
    token = (token or "").strip()
    if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_-]{30,}", token):
        raise ValueError("That doesn't look like a bot token. It's the long line BotFather sends, like 123456789:AA...")
    try:
        me = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15).json()
    except requests.RequestException:
        raise ValueError("Couldn't reach Telegram - check the internet connection and try again.") from None
    if not me.get("ok"):
        raise ValueError("Telegram didn't accept that token. Copy it again from BotFather (all of it).")
    set_secret("telegram_token", token)
    code = f"{secrets.randbelow(900000) + 100000}"
    memory.set_state(pairing_code=code, telegram_bot=me["result"].get("username", ""))
    update_config(telegram_user_id="")
    log.info("setup: telegram bot added, waiting for pairing")
    return telegram_status()


def telegram_remove():
    delete_secret("telegram_token")
    update_config(telegram_user_id="")
    memory.set_state(pairing_code=None, telegram_bot="")
    return telegram_status()


# ---------------- phone access through Tailscale (optional) ----------------
def _tailscale():
    exe = shutil.which("tailscale")
    if exe:
        return exe
    for p in (Path(r"C:\Program Files\Tailscale\tailscale.exe"), Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe")):
        if p.exists():
            return str(p)
    return None


def _ts(*args, timeout=30):
    exe = _tailscale()
    if not exe:
        raise RuntimeError("Tailscale isn't installed")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW,
                          encoding="utf-8", errors="replace")


def _ts_self():
    r = _ts("status", "--json")
    if r.returncode != 0:
        return None
    st = json.loads(r.stdout or "{}")
    me = st.get("Self") or {}
    users = st.get("User") or {}
    login = (users.get(str(me.get("UserID"))) or {}).get("LoginName", "")
    return {"state": st.get("BackendState"), "host": (me.get("DNSName") or "").rstrip("."), "login": login}


def phone_status():
    cfg = load_config()
    if not _tailscale():
        return {"state": "no-tailscale"}
    try:
        me = _ts_self()
    except Exception as e:
        return {"state": "error", "detail": str(e)[:160]}
    if not me or me["state"] != "Running" or not me["host"]:
        return {"state": "signed-out"}
    on = me["host"] in (cfg.get("pc_remote_hosts") or [])
    return {"state": "on" if on else "ready", "host": me["host"], "login": me["login"],
            "link": pc_features.phone_link() if on else ""}


def phone_enable():
    """Point Tailscale at her app (https on this PC's tailnet name) and allow only this Tailscale account in."""
    from .settings import APP_PORT
    me = _ts_self()
    if not me or me["state"] != "Running":
        raise ValueError("Sign in to Tailscale on this PC first (the Tailscale icon by the clock).")
    r = _ts("serve", "--bg", str(APP_PORT), timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    link = re.search(r"https://login\.tailscale\.com/\S+", out)
    if r.returncode != 0 or link:
        if link:   # HTTPS isn't switched on for this tailnet yet: Tailscale gives a page to enable it
            return {"state": "needs-https", "enable_url": link.group(0)}
        raise ValueError("Tailscale couldn't share the app: " + (out.strip()[-300:] or "unknown error"))
    update_config(pc_remote_hosts=[me["host"]], pc_remote_users=[me["login"]] if me["login"] else [])
    log.info("setup: phone access on via tailscale serve")
    return phone_status()


def phone_disable():
    from .settings import APP_PORT
    try:
        _ts("serve", "--https=443", "off", timeout=30)
    except Exception as e:
        log.warning("tailscale serve off failed: %s", e)
    update_config(pc_remote_hosts=[], pc_remote_users=[])
    log.info("setup: phone access off (port %s)", APP_PORT)
    return phone_status()


def qr_svg(text):
    """A QR code (SVG) of the phone link, so the phone can just scan it off the screen."""
    import io

    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


# ---------------- finish ----------------
def finish():
    cfg = load_config()
    if not cfg.get("owner_name"):
        raise ValueError("Finish the first step (your name and hers) first.")
    brain_vault.create()
    update_config(setup_done=True)
    from . import memories
    memories.write_index()
    log.info("setup finished")
    return status()
