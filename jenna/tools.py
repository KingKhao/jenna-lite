"""Her tools. Risky ones are parked as "pending actions" until the user taps Yes.

Jenna Lite sends every tool on every message (about 20, ~2.5k tokens): a tool list that never changes keeps
Ollama's prompt cache warm, so a repeat message only reads what's new.
"""
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from . import brain_vault, memory, web
from .settings import load_config

log = logging.getLogger("jenna")
MAX_OUT = 3500
_pending = {}          # action_id -> {"tool", "args", "summary", "created"}
_pending_lock = threading.Lock()
CURRENT_USER_TEXT = ""   # set by brain.respond: what the user actually said this turn


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


S = {"type": "string"}

SCHEMAS = [
    _fn("remember", "Save a long-term memory - something worth knowing for months: a lasting fact about the user, how "
        "they want you to work (a preference or a correction), a project decision, who someone is to them, or where "
        "something lives. NOT today's tasks, small talk, secrets, or anyone's contact or health details.",
        {"type": {"type": "string", "enum": ["about-me", "how-i-like-it", "project", "people", "reference"]},
         "hook": {"type": "string", "description": "one line, third person, e.g. 'Likes short answers in the morning'"},
         "why": S, "how_to_apply": S}, ["type", "hook"]),
    _fn("recall_memory", "Search your long-term memories (by meaning). Use before saying you don't know something "
        "about the user.", {"query": S}, ["query"]),
    _fn("forget_memory", "Forget a long-term memory when the user says it's wrong or outdated (they confirm first). "
        "Get the id from recall_memory.", {"id": S}, ["id"]),
    _fn("recall", "Look up something from a PAST conversation with the user (what they said, decided or asked "
        "before). Use when they refer to an earlier chat instead of guessing.", {"query": S}, ["query"]),
    _fn("search_brain", "Search the user's Brain (their notes folder: projects, people, ideas, decisions, past "
        "conversations). Use before saying you don't know something about their life or work.", {"query": S}, ["query"]),
    _fn("read_brain_note", "Read one note from the Brain by its path (e.g. 'Projects/garden.md').", {"path": S}, ["path"]),
    _fn("save_to_brain", "Save something the user wants kept (an idea, decision, plan, list) as its own note in the "
        "Brain's Inbox.", {"title": S, "note": S,
                            "kind": {"type": "string", "enum": ["idea", "decision", "task", "plan", "note"]}},
        ["title", "note"]),
    _fn("propose_brain_edit", "Change an existing note in the Brain, or add a new one outside the Inbox. The user "
        "confirms with Yes first. mode=append adds a section; mode=replace swaps old_text (copied exactly) for text.",
        {"path": S, "mode": {"type": "string", "enum": ["append", "replace"]}, "text": S, "old_text": S},
        ["path", "text"]),
    _fn("take_note", "Save a quick note for the user (when they say take a note / note that / write this down). Use "
        "their words.", {"text": S}, ["text"]),
    _fn("set_reminder", "Remind the user at a specific time (they get it in the app and on Telegram). 'when' is local "
        "time as YYYY-MM-DDTHH:MM.", {"text": S, "when": S,
                                      "repeat": {"type": "string", "enum": ["", "daily", "weekdays", "weekly"]}},
        ["text", "when"]),
    _fn("list_reminders", "List upcoming reminders."),
    _fn("cancel_reminder", "Cancel a reminder by id.", {"reminder_id": S}, ["reminder_id"]),
    _fn("add_goal", "Create a goal for the user to track.", {"title": S, "why": S, "target_date": S}, ["title"]),
    _fn("update_goal", "Log progress on a goal, or mark it done/dropped.",
        {"goal_id": S, "progress_note": S, "status": {"type": "string", "enum": ["", "active", "done", "dropped"]}},
        ["goal_id"]),
    _fn("list_goals", "List the user's goals.", {"status": {"type": "string", "enum": ["active", "done", "all"]}}),
    _fn("calculate", "Calculator. Use it for EVERY number you work out (totals, percentages, tips, splits, "
        "conversions) - never do arithmetic in your head. Supports + - * / ^ %, '15% of 80', sqrt, sin/cos/tan "
        "(degrees), log, ln, 5!, round(x, 2), mean, median, min, max, pi, e.", {"expression": S}, ["expression"]),
    _fn("get_weather", "Real weather forecast (now + daily highs/lows/rain chance). Defaults to the user's home city.",
        {"location": {"type": "string", "description": "City, region (e.g. 'Austin, TX' or 'Leeds, UK')"}}),
    _fn("web_search", "Search the internet (DuckDuckGo). Use for anything current or that you don't know: prices, "
        "news, hours, events, facts. Name the site you used.", {"query": S, "news": {"type": "boolean"}}, ["query"]),
    _fn("read_webpage", "Read the text of a web page (a search result or a link the user sent). Read-only.",
        {"url": S}, ["url"]),
    _fn("check_website", "Check whether a website is up and how fast it loads.", {"url": S}, ["url"]),
    _fn("use_skill", "Apply one of the user's saved skills (listed in your instructions) to some text and return the "
        "result.", {"skill": S, "text": S}, ["skill", "text"]),
    _fn("reply_with_voice", "Send your reply to this message as a voice note (when they ask to hear you)."),
    _fn("add_appointment", "Add an appointment (doctor, meeting, haircut...) to the user's schedule on this PC. It shows on the "
        "Today tab and the 30-minute reminder is AUTOMATIC (don't also call set_reminder). start/end are local time YYYY-MM-DDTHH:MM (end optional: 1 hour).",
        {"title": S, "start": S, "end": S, "location": S, "notes": S}, ["title", "start"]),
    _fn("list_appointments", "The user's appointments for the next few days: the ones added here plus their connected calendars.",
        {"days": {"type": "integer", "description": "how many days ahead (default 7)"}}),
    _fn("cancel_appointment", "Cancel an appointment added here, by its id from list_appointments (connected calendars are read-only).",
        {"appointment_id": S}, ["appointment_id"]),
]


