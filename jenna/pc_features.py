"""Backends for the app's tabs: Today, Notes, Skills, History, Brain, Diagnostics, Logs, Voices, Settings."""
import logging
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import brain_vault, memory
from .settings import DATA, ROOT, get_secret, load_config, update_config

log = logging.getLogger("jenna")
SKILLS_DIR = DATA / "skills"          # the user's skills (seeded from skills/ on first run)
SEED_SKILLS = ROOT / "skills"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def notes_dir():
    return brain_vault.inbox() / "Notes"


# ============================== Today ==============================
def today():
    now = datetime.now()
    day = f"{now:%Y-%m-%d}"
    # appointment reminders ("Coming up at ...") aren't listed: the appointment itself shows above them
    rs = sorted((r for r in memory.list_reminders() if not r["text"].startswith("Coming up at")), key=lambda r: r["when"])
    t12 = lambda r: memory.local_dt(r["when"]).strftime("%I:%M %p").lstrip("0")
    todays = [{"time": t12(r), "hm": r["when"][11:16], "text": r["text"], "repeat": r.get("repeat", "")} for r in rs if r["when"][:10] == day]
    upcoming = [{"when": memory.local_dt(r["when"]).strftime("%a %b %d, ") + t12(r), "text": r["text"]}
                for r in rs if r["when"][:10] > day][:6]
    nxt = next((r for r in todays if r["hm"] >= f"{now:%H:%M}"), None)
    appts, upcoming_appts, cals, cal_error = [], [], [], ""
    try:
        from . import conn_calendar, connections
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        def fmt(e):
            return {"title": e["title"], "time": "All day" if e["all_day"] else f"{e['start']:%I:%M %p}".lstrip("0"),
                    "end": "" if e["all_day"] else f"{e['end']:%I:%M %p}".lstrip("0"), "day": f"{e['start']:%a %b %d}",
                    "location": e["location"], "calendar": e["calendar"], "id": e.get("id", ""),
                    "past": (not e["all_day"]) and e["end"] < now}
        appts = [fmt(e) for e in conn_calendar.appointments(start, start + timedelta(days=1))]
        upcoming_appts = [fmt(e) for e in conn_calendar.appointments(start + timedelta(days=1), start + timedelta(days=8))][:10]
        cals = [connections.BY_ID[i]["name"] for i in connections.connected_ids("calendar")]
    except Exception as e:
        log.exception("appointments for Today failed")
        cal_error = f"Couldn't load calendars ({type(e).__name__})."
    goals = [{"id": g["id"], "title": g["title"], "target": g.get("target_date") or "",
              "last": (g.get("progress") or ["no progress logged yet"])[-1]} for g in memory.list_goals()]
    return {"date": f"{now:%A, %B %d}", "next": nxt, "reminders": todays, "upcoming": upcoming, "goals": goals,
            "appointments": appts, "upcoming_appointments": upcoming_appts, "calendars": cals, "calendar_error": cal_error,
            "notes_today": len([n for n in list_notes(1) if n["date"] == day])}


# ============================== Notes ==============================
def save_note(text, source="app"):
    text = brain_vault.redact((text or "").strip())
    if not text:
        return None
    now = datetime.now()
    d = notes_dir()
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{now:%Y-%m-%d}.md"
    if not f.exists():
        f.write_text(f"---\nsource: notes\ndate: {now:%Y-%m-%d}\n---\n\n# Notes - {now:%A, %B %d, %Y}\n\n", encoding="utf-8")
    with f.open("a", encoding="utf-8") as fh:
        fh.write(f"- **{now:%H:%M}** ({source}) {text}\n")
    return {"time": f"{now:%H:%M}", "date": f"{now:%Y-%m-%d}", "text": text, "source": source}


def list_notes(days=14):
    out = []
    for i in range(days):
        d = datetime.now() - timedelta(days=i)
        f = notes_dir() / f"{d:%Y-%m-%d}.md"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"- \*\*(\d\d:\d\d)\*\* \(([^)]*)\) (.*)", line)
            if m:
                out.append({"date": f"{d:%Y-%m-%d}", "time": m.group(1), "source": m.group(2), "text": m.group(3)})
    out.sort(key=lambda n: (n["date"], n["time"]), reverse=True)
    return out


# ============================== Skills ==============================
RESERVED = {"start", "help", "brief", "questions", "goals", "reminders", "skills", "voice", "pause", "resume", "app"}


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:40]


