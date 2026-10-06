"""Pictures and photo edits through ComfyUI, a free app the user installs (the "Image & video creation" card).

ComfyUI has a local web API: queue a workflow with POST /prompt, wait on /history/<id>, fetch files from /view.
Workflows live in workflows/*.json in ComfyUI's API format (exported from the official templates), with {{PLACEHOLDER}}
values filled in here. One job at a time; before a job her model is unloaded from the graphics card (they share it),
and afterwards ComfyUI frees its memory so her brain can load back.

Pictures are saved to Pictures/Jenna Lite, shown in the app, sent on Telegram/Slack if connected, and listed in the
Brain (Raw/pictures.md). The same content rules as the full Jenna: PG-13, and hard lines that never move.
"""
import json
import logging
import random
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from . import connections, live, memory
from .settings import ROOT, load_config

log = logging.getLogger("jenna")
WORKFLOWS = ROOT / "workflows"
PORTS = ("http://127.0.0.1:8000", "http://127.0.0.1:8188")   # ComfyUI Desktop, then a manual/portable install
SIZES = {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832)}
DAILY_LIMIT = 30
JOB_TIMEOUT_S = 15 * 60
BOT = None             # set by run_jenna: where finished pictures are delivered
_job = {"running": False}
_lock = threading.Lock()

BLOCKED = re.compile(r"\b(nude|naked|nsfw|porn\w*|sex(ual|y)?|lingerie|topless|explicit|gore|gory|blood(y)?|"
                     r"dismember\w*|beheading|swastika|kkk)\b", re.I)
MINORS = re.compile(r"\b(child(ren)?|kids?|minors?|underage|teen(age(r|d)?|s)?|preteen|toddler|infant|bab(y|ies)|"
                    r"school ?(girl|boy)s?|young (girl|boy)s?|little (girl|boy)s?|[1-9] ?(yo|year[- ]old)|1[0-7] ?(yo|year[- ]old))\b", re.I)
REAL_PEOPLE = re.compile(r"\b(taylor swift|elon musk|donald trump|joe biden|barack obama|kamala harris|beyonc[eé]|"
                         r"president of|celebrity|famous person)\b", re.I)
LOGO_FAKE = re.compile(r"\b(official|real) (logo|ad|advert\w*) (of|for) (nike|apple|coca.?cola|mcdonald'?s|walmart|amazon|google|disney)\b", re.I)


def pictures_dir() -> Path:
    p = Path.home() / "Pictures" / "Jenna Lite"
    p.mkdir(parents=True, exist_ok=True)
    return p


def base_url(f=None):
    f = f or connections.saved("image_video") or {}
    return (f.get("url") or "").rstrip("/") or PORTS[0]


