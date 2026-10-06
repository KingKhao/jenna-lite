"""Config, paths and secret storage.

Secrets (the Telegram bot token) live only in Windows Credential Manager via `keyring` - never in config.json,
the logs or the Brain folder.
"""
import json
import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# JENNA_CONFIG / JENNA_DATA let tests run against a scratch copy instead of the real setup
CONFIG_PATH = Path(os.environ.get("JENNA_CONFIG", ROOT / "config.json"))
DATA = Path(os.environ.get("JENNA_DATA", ROOT / "data"))
DATA.mkdir(parents=True, exist_ok=True)

KEYRING_SERVICE = "jenna-lite"
APP_PORT = 8794          # the app (her own ports, so she can run next to another Jenna on the same PC)
LOCK_PORT = 8793         # single-instance lock for the supervisor
_lock = threading.Lock()

DEFAULTS = {
    "setup_done": False,
    "owner_name": "",
    "assistant_name": "Jenna",
    "personality": "warm-friend",
    "model": "qwen3:8b",
    "ollama_url": "http://127.0.0.1:11434",
    "num_ctx": 8192,
    "brain_dir": "",
    "telegram_user_id": "",
    "units": "us",                 # us (F, mph) or metric (C, km/h)
    "home_city": "",
    "schedule": {"morning": "07:30", "evening": "21:00"},
    "morning_checkin": True,
    "questions_per_day": 1,
    "whisper_model": "base.en",
    "voice": "heart",
    "kokoro_speed": 1.0,
    "voice_replies": "mirror",     # mirror | always | off (Telegram voice notes)
    "ptt_mode": "hold",
    "push_to_talk_key": "f8",     # F9 is Edge's Reading mode shortcut, so it fought the app window
    "pc_remote_hosts": [],         # her Tailscale address, once the phone is set up
    "pc_remote_users": [],         # the Tailscale login(s) allowed in
    "pc_mirror_to_telegram": True,
}


def load_config() -> dict:
    with _lock:
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            saved = {}
        return {**DEFAULTS, **saved}


def update_config(**changes) -> dict:
    with _lock:
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            cfg = {}
        cfg.update(changes)
        # atomic: a crash mid-write must never leave a half config.json she can't start from
        tmp = CONFIG_PATH.with_name(CONFIG_PATH.name + ".tmp")
        tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
        return {**DEFAULTS, **cfg}


def owner() -> str:
    return load_config().get("owner_name") or "you"


def name() -> str:
    return load_config().get("assistant_name") or "Jenna"


def get_secret(key: str):
    import keyring
    return keyring.get_password(KEYRING_SERVICE, key)


def set_secret(key: str, value: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, key, value)


def delete_secret(key: str) -> None:
    import keyring
    try:
        keyring.delete_password(KEYRING_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass


_busy = 0
_busy_lock = threading.Lock()


class busy:
    """`with busy():` marks her as mid-task (a restart waits until she's done)."""
    def __enter__(self):
        global _busy
        with _busy_lock:
            _busy += 1

    def __exit__(self, *_exc):
        global _busy
        with _busy_lock:
            _busy -= 1


def is_busy() -> bool:
    return _busy > 0


def setup_logging() -> logging.Logger:
    log = logging.getLogger("jenna")
    if not log.handlers:
        log.setLevel(logging.INFO)
        h = RotatingFileHandler(DATA / "jenna.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
        log.addHandler(h)
    return log
