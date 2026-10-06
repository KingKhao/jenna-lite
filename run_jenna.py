"""Start Jenna Lite. Launched at login by the Startup shortcut the installer adds (pythonw, no window).

Two layers:
  supervisor  (no args) - tiny, stdlib only. Holds the single-instance lock and keeps the worker alive, restarting
              it with back-off after a crash (so one bad moment can never leave her dead).
  worker      (--worker) - the real assistant: the app server, Telegram (if set up), the scheduler, push-to-talk (F8).
Logs: data/jenna.log (worker), data/supervisor.log (supervisor).
"""
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
LOCK_PORT = 8793


def _sup_log(msg):
    (ROOT / "data").mkdir(exist_ok=True)
    with (ROOT / "data" / "supervisor.log").open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def supervise():
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", LOCK_PORT))
    except OSError:
        return   # already running
    _sup_log("supervisor started")
    backoff = 10
    while True:
        started = time.time()
        code = subprocess.call([sys.executable, str(ROOT / "run_jenna.py"), "--worker"], cwd=str(ROOT),
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ran = time.time() - started
        if ran > 600:
            backoff = 10   # it had been running fine - treat as a one-off crash
        _sup_log(f"worker exited with code {code} after {ran:.0f}s - restarting in {backoff}s")
        time.sleep(backoff)
        backoff = min(backoff * 2, 300)


def wait_for_ollama(log):
    import requests
    from jenna.settings import load_config
    for _ in range(60):
        try:
            requests.get(load_config()["ollama_url"] + "/api/tags", timeout=5)
            return
        except requests.RequestException:
            time.sleep(5)
    log.warning("Ollama not reachable after 5 minutes - continuing anyway (the app will say so)")


def worker():
    from jenna.settings import setup_logging
    log = setup_logging()
    try:
        from jenna import pc_api, scheduler
        from jenna.telegram import Bot
    except Exception:
        log.exception("failed to load her code - the supervisor will retry")
        raise
    log.info("Jenna Lite starting")
    bot = Bot()
    # the app comes up first, even before Ollama answers: the setup screen and diagnostics need it
    threading.Thread(target=pc_api.serve, args=(bot,), name="pc-app", daemon=True).start()
    wait_for_ollama(log)
    threading.Thread(target=scheduler.run_forever, args=(bot,), name="scheduler", daemon=True).start()
    from jenna import conn_comfy, conn_slack
    conn_comfy.BOT = bot   # finished pictures go to the app, Telegram and Slack
    threading.Thread(target=conn_slack.run, args=(bot,), name="slack", daemon=True).start()   # idles until Slack is connected
    try:
        from jenna import pc_ptt
        pc_ptt.start(pc_api)
    except Exception:
        log.exception("push-to-talk failed to start (the app still works)")

    def _index():
        try:
            from jenna import memories
            memories.refresh_index()   # catches up with any memory files edited by hand
        except Exception:
            log.exception("memory index refresh failed")
    threading.Thread(target=_index, name="memory-index", daemon=True).start()
    while True:
        try:
            bot.run_forever()
        except Exception:
            log.exception("telegram loop crashed - restarting in 15 s")
            time.sleep(15)


if __name__ == "__main__":
    if "--worker" in sys.argv:
        worker()
    else:
        supervise()