# ---------------- connecting ----------------
def _get(url, path, timeout=10):
    r = requests.get(url + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def installed_models(url):
    """{'diffusion_models': [...], 'text_encoders': [...], 'vae': [...]} - what ComfyUI can load right now."""
    out = {}
    for folder in ("diffusion_models", "text_encoders", "vae", "checkpoints"):
        try:
            out[folder] = _get(url, f"/models/{folder}")
        except Exception:
            out[folder] = []
    return out


def manifest(name):
    return json.loads((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))


def missing_models(url, name):
    """The model files a workflow needs that aren't installed (with the template that downloads them)."""
    have = installed_models(url)
    need = manifest(name)["models"]
    return [m for m in need if m["file"] not in have.get(m["folder"], [])]


def test(f):
    tried = [f["url"].rstrip("/")] if f.get("url") and f["url"] != "auto" else list(PORTS)
    for url in tried:
        if not re.fullmatch(r"http://(127\.0\.0\.1|localhost):\d{2,5}", url):
            raise ValueError("Use ComfyUI's address on this computer, like http://127.0.0.1:8000.")
        try:
            stats = _get(url, "/system_stats", timeout=5)
        except Exception:
            continue
        gone = missing_models(url, "picture")
        dev = ((stats.get("devices") or [{}])[0].get("name") or "").split(":")[-1].strip()
        if gone:
            raise ValueError(f"ComfyUI is running at {url}, but the picture model isn't downloaded yet ({gone[0]['file']}). "
                             f"In ComfyUI, open Workflow > Browse Templates > {gone[0]['template']} once and let it download, "
                             "then press Test & connect again.")
        return {"url": url, "account": f"ComfyUI at {url.split('//')[1]}" + (f" ({dev})" if dev else "")}
    raise ValueError("ComfyUI isn't running. Open ComfyUI Desktop (or start your ComfyUI), wait until it's ready, then "
                     "press Test & connect again.")


# ---------------- rules ----------------
def _today_count():
    day = f"{datetime.now():%Y-%m-%d}"
    return sum(1 for j in memory._read_json("pictures.json", []) if j.get("date") == day and j.get("ok"))


def check(prompt, count=1, edit=False):
    """None if it may run, else the reason it won't."""
    if _job["running"]:
        return "I'm already making a picture - one at a time. It'll show up here when it's done."
    text = prompt or ""
    if MINORS.search(text) and (BLOCKED.search(text) or re.search(r"\b(bikini|swimsuit|kiss\w*|romantic|sexy)\b", text, re.I)):
        return "Not making that. Anything sexual or suggestive involving young people is a hard no."
    if BLOCKED.search(text):
        return "Pictures I make stay PG-13 - nothing sexual, gory or hateful."
    if REAL_PEOPLE.search(text) and not edit:
        return "I don't make pictures of real, famous people - try a made-up character instead."
    if LOGO_FAKE.search(text):
        return "I won't make something that passes for a real company's official ad or logo."
    if len(text.strip()) < (8 if edit else 25):
        return ("PROMPT TOO SHORT - describe the picture properly (subject, setting, style, colors, lighting, and any exact "
                "text in double quotes), then try again." if not edit else "Say what to change in the photo.")
    if _today_count() + count > DAILY_LIMIT:
        return f"That would pass my {DAILY_LIMIT}-pictures-a-day limit. Tomorrow's a new day."
    return None


# ---------------- running a job ----------------
def _fill(node, values):
    """Replace "{{NAME}}" strings anywhere in the workflow (numbers stay numbers)."""
    if isinstance(node, dict):
        return {k: _fill(v, values) for k, v in node.items()}
    if isinstance(node, list):
        return [_fill(v, values) for v in node]
    if isinstance(node, str) and node.startswith("{{") and node.endswith("}}"):
        return values[node[2:-2]]
    return node


def _unload_her_brain():
    """They share the graphics card: tell Ollama to drop its models before a picture (it reloads on her next turn)."""
    url = load_config()["ollama_url"]
    try:
        for m in requests.get(url + "/api/ps", timeout=10).json().get("models", []):
            requests.post(url + "/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
        time.sleep(2)
    except Exception as e:
        log.info("couldn't unload the model before a picture: %s", e)


def _upload_photo(url, path):
    with open(path, "rb") as fh:
        r = requests.post(url + "/upload/image", files={"image": (f"jl_{uuid.uuid4().hex[:8]}{Path(path).suffix}", fh)},
                          data={"overwrite": "true"}, timeout=60)
    r.raise_for_status()
    d = r.json()
    return (d.get("subfolder") + "/" if d.get("subfolder") else "") + d["name"]


def _run_one(url, name, values):
    wf = _fill(manifest(name)["workflow"], values)
    r = requests.post(url + "/prompt", json={"prompt": wf, "client_id": "jenna-lite"}, timeout=30)
    if r.status_code != 200:
        err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise RuntimeError(f"ComfyUI refused the job: {(err.get('error') or {}).get('message') or r.text[:200]}")
    pid = r.json()["prompt_id"]
    started = time.time()
    while time.time() - started < JOB_TIMEOUT_S:
        time.sleep(2)
        h = requests.get(f"{url}/history/{pid}", timeout=15).json().get(pid)
        if not h:
            continue
        status = (h.get("status") or {}).get("status_str")
        if status == "error":
            msgs = [m for m in (h.get("status") or {}).get("messages", []) if m and m[0] == "execution_error"]
            raise RuntimeError("ComfyUI hit an error: " + (msgs[0][1].get("exception_message", "")[:200] if msgs else "unknown"))
        files = [img for out in (h.get("outputs") or {}).values() for img in out.get("images", []) if img.get("type") == "output"]
        if files:
            saved = []
            for img in files:
                data = requests.get(url + "/view", params={"filename": img["filename"], "subfolder": img.get("subfolder", ""),
                                                          "type": "output"}, timeout=60).content
                dest = pictures_dir() / f"{datetime.now():%Y-%m-%d %H%M%S} {re.sub(r'[^a-z0-9]+', '-', values.get('TITLE', 'picture').lower())[:40]}{Path(img['filename']).suffix or '.png'}"
                n = 2
                while dest.exists():
                    dest = dest.with_name(f"{dest.stem}-{n}{dest.suffix}")
                    n += 1
                dest.write_bytes(data)
                saved.append(dest)
            return saved
    raise RuntimeError("ComfyUI took longer than 15 minutes - stopped waiting.")


def _deliver(paths, prompt, edit):
    names = [p.name for p in paths]
    text = ("Here's your edited photo" if edit else ("Here's your picture" if len(paths) == 1 else "Here are your pictures")) \
        + f" - saved in Pictures/Jenna Lite."
    live.publish("assistant", text, "app", kind="images", extra={"images": [f"/api/pictures/{n}" for n in names]})
    memory.append_history("assistant", f"{text} ({', '.join(names)})")
    bot = BOT
    if bot is not None:
        try:
            if bot.enabled and bot.owner:
                for p in paths:
                    bot.send_photo(p, text if p == paths[0] else "")
        except Exception:
            log.exception("couldn't send the picture to Telegram")
        try:
            from . import conn_slack
            conn_slack.send_files(paths, text)
        except Exception:
            log.exception("couldn't send the picture to Slack")
    try:
        from . import brain_vault
        log_file = brain_vault.vault() / "Raw" / "pictures.md"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"- {datetime.now():%Y-%m-%d %H:%M} {'edit' if edit else 'picture'}: {brain_vault.redact(prompt)[:300]} -> "
                     f"{', '.join(names)}\n")
    except Exception:
        log.exception("couldn't log the picture in the Brain")


def _job_thread(name, prompts_values, prompt, edit, count):
    url = base_url()
    ok, outs, err = False, [], ""
    t0 = time.time()
    try:
        _unload_her_brain()
        for values in prompts_values:
            outs += _run_one(url, name, values)
        ok = bool(outs)
    except requests.RequestException:
        err = "ComfyUI stopped answering - is it still open?"
    except Exception as e:
        err = str(e)[:300]
        log.exception("picture job failed")
    finally:
        try:
            requests.post(url + "/free", json={"unload_models": True, "free_memory": True}, timeout=30)
        except Exception as e:
            log.debug("ComfyUI /free: %r", e)
        _job["running"] = False
        with memory._lock:
            jobs = memory._read_json("pictures.json", [])
            jobs.append({"date": f"{datetime.now():%Y-%m-%d}", "ok": ok, "count": count, "edit": edit,
                         "minutes": round((time.time() - t0) / 60, 1), "files": [p.name for p in outs], "error": err})
            memory._write_json("pictures.json", jobs[-500:])
    if ok:
        _deliver(outs, prompt, edit)
    else:
        msg = f"I couldn't finish that picture: {err or 'nothing came back'}"
        live.publish("assistant", msg, "app")
        if BOT is not None:
            BOT.send(msg)


def start_picture(prompt, aspect="square", count=1):
    count = max(1, min(int(count or 1), 4))
    why = check(prompt, count)
    if why:
        return why
    url = base_url()
    gone = missing_models(url, "picture")
    if gone:
        return f"The picture model isn't downloaded in ComfyUI yet - open the {gone[0]['template']} template there once."
    w, h = SIZES.get(aspect, SIZES["square"])
    title = " ".join(prompt.split()[:6])
    values = [{"PROMPT": prompt, "SEED": random.randint(1, 2**31 - 1), "WIDTH": w, "HEIGHT": h, "TITLE": title} for _ in range(count)]
    with _lock:
        if _job["running"]:
            return check(prompt, count)
        _job["running"] = True
    threading.Thread(target=_job_thread, args=("picture", values, prompt, False, count), name="pictures", daemon=True).start()
    return (f"Started: {count} {'picture' if count == 1 else 'pictures'} ({aspect}). About a minute each (longer the first "
            "time while ComfyUI loads the model). It'll appear in the chat when it's ready. Tell the user that.")


def start_edit(instruction):
    why = check(instruction, 1, edit=True)
    if why:
        return why
    photo = memory.get_state().get("last_photo")
    if not photo or not Path(photo).exists():
        return "There's no photo to edit yet - ask the user to send one (the paperclip in the app chat, or a photo on Telegram)."
    url = base_url()
    gone = missing_models(url, "edit")
    if gone:
        return f"The photo-edit model isn't downloaded in ComfyUI yet - open the {gone[0]['template']} template there once."
    try:
        image = _upload_photo(url, photo)
    except Exception as e:
        return f"Couldn't hand the photo to ComfyUI ({type(e).__name__}) - is it open?"
    values = [{"PROMPT": instruction, "SEED": random.randint(1, 2**31 - 1), "IMAGE": image, "TITLE": "edit " + " ".join(instruction.split()[:5])}]
    with _lock:
        if _job["running"]:
            return check(instruction, 1, edit=True)
        _job["running"] = True
    threading.Thread(target=_job_thread, args=("edit", values, instruction, True, 1), name="pictures", daemon=True).start()
    return "Started editing the photo - about a minute. It'll appear in the chat when it's ready. Tell the user that."
