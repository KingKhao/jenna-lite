"""Hold the push-to-talk key (F8 by default) anywhere on the PC to talk to her; she answers out loud.

Runs inside the worker (same brain + memory). Picks the first real microphone (skips Steam's virtual
ones); with no real mic it plays a warning tone instead of recording silence.
"""
import logging
import tempfile
import threading
import time
import sys
import uuid
from pathlib import Path

from .settings import load_config

log = logging.getLogger("jenna")
RATE = 16000
MAX_SECONDS = 120          # safety stop for tap mode
SILENCE_STOP = 2.5         # tap mode: send after this much quiet when the early transcript isn't available
PEEK_AFTER, FAST_QUIET, SLOW_QUIET = 0.6, 1.0, 2.6   # layered end of turn (same as the app, 2026-10-02)
_state = {"rec": None, "frames": [], "busy": False, "started": 0.0, "key_down": False,
          "last_voice": 0.0, "spoke": False, "peek": None, "playing": False, "cut": False}
_lock = threading.Lock()


def mode():
    return "tap" if load_config().get("ptt_mode", "hold") in ("tap", "toggle") else "hold"


def _pick_mic():
    import sounddevice as sd
    want = (load_config().get("mic_device") or "").lower()
    for i, d in enumerate(sd.query_devices()):
        name = d["name"].lower()
        if d["max_input_channels"] < 1 or "steam" in name or "sound mapper" in name or "primary sound" in name:
            continue
        if not want or want in name:
            return i
    return None


SUPPORTED = sys.platform == "win32"   # macOS: use the mic button in the app (a global hotkey needs Accessibility access)


def _beep(freq, ms):
    import winsound
    threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


def _start():
    import sounddevice as sd
    with _lock:
        if _state["rec"] is not None or _state["busy"]:
            return
        dev = _pick_mic()
        if dev is None:
            _beep(300, 350)   # low buzz = no real microphone plugged in
            log.warning("push-to-talk pressed but no real microphone is connected")
            return
        _state["frames"] = []
        _state["spoke"], _state["last_voice"], _state["peek"] = False, time.time(), None

        def cb(indata, frames, t, status):
            _state["frames"].append(indata.copy())
            if mode() == "tap":   # hands-free: notice when he stops talking
                level = float(abs(indata).mean())
                now = time.time()
                if level > 350:
                    _state["spoke"], _state["last_voice"], _state["peek"] = True, now, None
                    return
                quiet = now - _state["last_voice"] if _state["spoke"] else 0
                pk = _state["peek"]
                if quiet > PEEK_AFTER and pk is None:
                    _state["peek"] = pk = {"since": _state["last_voice"]}
                    threading.Thread(target=_peek, args=(pk, list(_state["frames"])), daemon=True).start()
                done = pk is not None and "text" in pk and pk["since"] == _state["last_voice"]
                if (done and ((pk["finished"] and quiet > FAST_QUIET) or quiet > SLOW_QUIET)) or \
                        (pk is not None and pk.get("failed") and quiet > SILENCE_STOP) or \
                        quiet > SLOW_QUIET + 4 or now - _state["started"] > MAX_SECONDS:
                    threading.Thread(target=_stop, args=(_pc_api,), daemon=True).start()
        try:
            s = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", device=dev, callback=cb)
            s.start()
        except Exception:
            log.exception("couldn't open the microphone")
            _beep(300, 350)
            return
        _state["rec"], _state["started"] = s, time.time()
    log.info("push-to-talk: listening (mic #%s)", dev)
    _beep(880, 90)            # high blip = listening


def _peek(pk, frames):
    """Transcribe what he's said so far while still listening (tap mode); _process reuses it."""
    import numpy as np
    import soundfile as sf
    from . import turntaking
    try:
        wav = Path(tempfile.gettempdir()) / f"jenna_peek_{uuid.uuid4().hex[:8]}.wav"
        sf.write(str(wav), np.concatenate(frames), RATE)
        try:
            text = _pc_api._bot.transcribe_path(wav)
        finally:
            wav.unlink(missing_ok=True)
        pk["finished"] = turntaking.sounds_finished(text)
        pk["text"] = text
    except Exception:
        log.exception("push-to-talk early transcript failed")
        pk["failed"] = True