def schemas():
    """Her base tools + the tools for whatever is connected (that part only changes when a connection does)."""
    from . import connections
    return SCHEMAS + connections.tool_schemas()


def _clip(s, n=MAX_OUT):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + f"\n...[truncated {len(s) - n} chars]"


# ---------------- pending actions (Yes / No) ----------------
def _park(tool, args, summary):
    aid = uuid.uuid4().hex[:8]
    with _pending_lock:
        _pending[aid] = {"tool": tool, "args": args, "summary": summary, "created": time.time()}
    return aid


def latest_pending():
    """Most recent still-valid pending action id (for typed 'yes' / 'no' replies)."""
    with _pending_lock:
        live = [(v["created"], k) for k, v in _pending.items() if time.time() - v["created"] <= 3600]
    return max(live)[1] if live else None


def take_pending(aid):
    with _pending_lock:
        a = _pending.pop(aid, None)
    if a and time.time() - a["created"] > 3600:
        return None
    return a


def _needs_confirm(name, args):
    if name in ("read_webpage", "check_website"):
        from . import security
        why = security.outbound_check(str(args.get("url", "")), CURRENT_USER_TEXT)
        if why:
            return f"Open this site?\n{str(args.get('url', ''))[:300]}\n\nAsking because {why}."
    if name == "forget_memory":
        from . import memories
        m = next((m for m in memories.all_memories() if m["id"] == args.get("id")), None)
        return f"Forget this memory?\n\n{m['hook']}" if m else None   # unknown id: runs and says so
    from . import connections
    if name in connections.CONFIRM:
        return connections.confirm_summary(name, args)
    if name == "propose_brain_edit":
        ok, msg, _ = brain_vault.edit_check(args.get("path", ""), args.get("mode", "append"), args.get("text", ""),
                                            args.get("old_text", ""))
        if not ok:
            return None   # runs, and returns the reason it can't be done
        verb = "Replace in" if args.get("mode") == "replace" else "Add to"
        return f"{verb} Brain note {args.get('path')}?\n\n{str(args.get('text', ''))[:700]}"
    return None


def call(name, args, allow_risky=False):
    """Run a tool. Returns (result_text, pending: dict|None)."""
    args = args or {}
    from . import security
    if security.paused():
        return security.PAUSED_RESULT, None
    if name not in {s["function"]["name"] for s in schemas()}:
        return f"There's no tool called {name} (it may need a connection the user hasn't added).", None
    if not allow_risky:
        summary = _needs_confirm(name, args)
        if summary:
            with _pending_lock:   # she sometimes proposes the same thing twice in one turn: one card is enough
                dup = any(v["tool"] == name and v["summary"] == summary and time.time() - v["created"] < 600
                          for v in _pending.values())
            if dup:
                return "PENDING: the user already has Yes/No buttons for exactly this. Don't ask again.", None
            aid = _park(name, args, summary)
            return (f"PENDING: this needs the user's OK (action {aid}). They have Yes/No buttons. Tell them briefly "
                    "what you're waiting on; don't claim it's done."), {"id": aid, "summary": summary}
    try:
        from . import connections
        if name in {s["function"]["name"] for s in connections.tool_schemas()}:
            result = connections.execute(name, args)
            if name in connections.UNTRUSTED and isinstance(result, str):
                result = security.untrusted(connections.UNTRUSTED[name], result)   # anyone can email you
        else:
            result = _execute(name, args)
        if name in security.WEB_TOOLS and isinstance(result, str):
            result = security.flag_web(result)   # page text is data, never instructions
        return security.scrub(result), None
    except web.Blocked as e:
        return f"Not allowed: {e}", None
    except Exception as e:  # tool errors go back to the model, not up the stack
        log.exception("tool %s failed", name)
        return f"Tool error: {type(e).__name__}: {e}", None