def _parse_skill(p):
    text = p.read_text(encoding="utf-8")
    meta, body = {}, text
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if m:
        body = m.group(2).strip()
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    slug = p.stem
    return {"id": slug, "name": meta.get("name", slug), "command": meta.get("command", slug),
            "description": meta.get("description", ""), "instructions": body,
            "created": meta.get("created", ""), "updated": meta.get("updated", "")}


def _seed_skills():
    """Copy in the built-in skills she doesn't have yet - on first run, and when an update adds new ones. Each is
    copied once (listed in .seeded.json), so a skill the user deleted or edited is never brought back over theirs."""
    import json
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    seen_file = SKILLS_DIR / ".seeded.json"
    try:
        seen = set(json.loads(seen_file.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = {p.name for p in SKILLS_DIR.glob("*.md")}   # an install from before this list existed
    new = [p for p in SEED_SKILLS.glob("*.md") if p.name not in seen]
    for p in new:
        if not (SKILLS_DIR / p.name).exists():
            shutil.copyfile(p, SKILLS_DIR / p.name)
        seen.add(p.name)
    if new or not seen_file.exists():
        seen_file.write_text(json.dumps(sorted(seen)), encoding="utf-8")


def list_skills():
    _seed_skills()
    return [_parse_skill(p) for p in sorted(SKILLS_DIR.glob("*.md"))]


def get_skill(ref):
    ref = (ref or "").lower().lstrip("/")
    return next((s for s in list_skills() if s["id"] == ref or s["command"].lower() == ref
                 or s["name"].lower() == ref), None)


def save_skill(d):
    _seed_skills()
    slug = _slug(d.get("id") or d.get("name"))
    if not slug:
        raise ValueError("A skill needs a name.")
    command = _slug(d.get("command") or d.get("name")).replace("-", "")
    if command in RESERVED:
        raise ValueError(f"/{command} is already one of her commands - pick another command name.")
    p = SKILLS_DIR / f"{slug}.md"
    created = _parse_skill(p)["created"] if p.exists() else f"{datetime.now():%Y-%m-%d}"
    clean = lambda s: " ".join(str(s or "").split())   # one line each: frontmatter can't be broken by a newline
    p.write_text(f"---\nname: {clean(d.get('name', slug))}\ncommand: {command}\n"
                 f"description: {clean(d.get('description'))}\ncreated: {created}\n"
                 f"updated: {datetime.now():%Y-%m-%d %H:%M}\n---\n\n{(d.get('instructions') or '').strip()}\n",
                 encoding="utf-8")
    return _parse_skill(p)


def delete_skill(ref):
    s = get_skill(ref)
    if not s:
        return False
    trash = SKILLS_DIR / ".deleted"
    trash.mkdir(exist_ok=True)
    shutil.move(str(SKILLS_DIR / f"{s['id']}.md"), str(trash / f"{s['id']}-{int(time.time())}.md"))   # recoverable
    return True


ORBIT = ["decide", "plan", "email", "brainstorm", "meal", "goal", "summarize", "reply", "humanize"]   # the showcase


def constellation():
    """Home screen: nine of her skills orbit the orb as little helpers - the showcase set first, then the user's own."""
    skills = list_skills()
    picked = sorted(skills, key=lambda s: ORBIT.index(s["id"]) if s["id"] in ORBIT else len(ORBIT))[:9]
    return {"agents": [{"id": s["id"], "name": s["name"], "specialty": s["description"]} for s in picked], "working": []}


# ============================== History ==============================
def history(q="", n=100):
    msgs = memory.display_history(2000)
    if q:
        words = q.lower().split()
        msgs = [m for m in msgs if all(w in m["content"].lower() for w in words)]
    return msgs[-n:]


# ============================== Hardware / models ==============================
def _mac():
    """(chip name, usable memory for the model in GB) on a Mac. Apple Silicon shares one pool of memory between the
    processor and graphics, so the model size follows total memory; Intel Macs run on the processor."""
    try:
        ram = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout) / 2**30
        chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None, 0
    if "Apple" not in chip:
        return chip or "Intel Mac", 0
    usable = 12 if ram >= 31 else 8 if ram >= 15 else 4   # leaves room for macOS and her other parts
    return f"{chip} ({ram:.0f} GB unified memory)", usable


def gpu():
    """(name, VRAM in GB) of the NVIDIA card (or a Mac's usable unified memory), or (None, 0)."""
    import sys
    if sys.platform == "darwin":
        return _mac()
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None, 0
    try:
        out = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=_NO_WINDOW).stdout
        name, mem = out.strip().splitlines()[0].rsplit(",", 1)
        return name.strip(), round(int(mem) / 1024, 1)
    except Exception:
        return None, 0


