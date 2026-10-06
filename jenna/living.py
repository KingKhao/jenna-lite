"""Living documents: plain files the user edits (her personality) that she re-reads every
turn. Cached on (mtime, size) so an unchanged file costs no disk read, and an edit shows up on the very next
message with no restart. Never raises: a missing or unreadable file reads as ''."""
import threading

_cache = {}
_lock = threading.Lock()


def read(path):
    try:
        st = path.stat()
        key = (st.st_mtime_ns, st.st_size)
        with _lock:
            hit = _cache.get(str(path))
            if hit and hit[0] == key:
                return hit[1]
        text = path.read_text(encoding="utf-8-sig").strip()
        with _lock:
            _cache[str(path)] = (key, text)
        return text
    except (OSError, UnicodeDecodeError):
        return ""