_REL = re.compile(r"\bin\s+(an?|one|two|three|four|five|ten|fifteen|twenty|thirty|forty[- ]five|half an?|\d+(?:\.\d+)?)"
                  r"\s*(minutes?|mins?|hours?|hrs?)\b", re.I)
_REL_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
              "twenty": 20, "thirty": 30, "forty five": 45, "forty-five": 45, "half a": 0.5, "half an": 0.5}


def relative_time(text, now=None):
    """'in 20 minutes' / 'in an hour' / 'in half an hour' in the user's own words -> the exact time, else None.
    The code does the clock math: a model once wrote 01:54 for 1:54 PM."""
    m = _REL.search(text or "")
    if not m:
        return None
    raw = m.group(1).lower()
    n = float(raw) if raw[0].isdigit() else _REL_WORDS.get(raw.replace("-", " ") if "forty" in raw else raw, 0)
    if not n:
        return None
    minutes = n * (60 if m.group(2).lower().startswith(("hour", "hr")) else 1)
    return ((now or datetime.now()) + timedelta(minutes=minutes)).replace(second=0, microsecond=0)


def _same_reminder(a, b):
    import difflib
    norm = lambda t: " ".join(re.findall(r"[a-z0-9]+", t.lower().replace("today", "")))
    x, y = norm(a), norm(b)
    return bool(x) and (x == y or difflib.SequenceMatcher(None, x, y).ratio() >= 0.8)


def recall_conversations(query, max_hits=8):
    """Past exchanges that match: recent history first, then the daily logs in the Brain."""
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
    if not words:
        return "Give me a word or two to look for."
    hits = [f"{m['time']} {'User' if m['role'] == 'user' else 'You'}: {m['content'][:300]}"
            for m in memory.display_history(600) if sum(w in m["content"].lower() for w in words) >= min(2, len(words))]
    out = hits[-max_hits:]
    if len(out) < max_hits:
        logs = sorted(brain_vault.convo_dir().glob("*.md"), reverse=True)[:60] if brain_vault.convo_dir().exists() else []
        for p in logs:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if sum(w in line.lower() for w in words) >= min(2, len(words)):
                    out.append(f"{p.stem} {line[:300]}")
                    if len(out) >= max_hits:
                        break
            if len(out) >= max_hits:
                break
    return "\n".join(out) or f"Nothing in our past conversations matches '{query}'."