def recommended_model(vram_gb):
    """The biggest qwen3 that fits on the card (and still leaves room for the conversation)."""
    if vram_gb >= 11.5:
        return "qwen3:14b", 12288
    if vram_gb >= 7.5:
        return "qwen3:8b", 8192
    return "qwen3:4b", 8192


def ollama_models():
    import requests
    try:
        r = requests.get(load_config()["ollama_url"] + "/api/tags", timeout=5).json()
        return [m["name"] for m in r.get("models", [])]
    except Exception:
        return None


def has_model(name, models):
    """Ollama lists models with a tag; a bare name means ':latest'."""
    return (name if ":" in name else f"{name}:latest") in models


# ============================== Diagnostics ==============================
def _check(name, fn):
    t = time.time()
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"{type(e).__name__}: {str(e)[:150]}"
    return {"name": name, "ok": ok, "detail": detail, "ms": int((time.time() - t) * 1000)}


def diagnostics():
    cfg = load_config()

    def brain():
        models = ollama_models()
        if models is None:
            return False, "Ollama isn't running - start it from the Start menu (it should start with Windows)."
        if not has_model(cfg["model"], models):
            return False, f"{cfg['model']} isn't downloaded yet - run 'Install Jenna Lite' again."
        return True, f"{cfg['model']} via Ollama"

    def recall():
        models = ollama_models() or []
        return (True, "recall by meaning (nomic-embed-text)") if has_model("nomic-embed-text", models) else \
            (False, "nomic-embed-text missing - memories fall back to keyword recall. Fix: ollama pull nomic-embed-text")

    def voice_files():
        from . import voice
        return (True, "Kokoro voice ready") if voice.available() else (False, "voice files missing - run the installer again")

    def mic():
        from .pc_api import mic_status
        m = mic_status()
        return m["ok"], ", ".join(m["devices"][:2]) or "no real microphone"

    def vault():
        p = brain_vault.vault()
        return p.exists(), str(p) if p.exists() else f"{p} doesn't exist - Menu > Settings to pick the folder"

    def telegram():
        if not get_secret("telegram_token"):
            return None, "not set up (optional) - Menu > Telegram"
        return (True, "connected") if cfg.get("telegram_user_id") else (False, "bot added but not paired - Menu > Telegram")

    def phone():
        if not cfg.get("pc_remote_hosts"):
            return None, "not set up (optional) - Menu > Phone setup"
        return True, cfg["pc_remote_hosts"][0]

    def errors():
        n = len([l for l in _log_lines(3000) if " ERROR " in l and l[:10] == f"{datetime.now():%Y-%m-%d}"])
        return n == 0, f"{n} error(s) logged today" if n else "no errors today"

    return [_check(n, f) for n, f in [("Brain (the AI model)", brain), ("Memory recall", recall), ("Voice", voice_files),
                                      ("Microphone", mic), ("Brain folder", vault), ("Telegram", telegram),
                                      ("Phone access", phone), ("Errors", errors)]]


