"""Live updates for the Jenna app windows (PC + phone) and phone push notifications.

Every message (Telegram, PC app, phone app, her own scheduled messages) is published here. Open app windows
get it instantly over a Server-Sent-Events stream; messages she starts on her own (morning check-in, alerts,
follow-ups, reminders) also buzz the user's phone via Web Push, even with the app closed.
"""
import json
import logging
import queue
import threading
import time
import uuid

from .settings import DATA

log = logging.getLogger("jenna")
_clients = []                 # one queue per open app window
_clients_lock = threading.Lock()
_conv = threading.local()     # set while she's answering the user (replies aren't "proactive")
SUBS = DATA / "push_subs.json"
VAPID_KEY = DATA / "vapid_private.pem"
# Web Push needs a contact for the push services (a URL or mailto:). This is the project page, not the user.
PUSH_CONTACT = "https://clinchvalleydigital.com/jenna-lite"


# ---------------- conversation context ----------------
class conversation:
    """`with conversation():` - messages sent inside are replies to the user, not things she started."""
    def __enter__(self):
        _conv.depth = getattr(_conv, "depth", 0) + 1

    def __exit__(self, *_exc):
        _conv.depth -= 1


def in_conversation():
    return getattr(_conv, "depth", 0) > 0


# ---------------- live stream ----------------
def subscribe():
    q = queue.Queue(maxsize=200)
    with _clients_lock:
        _clients.append(q)
    return q


def unsubscribe(q):
    with _clients_lock:
        if q in _clients:
            _clients.remove(q)


def publish(role, text, source="telegram", origin=None, kind="message", extra=None):
    """role: user | assistant. origin: the app window that sent it (it already shows it)."""
    if not text and kind == "message":
        return
    ev = {"id": uuid.uuid4().hex[:10], "kind": kind, "role": role, "text": text, "source": source,
          "origin": origin, "time": time.strftime("%Y-%m-%d %H:%M"), **(extra or {})}
    with _clients_lock:
        clients = list(_clients)
    for q in clients:
        try:
            q.put_nowait(ev)
        except queue.Full:
            pass
    if role == "assistant" and kind == "message" and not in_conversation():
        threading.Thread(target=notify, args=(_name(), text), daemon=True).start()


def _name():
    from .settings import load_config
    return load_config().get("assistant_name") or "Jenna"


# ---------------- phone push notifications ----------------
def _vapid():
    from py_vapid import Vapid
    if not VAPID_KEY.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(VAPID_KEY))
    return Vapid.from_file(str(VAPID_KEY))


def public_key():
    import base64
    from cryptography.hazmat.primitives import serialization
    raw = _vapid().public_key.public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _subs():
    from . import memory
    return memory.read_path(SUBS, [])


def add_subscription(sub):
    subs = [s for s in _subs() if s.get("endpoint") != sub.get("endpoint")]
    subs.append(sub)
    from . import memory
    memory.write_path(SUBS, subs, indent=1)
    return len(subs)


def notify(title, body):
    subs = _subs()
    if not subs:
        return
    from pywebpush import WebPushException, webpush
    payload = json.dumps({"title": title, "body": body[:240]})
    keep = []
    for s in subs:
        try:
            webpush(subscription_info=s, data=payload, vapid_private_key=str(VAPID_KEY),
                    vapid_claims={"sub": PUSH_CONTACT}, ttl=3600)
            keep.append(s)
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code not in (404, 410):      # 404/410 = that phone unsubscribed; drop it
                keep.append(s)
                log.warning("push failed (%s): %s", code, str(e)[:160])
        except Exception:
            keep.append(s)
            log.exception("push failed")
    if len(keep) != len(subs):
        from . import memory
        memory.write_path(SUBS, keep, indent=1)
