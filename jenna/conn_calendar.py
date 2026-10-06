"""Calendars and appointments.

- Connected calendars are read-only: Google / Outlook / any app through its private iCal (ICS) link, Apple iCloud
  through CalDAV with an app-specific password. Fetched at most every 10 minutes.
- Appointments she adds herself ("dentist Thursday at 2") are kept on this PC (data/appointments.json), get a
  reminder before they start, and show on the Today tab next to the calendar events.
"""
import logging
import threading
import time
import uuid
from datetime import date, datetime, timedelta

import requests

from . import connections, memory

log = logging.getLogger("jenna")
CACHE_S = 600
REMIND_BEFORE_MIN = 30
_cache = {}            # pid -> (time, events)
_lock = threading.Lock()


# ---------------- connected calendars ----------------
def _ics_url(u):
    u = (u or "").strip()
    if u.startswith("webcal://"):
        u = "https://" + u[len("webcal://"):]
    if not u.startswith("https://"):
        raise ValueError("That should be an https:// (or webcal://) calendar link.")
    return u


def _fetch_ics(url):
    from . import web
    url = _ics_url(url)
    web._check_url(url)   # public internet only
    r = web._get_checked(url, timeout=25, headers={"User-Agent": "JennaLite/1.0 (calendar)"})
    if r.status_code != 200:
        raise ValueError(f"The calendar link answered with an error ({r.status_code}). Copy it again.")
    data = r.content[:15_000_000]
    if b"BEGIN:VCALENDAR" not in data[:4000]:
        raise ValueError("That link isn't a calendar file. Use the iCal / ICS address (Google: 'Secret address in iCal format').")
    return data


def _as_dt(v, end=False):
    if isinstance(v, datetime):
        return v.astimezone().replace(tzinfo=None) if v.tzinfo else v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    return None


def _events_from_ics(data, start, end, label):
    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        s, e = ev.get("DTSTART"), ev.get("DTEND")
        if not s:
            continue
        all_day = not isinstance(s.dt, datetime)
        sd = _as_dt(s.dt)
        ed = _as_dt(e.dt) if e else sd + (timedelta(days=1) if all_day else timedelta(hours=1))
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        out.append({"title": str(ev.get("SUMMARY", "(busy)")), "start": sd, "end": ed, "all_day": all_day,
                    "location": str(ev.get("LOCATION", "") or ""), "calendar": label})
    return out


def _icloud_events(f, start, end):
    import caldav
    with caldav.DAVClient(url="https://caldav.icloud.com", username=f["username"], password=f["password"].replace(" ", ""),
                          timeout=30) as client:
        out = []
        for cal in client.principal().calendars():
            try:
                for item in cal.search(start=start, end=end, event=True, expand=True):
                    out += _events_from_ics(item.data.encode() if isinstance(item.data, str) else item.data, start, end,
                                            cal.name or "iCloud")
            except Exception as e:
                log.info("iCloud calendar %s skipped: %s", getattr(cal, "name", "?"), e)
        return out


def _events_for(pid, start, end, f=None):
    f = f or {**(connections.saved(pid) or {}), **connections.secrets(pid)}
    label = f.get("label") or connections.BY_ID[pid]["name"]
    if pid == "icloud_cal":
        return _icloud_events(f, start, end)
    return _events_from_ics(_fetch_ics(f.get("url", "")), start, end, label)


def test(pid, f):
    now = datetime.now()
    try:
        evs = _events_for(pid, now - timedelta(days=1), now + timedelta(days=14), f)
    except ValueError:
        raise
    except Exception as e:
        if pid == "icloud_cal":
            raise ValueError("Apple didn't accept that Apple ID and app-specific password.") from e
        raise ValueError(f"Couldn't read that calendar ({type(e).__name__}).") from e
    return {"account": f.get("label") or (f.get("username") if pid == "icloud_cal" else "") or connections.BY_ID[pid]["name"],
            "events_found": len(evs)}


