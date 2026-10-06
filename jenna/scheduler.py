"""Her clock: reminders (checked every 20 s), the morning check-in and the nightly summary into the Brain.

Each job runs at most once a day (the date it last ran is kept in state), and one failing job never stops the
others. /pause stops the scheduled messages; reminders the user set still come through.
"""
import logging
import time
from datetime import datetime

from . import brain, memory
from .settings import load_config

log = logging.getLogger("jenna")
TICK_S = 20
NIGHTLY = "23:30"


def _due(job, at, now):
    """True once per day, from `at` (HH:MM) until midnight, if it hasn't run today."""
    if not at:
        return False
    today = f"{now:%Y-%m-%d}"
    try:
        if memory.get_state().get(f"ran_{job}") == today:
            return False
    except memory.Unreadable:
        return False
    return f"{now:%H:%M}" >= at


def _mark(job, now):
    memory.set_state(**{f"ran_{job}": f"{now:%Y-%m-%d}"})


def tick(bot, now=None):
    now = now or datetime.now()
    for r in memory.pop_due_reminders():
        bot.send(f"⏰ Reminder: {r['text']}")
    cfg = load_config()
    if not cfg.get("setup_done"):
        return
    from . import security
    if security.paused():
        return
    sched = cfg.get("schedule") or {}
    # before noon only: a PC switched on at 9 pm shouldn't say good morning
    if cfg.get("morning_checkin", True) and now.hour < 12 and _due("morning", sched.get("morning"), now):
        _mark("morning", now)   # marked first: a crash must not repeat the message every 20 s
        try:
            msg = brain.morning_message()
            if msg:
                memory.append_history("assistant", msg)
                bot.send(msg)
        except Exception:
            log.exception("morning check-in failed")
    if _due("tokens", "03:00", now):
        _mark("tokens", now)
        try:
            from . import conn_social
            conn_social.refresh()
        except Exception:
            log.exception("token renewal failed")
    if _due("nightly", NIGHTLY, now):
        _mark("nightly", now)
        try:
            brain.nightly_summary()
        except Exception:
            log.exception("nightly summary failed")


def run_forever(bot):
    log.info("scheduler started")
    while True:
        try:
            tick(bot)
        except Exception:
            log.exception("scheduler tick failed")
        time.sleep(TICK_S)