def _execute(name, a):
    if name == "remember":
        from . import memories
        body = "\n\n".join(x for x in (a.get("hook", ""), f"Why: {a['why']}" if a.get("why") else "",
                                       f"How to apply: {a['how_to_apply']}" if a.get("how_to_apply") else "") if x)
        return memories.save(a.get("type", ""), a.get("hook", ""), body, source="in chat")[1]
    if name == "recall_memory":
        from . import memories
        hits = memories.search(a.get("query", ""), k=6)
        return ("\n".join(f"- {m['id']} [{m['type']}, {m['updated']}] {m['hook']}\n  {m['body'][:400]}" for m, _, _ in hits)
                + "\n(Point-in-time: verify any status or number before relying on it.)") if hits else "No memory matches that."
    if name == "forget_memory":
        from . import memories
        return "Forgotten (moved to memories/_forgotten)." if memories.forget(a.get("id", "")) else \
            "No memory with that id - use recall_memory to find it."
    if name == "recall":
        return _clip(recall_conversations(a.get("query", "")), 3000)
    if name == "search_brain":
        return _clip(brain_vault.search(a.get("query", "")))
    if name == "read_brain_note":
        return _clip(brain_vault.read_note(a.get("path", "")), 6000)
    if name == "save_to_brain":
        return brain_vault.save_note(a.get("title", ""), a.get("note", ""), a.get("kind", "note"))
    if name == "propose_brain_edit":
        return brain_vault.apply_edit(a.get("path", ""), a.get("mode", "append"), a.get("text", ""), a.get("old_text", ""))
    if name == "take_note":
        from . import pc_features
        n = pc_features.save_note(a.get("text", ""), "chat")
        return f"Note saved ({n['time']})." if n else "Nothing to save."
    if name == "set_reminder":
        when = memory.local_dt(a["when"])
        rel = relative_time(CURRENT_USER_TEXT)
        if rel:
            when = rel
        if when < datetime.now() - timedelta(minutes=2):
            return f"Not set: {when:%a %b %d %I:%M %p} has already passed. Ask when they want it."
        # "remind me at 11:30 instead" must move the reminder, not leave the old one too
        moved = [old for old in memory.list_reminders()
                 if not old.get("repeat") and not a.get("repeat") and old["when"][:10] == f"{when:%Y-%m-%d}"
                 and _same_reminder(old["text"], a["text"])]
        covered = next((r for r in memory.list_reminders() if r["text"].startswith("Coming up at")
                        and abs((memory.local_dt(r["when"]) - when).total_seconds()) <= 600), None)
        if covered and not a.get("repeat"):   # the appointment already reminds them then
            return (f"Not needed: the appointment already includes a reminder at {memory.local_dt(covered['when']):%I:%M %p}. "
                    "Just confirm the appointment itself to the user.")
        for old in moved:
            memory.cancel_reminder(old["id"])
        r = memory.add_reminder(a["text"], when, a.get("repeat", ""))
        done = f"Reminder #{r['id']} set for {when:%a %b %d %I:%M %p}" + (f" ({r['repeat']})" if r["repeat"] else "")
        if moved:
            done += " - moved from " + ", ".join(memory.local_dt(o["when"]).strftime("%I:%M %p") for o in moved)
        return done
    if name == "list_reminders":
        rs = memory.list_reminders()
        return "\n".join(f"#{r['id']} {r['when']} {r['text']} {r['repeat']}".strip() for r in rs) or "No reminders."
    if name == "cancel_reminder":
        return "Cancelled." if memory.cancel_reminder(a.get("reminder_id", "")) else "No reminder with that id."
    if name == "add_goal":
        g = memory.add_goal(a["title"], a.get("why", ""), a.get("target_date", ""))
        return f"Goal created #{g['id']}: {g['title']}"
    if name == "update_goal":
        g = memory.update_goal(a.get("goal_id", ""), a.get("progress_note", ""), a.get("status", ""))
        return f"Updated #{g['id']} ({g['status']})" if g else "No goal with that id."
    if name == "list_goals":
        gs = memory.list_goals(a.get("status") or "active")
        return "\n".join(f"#{g['id']} {g['title']} [{g['status']}] target={g.get('target_date') or '-'} "
                         f"last={g['progress'][-1] if g['progress'] else 'no progress yet'}" for g in gs) or "No goals."
    if name == "calculate":
        from . import calc
        return calc.calculate(a.get("expression", ""), a.get("angle_unit"))
    if name == "get_weather":
        cfg = load_config()
        where = a.get("location") or cfg.get("home_city")
        if not where:
            return "I don't know your city yet - which city should I check? (Set it once in Menu > Settings.)"
        return web.weather(where, 7, metric=cfg.get("units") == "metric")
    if name == "web_search":
        mine = brain_vault.search(a["query"], max_hits=3)
        brain_part = "" if mine.startswith("Nothing in the Brain") else \
            ("FROM THE USER'S BRAIN (check this first - it beats the web):\n" + mine[:1500] + "\n\n")
        return _clip(brain_part + "FROM THE INTERNET:\n" + web.search(a["query"], news=bool(a.get("news"))), 5500)
    if name == "read_webpage":
        return _clip(web.read(a["url"]), 6500)
    if name == "check_website":
        return web.check_site(a["url"])
    if name == "use_skill":
        from . import brain, pc_features
        s = pc_features.get_skill(a.get("skill", ""))
        if not s:
            return f"No skill called {a.get('skill')}. Skills: " + ", ".join(x["command"] for x in pc_features.list_skills())
        return _clip(brain.apply_skill(s, a.get("text", "")))
    if name in ("add_appointment", "list_appointments", "cancel_appointment"):
        from . import conn_calendar
        if name == "add_appointment":
            return conn_calendar.add_appointment(a.get("title", ""), a.get("start", ""), a.get("end", ""),
                                                 a.get("location", ""), a.get("notes", ""))[1]
        if name == "list_appointments":
            return conn_calendar.list_text(a.get("days") or 7)
        if conn_calendar.cancel_appointment(a.get("appointment_id", "")):
            return "Cancelled."
        return "No appointment with that id here (connected calendars can only be changed in their own app)."
    if name == "reply_with_voice":
        memory.set_state(voice_next_reply=True)
        return "Your reply to this message will be sent as a voice note."
    return f"There's no tool called {name}."