def calendar_events(start, end):
    """Events from every connected calendar between start and end (cached per calendar)."""
    out = []
    for pid in connections.connected_ids("calendar"):
        with _lock:
            hit = _cache.get(pid)
        if hit and time.time() - hit[0] < CACHE_S and hit[1] <= start and hit[2] >= end:
            evs = hit[3]
        else:
            lo, hi = min(start, datetime.now() - timedelta(days=1)), max(end, datetime.now() + timedelta(days=31))
            try:
                evs = _events_for(pid, lo, hi)
                with _lock:
                    _cache[pid] = (time.time(), lo, hi, evs)
            except Exception as e:
                log.warning("calendar %s unavailable: %s", pid, e)
                continue
        out += [e for e in evs if e["end"] > start and e["start"] < end]
    return out


# ---------------- her own appointments (on this PC) ----------------
def _load():
    return memory._read_json("appointments.json", [])


def add_appointment(title, start, end="", location="", notes=""):
    s = memory.local_dt(start)
    e = memory.local_dt(end) if end else s + timedelta(hours=1)
    if e <= s:
        e = s + timedelta(hours=1)
    if s < datetime.now() - timedelta(minutes=5):
        return None, f"Not added: {s:%a %b %d %I:%M %p} has already passed."
    import difflib
    for x in _load():   # the model sometimes calls this twice in one turn: same thing, same time = already there
        if memory.local_dt(x["start"]) == s and difflib.SequenceMatcher(None, x["title"].lower(), title.lower().strip()).ratio() > 0.7:
            return x, f"Already on the schedule: {x['title']}, {s:%a %b %d %I:%M %p} (#{x['id']}). Not added twice."
    a = {"id": uuid.uuid4().hex[:5], "title": title.strip()[:120], "start": s.isoformat(timespec="minutes"),
         "end": e.isoformat(timespec="minutes"), "location": location.strip()[:120], "notes": notes.strip()[:500]}
    remind_at = s - timedelta(minutes=REMIND_BEFORE_MIN)
    if remind_at > datetime.now():
        a["reminder"] = memory.add_reminder(f"Coming up at {s:%I:%M %p}: {a['title']}"
                                            + (f" ({a['location']})" if a["location"] else ""), remind_at)["id"]
    with memory._lock:
        items = _load()
        items.append(a)
        memory._write_json("appointments.json", [x for x in items if memory.local_dt(x["end"]) > datetime.now() - timedelta(days=60)])
    return a, (f"Appointment #{a['id']} added: {a['title']}, {s:%a %b %d %I:%M %p}" + (f" at {a['location']}" if a["location"] else "")
               + (f". I'll remind you {REMIND_BEFORE_MIN} minutes before." if a.get("reminder") else "."))


def cancel_appointment(aid):
    with memory._lock:
        items = _load()
        hit = next((x for x in items if x["id"] == str(aid).lstrip("#")), None)
        if not hit:
            return False
        memory._write_json("appointments.json", [x for x in items if x is not hit])
    if hit.get("reminder"):
        memory.cancel_reminder(hit["reminder"])
    return True


def appointments(start, end):
    """Her appointments + connected calendar events between start and end, sorted. Each: title, start, end, all_day,
    location, calendar, id (hers only)."""
    mine = [{"title": a["title"], "start": memory.local_dt(a["start"]), "end": memory.local_dt(a["end"]), "all_day": False,
             "location": a.get("location", ""), "calendar": "Added by her", "id": a["id"]} for a in _load()]
    mine = [a for a in mine if a["end"] > start and a["start"] < end]
    return sorted(mine + calendar_events(start, end), key=lambda e: (e["start"], not e["all_day"]))


def describe(evs, with_day=True):
    if not evs:
        return "Nothing on the calendar."
    lines = []
    for e in evs:
        when = (f"{e['start']:%a %b %d}, " if with_day else "") + ("all day" if e["all_day"] else f"{e['start']:%I:%M %p}-{e['end']:%I:%M %p}")
        lines.append(f"- {when}: {e['title']}" + (f" @ {e['location']}" if e["location"] else "")
                     + f" [{e['calendar']}" + (f", #{e['id']}" if e.get("id") else "") + "]")
    return "\n".join(lines)


def list_text(days=7):
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    evs = appointments(start, start + timedelta(days=max(1, min(int(days or 7), 60))))
    cals = [connections.BY_ID[i]["name"] for i in connections.connected_ids("calendar")]
    src = f"(from {', '.join(cals)} and appointments added here)" if cals else "(appointments added here - no calendar connected yet)"
    return f"{src}\n{describe(evs)}"