def _stop(pc_api):
    with _lock:
        s = _state["rec"]
        if s is None:
            return
        _state["rec"] = None
    s.stop()
    s.close()
    _beep(660, 90)            # lower blip = got it
    if mode() == "hold" and time.time() - _state["started"] < 0.5:
        return                # accidental tap in hold mode
    pk = _state["peek"]
    early = pk["text"] if pk and "text" in pk and pk["since"] == _state["last_voice"] else None
    threading.Thread(target=_process, args=(pc_api, list(_state["frames"]), early), daemon=True).start()


def _process(pc_api, frames, early=None):
    import numpy as np
    import soundfile as sf
    _state["busy"], _state["cut"] = True, False
    try:
        audio = np.concatenate(frames) if frames else np.zeros((0, 1), dtype="int16")
        if audio.size < RATE * 0.4 or np.abs(audio).max() < 200:
            log.info("push-to-talk: nothing heard")
            return
        if early is not None:   # transcribed during the pause already
            heard = early
        else:
            wav = Path(tempfile.gettempdir()) / f"jenna_ptt_{uuid.uuid4().hex[:8]}.wav"
            sf.write(str(wav), audio, RATE)
            try:
                heard = pc_api._bot.transcribe_path(wav)
            finally:
                wav.unlink(missing_ok=True)
        if not heard:
            return
        log.info("push-to-talk heard: %s", heard[:120])
        for item in pc_api.handle_message(heard, from_voice=True, speak=True):
            if item.get("type") == "text" and item.get("audio"):
                for url in [item["audio"]] + item.get("audio_more", []):   # sentence by sentence
                    path = pc_api.take_audio(url.rsplit("/", 1)[-1])
                    if path and not _state["cut"]:
                        _state["playing"] = True
                        import winsound
                        winsound.PlaySound(str(path), winsound.SND_FILENAME)
                        _state["playing"] = False
                    if path:
                        Path(path).unlink(missing_ok=True)
                if _state["cut"]:
                    break
    except Exception:
        log.exception("push-to-talk failed")
    finally:
        _state["busy"] = _state["playing"] = False


_pc_api = None


def _cut_in_then_listen():
    """The key while she's talking: stop her mid-sentence (and skip the rest), then listen."""
    from . import memory
    _state["cut"] = True
    import winsound
    winsound.PlaySound(None, 0)          # stops the sound that's playing
    memory.set_state(cut_in=time.time())
    log.info("push-to-talk: cut her off")
    for _ in range(30):                  # her reply loop notices within a moment
        if not _state["busy"]:
            break
        time.sleep(0.05)
    if mode() == "tap" or _state["key_down"]:
        _start()


def _on_press(pc_api):
    if not _state["key_down"]:
        log.info("push-to-talk: %s pressed (%s mode)", key().upper(), mode())
    if _state["key_down"]:
        return            # Windows auto-repeats a held key - only react to the first press
    _state["key_down"] = True
    if _state["busy"] and _state["playing"]:
        threading.Thread(target=_cut_in_then_listen, daemon=True).start()
        return
    if mode() == "hold":
        _start()
    elif _state["rec"] is None:
        _start()          # tap mode: first tap starts...
    else:
        _stop(pc_api)     # ...second tap sends


def _on_release(pc_api):
    _state["key_down"] = False
    if mode() == "hold":
        _stop(pc_api)


KEYS = ("f8", "f9", "f2", "f4", "pause")   # offered in Settings; F9 also opens Edge's Reading mode
_hooks = []


def key():
    k = str(load_config().get("push_to_talk_key") or "f8").lower()
    return k if k in KEYS else "f8"


def start(pc_api):
    global _pc_api
    _pc_api = pc_api
    rebind()


def rebind():
    """(Re)register the hotkey - called at start and when it's changed in Settings, no restart needed."""
    if not SUPPORTED:
        log.info("push-to-talk hotkey: Windows only for now - use the mic in the app")
        return
    try:
        import keyboard
        for h in _hooks:
            try:
                keyboard.unhook(h)
            except (KeyError, ValueError):
                pass
        _hooks.clear()
        k = key()
        _hooks.append(keyboard.on_press_key(k, lambda e: _on_press(_pc_api), suppress=False))
        _hooks.append(keyboard.on_release_key(k, lambda e: _on_release(_pc_api), suppress=False))
        log.info("push-to-talk ready: %s %s", "tap" if mode() == "tap" else "hold", k.upper())
    except Exception:
        log.exception("push-to-talk hotkey unavailable")
