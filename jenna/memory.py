"""Her working memory: state, reminders, goals, get-to-know questions and the chat history.

Machine state (JSON) lives in data/. Human-readable copies (goals, answered questions) go into the Brain, under
About-Me/<assistant>/, so the user can read them. Lasting facts about the user are memories (memories.py).
"""
import json
import logging
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .settings import DATA, load_config

_lock = threading.RLock()


def _now():
    return datetime.now()


def my_dir() -> Path:
    """About-Me/<assistant>/ in the Brain: what she keeps for the user to read."""
    from . import brain_vault
    p = brain_vault.vault() / "About-Me" / (load_config().get("assistant_name") or "Jenna")
    p.mkdir(parents=True, exist_ok=True)
    return p


class Unreadable(RuntimeError):
    """A data file exists but can't be read - callers must not treat it as empty (and never overwrite it)."""


def _read_json(name, default):
    return read_path(DATA / name, default)


def _write_json(name, value):
    write_path(DATA / name, value)


def read_path(p, default):
    """The file's JSON, or `default` only when the file doesn't exist yet. A file that exists but can't be read
    (a Windows lock from antivirus or the indexer, a half write) is retried, then its .bak is used; if both fail it
    raises Unreadable. Returning the default there could write {} over real data."""
    p = Path(p)
    if not p.exists():
        return default
    for attempt in range(4):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except OSError:
            time.sleep(0.05 * (attempt + 1))
        except json.JSONDecodeError:
            break
    bak = p.with_name(p.name + ".bak")
    try:
        got = json.loads(bak.read_text(encoding="utf-8"))
        logging.getLogger("jenna").warning("%s unreadable - using its backup copy", p.name)
        return got
    except (OSError, json.JSONDecodeError):
        raise Unreadable(f"{p.name} exists but couldn't be read (left untouched)") from None


def write_path(p, value, indent=2):
    """Atomic write (temp file + rename) that keeps the previous version as <name>.bak."""
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=indent, ensure_ascii=False), encoding="utf-8")
    if p.exists():
        try:
            shutil.copyfile(p, p.with_name(p.name + ".bak"))
        except OSError:
            pass   # the backup is best-effort; the atomic replace below is what matters
    for attempt in range(4):
        try:
            tmp.replace(p)
            return
        except PermissionError:   # Windows: someone has the file open for a moment
            if attempt == 3:
                raise
            time.sleep(0.05 * (attempt + 1))


# ---------------- state ----------------
def get_state():
    with _lock:
        return _read_json("state.json", {})


def set_state(**changes):
    with _lock:
        s = _read_json("state.json", {})
        s.update(changes)
        _write_json("state.json", s)
        return s


# ---------------- get-to-know questions ----------------
def asked_questions():
    with _lock:
        return _read_json("questions.json", [])


def add_questions(texts):
    with _lock:
        qs = _read_json("questions.json", [])
        today = f"{_now():%Y-%m-%d}"
        new = [{"id": uuid.uuid4().hex[:8], "date": today, "text": t.strip(), "answer": None} for t in texts]
        qs += new
        _write_json("questions.json", qs)
        return new


def open_questions(days=2):
    cutoff = f"{_now() - timedelta(days=days):%Y-%m-%d}"
    return [q for q in asked_questions() if q["answer"] is None and q["date"] >= cutoff]


def answer_question(qid, answer):
    with _lock:
        qs = _read_json("questions.json", [])
        for q in qs:
            if q["id"] == qid and q["answer"] is None:
                q["answer"] = answer
                q["answered"] = f"{_now():%Y-%m-%d %H:%M}"
                with (my_dir() / "questions.md").open("a", encoding="utf-8") as f:
                    f.write(f"\n**{q['date']} - {q['text']}**\n{answer}\n")
                break
        _write_json("questions.json", qs)


# ---------------- goals ----------------
def _render_goals(goals):
    lines = ["# Goals", "", f"Tracked by {load_config().get('assistant_name') or 'Jenna'}.", ""]
    for status in ("active", "done", "dropped"):
        group = [g for g in goals if g["status"] == status]
        if not group:
            continue
        lines += [f"## {status.title()}", ""]
        for g in group:
            due = f" (target {g['target_date']})" if g.get("target_date") else ""
            lines.append(f"### {g['title']}{due} `#{g['id']}`")
            if g.get("why"):
                lines.append(f"Why: {g['why']}")
            for n in g.get("progress", [])[-10:]:
                lines.append(f"- {n}")
            lines.append("")
    try:
        (my_dir() / "goals.md").write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        logging.getLogger("jenna").exception("couldn't write goals.md")


def list_goals(status="active"):
    goals = _read_json("goals.json", [])
    return [g for g in goals if status == "all" or g["status"] == status]


def add_goal(title, why="", target_date=""):
    with _lock:
        goals = _read_json("goals.json", [])
        g = {"id": uuid.uuid4().hex[:5], "title": title, "why": why, "target_date": target_date,
             "status": "active", "created": f"{_now():%Y-%m-%d}", "progress": []}
        goals.append(g)
        _write_json("goals.json", goals)
        _render_goals(goals)
        return g


def update_goal(goal_id, progress_note="", status=""):
    with _lock:
        goals = _read_json("goals.json", [])
        for g in goals:
            if g["id"] == str(goal_id).lstrip("#"):
                if progress_note:
                    g["progress"].append(f"{_now():%Y-%m-%d}: {progress_note}")
                if status in ("active", "done", "dropped"):
                    g["status"] = status
                _write_json("goals.json", goals)
                _render_goals(goals)
                return g
        return None