# ============================== Logs ==============================
def _log_lines(n=500):
    p = DATA / "jenna.log"
    if not p.exists():
        return []
    with p.open("rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 600_000))
        lines = f.read().decode("utf-8", "replace").splitlines()
    return lines[-n:]


def logs(level="problems", n=200):
    lines = _log_lines(4000)
    if level == "problems":
        out, keep = [], False
        for l in lines:
            if re.match(r"\d{4}-\d\d-\d\d ", l):
                keep = (" ERROR " in l) or (" WARNING " in l)
            if keep:
                out.append(l)
        lines = out
    sup = DATA / "supervisor.log"
    return {"jenna": [brain_vault.redact(l) for l in lines[-n:]],
            "supervisor": sup.read_text(encoding="utf-8").splitlines()[-30:] if sup.exists() else []}


# ============================== Voices ==============================
ACCENT = {"a": "American", "b": "British"}
GENDER = {"f": "female", "m": "male"}


def voices():
    from . import voice
    cfg = load_config()
    try:
        all_ids = voice.engine().get_voices()
    except Exception:
        all_ids = list(voice.KOKORO_VOICES.values())
    english = sorted(v for v in all_ids if v[:1] in ACCENT and v[1:2] in GENDER)

    def info(vid):
        return {"id": vid, "name": vid.split("_", 1)[1].title(), "desc": f"{ACCENT[vid[0]]} {GENDER[vid[1]]}"}
    favs = cfg.get("voice_list") or ["af_heart", "af_bella", "bf_emma", "am_michael"]
    return {"current": voice.voice_id(), "speed": float(cfg.get("kokoro_speed", 1.0)), "ready": voice.available(),
            "list": [info(v) for v in favs if v in english], "all": [info(v) for v in english]}


def set_voice(d):
    cfg = load_config()
    favs = cfg.get("voice_list") or ["af_heart", "af_bella", "bf_emma", "am_michael"]
    if d.get("add") and d["add"] not in favs:
        favs.append(d["add"])
    if d.get("remove") and d["remove"] in favs and len(favs) > 1:
        favs.remove(d["remove"])
    changes = {"voice_list": favs}
    if d.get("voice"):
        changes["voice"] = str(d["voice"])[:20]
    if d.get("speed") is not None:
        changes["kokoro_speed"] = round(min(1.3, max(0.7, float(d["speed"]))), 2)
    update_config(**changes)
    return voices()


def preview_voice(voice_id, speed):
    import tempfile
    from . import voice
    if not re.fullmatch(r"[ab][fm]_[a-z]+", voice_id or ""):
        raise ValueError("unknown voice")
    name = voice_id.split("_", 1)[-1].title()
    who = load_config().get("owner_name") or "there"
    wav = Path(tempfile.gettempdir()) / f"jenna_lite_preview_{voice_id}.wav"
    voice.kokoro_wav(f"Hi {who}, this is {name}. Here's how I'd sound talking you through your day.",
                     voice_id, min(1.3, max(0.7, float(speed))), wav)
    return wav


# ============================== Settings ==============================
EDITABLE = {"owner_name": str, "assistant_name": str, "home_city": str, "units": str, "morning_checkin": bool,
            "questions_per_day": int, "voice_replies": str, "ptt_mode": str, "push_to_talk_key": str, "pc_mirror_to_telegram": bool}


def settings():
    from . import brain
    cfg = load_config()
    return {**{k: cfg.get(k) for k in EDITABLE}, "morning_time": (cfg.get("schedule") or {}).get("morning", "07:30"),
            "model": cfg.get("model"), "brain_dir": str(brain_vault.vault()), "personality": brain.personality(),
            "telegram": bool(get_secret("telegram_token")), "paired": bool(cfg.get("telegram_user_id"))}


def save_settings(d):
    from . import brain
    changes = {}
    for k, kind in EDITABLE.items():
        if k in d:
            v = d[k]
            changes[k] = bool(v) if kind is bool else max(0, min(5, int(v))) if kind is int else str(v).strip()[:80]
    if changes.get("units") not in (None, "us", "metric"):
        changes.pop("units")
    if changes.get("voice_replies") not in (None, "mirror", "always", "off"):
        changes.pop("voice_replies")
    if changes.get("ptt_mode") not in (None, "hold", "tap"):
        changes.pop("ptt_mode")
    from . import pc_ptt
    if "push_to_talk_key" in changes:
        changes["push_to_talk_key"] = changes["push_to_talk_key"].lower()
        if changes["push_to_talk_key"] not in pc_ptt.KEYS:
            changes.pop("push_to_talk_key")
    if d.get("morning_time") and re.fullmatch(r"[0-2]\d:[0-5]\d", d["morning_time"]):
        changes["schedule"] = {**(load_config().get("schedule") or {}), "morning": d["morning_time"]}
    if changes:
        update_config(**changes)
    if "push_to_talk_key" in changes or "ptt_mode" in changes:
        pc_ptt.rebind()
    if isinstance(d.get("personality"), str) and d["personality"].strip():
        brain.personality_file().write_text(d["personality"].strip()[:brain.PERSONALITY_MAX] + "\n", encoding="utf-8")
    return settings()


def phone_link():
    """The one-time link that opens her app on the phone (through Tailscale), or '' if not set up."""
    from .pc_api import token
    hosts = load_config().get("pc_remote_hosts") or []
    return f"https://{hosts[0]}/?t={token()}" if hosts else ""