# ---------------- reminders ----------------
def local_dt(value):
    """ISO text or datetime -> naive LOCAL datetime. The model sometimes adds an offset ("...T09:00-04:00");
    comparing that with datetime.now() raised TypeError and the reminder was never set."""
    d = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return d.astimezone().replace(tzinfo=None) if d.tzinfo else d


REMINDER_KEEP_DAYS = 30   # finished one-time reminders older than this are dropped


def add_reminder(text, when, repeat=""):
    when = local_dt(when)
    with _lock:
        rs = _read_json("reminders.json", [])
        r = {"id": uuid.uuid4().hex[:5], "text": text, "when": when.isoformat(timespec="minutes"),
             "repeat": repeat, "done": False}
        rs.append(r)
        _write_json("reminders.json", rs)
        return r


def list_reminders():
    return [r for r in _read_json("reminders.json", []) if not r["done"]]


def cancel_reminder(rid):
    with _lock:
        rs = _read_json("reminders.json", [])
        hit = False
        for r in rs:
            if r["id"] == str(rid).lstrip("#") and not r["done"]:
                r["done"] = True
                hit = True
        _write_json("reminders.json", rs)
        return hit


def pop_due_reminders():
    """Return reminders that are due and advance/close them."""
    with _lock:
        rs = _read_json("reminders.json", [])
        now = _now()
        due = []
        for r in rs:
            if r["done"]:
                continue
            when = local_dt(r["when"])
            if when <= now:
                due.append(dict(r))
                step = {"daily": timedelta(days=1), "weekly": timedelta(weeks=1),
                        "weekdays": timedelta(days=1)}.get(r.get("repeat"))
                if step:
                    nxt = when
                    while nxt <= now:
                        nxt += step
                        while r["repeat"] == "weekdays" and nxt.weekday() >= 5:
                            nxt += timedelta(days=1)
                    r["when"] = nxt.isoformat(timespec="minutes")
                else:
                    r["done"] = True
        cutoff = now - timedelta(days=REMINDER_KEEP_DAYS)
        kept = [r for r in rs if not (r["done"] and local_dt(r["when"]) < cutoff)]
        if due or len(kept) != len(rs):
            _write_json("reminders.json", kept)
        return due


# ---------------- chat history ----------------
HISTORY_CAP = 600


def get_history(limit=24):
    """Recent messages for the model, including past tool calls/results, never starting mid-turn."""
    return _for_model(_read_json("history.json", [])[-limit:])


def _history_key(m):
    return f"{m.get('time', '')}|{m.get('role')}|{(m.get('content') or '')[:80]}"


def get_history_stable(base=16, step=8):
    """Like get_history(base), but the window's first message stays put while it grows to base+step messages,
    then jumps forward once. A window that slid by one every turn changed the start of her prompt each time, so
    Ollama re-read the whole history on every message. The anchor is the message itself, not an index, because
    history.json is capped and its indexes shift."""
    full = _read_json("history.json", [])
    anchor = get_state().get("history_anchor")
    idx = next((i for i in range(len(full) - 1, -1, -1) if _history_key(full[i]) == anchor), None) if anchor else None
    if idx is None or len(full) - idx > base + step:
        idx = max(0, len(full) - base)
        set_state(history_anchor=_history_key(full[idx]) if full else None)
    return _for_model(full[idx:])


def _for_model(h):
    h = list(h)
    while h and h[0]["role"] != "user":
        h.pop(0)
    out = []
    for m in h:
        c = (m.get("content") or "").strip()
        if m["role"] == "assistant" and c.startswith("[") and c.endswith("]") and not m.get("tool_calls"):
            continue   # internal notes ('[I sent the reminder]') - she copied them into replies
        msg = {"role": m["role"], "content": m.get("content", "")}
        if m.get("tool_calls"):
            msg["tool_calls"] = m["tool_calls"]
        if m.get("tool_name"):
            msg["tool_name"] = m["tool_name"]
        out.append(msg)
    return out


def append_history(role, content, **extra):
    with _lock:
        h = _read_json("history.json", [])
        h.append({"role": role, "content": content, "time": f"{_now():%Y-%m-%d %H:%M}", **extra})
        _write_json("history.json", h[-HISTORY_CAP:])


def display_history(n=40):
    """Recent real conversation (no tool steps or internal notes) with times, for the app."""
    out = []
    for m in _read_json("history.json", []):
        c = (m.get("content") or "").strip()
        if m["role"] not in ("user", "assistant") or not c or m.get("tool_calls"):
            continue
        if c.startswith("[") and c.endswith("]"):
            continue
        out.append({"role": m["role"], "content": c, "time": m.get("time", "")})
    return out[-n:]


def last_assistant_message():
    for m in reversed(_read_json("history.json", [])):
        if m["role"] == "assistant" and m.get("content"):
            return m["content"]
    return ""


def history_for_day(day: str):
    return [m for m in _read_json("history.json", [])
            if m.get("time", "").startswith(day) and m["role"] in ("user", "assistant") and m.get("content")]


def clear_history():
    """Settings > 'Clear chat history' (her memories and the Brain stay)."""
    with _lock:
        _write_json("history.json", [])
        set_state(history_anchor=None)
