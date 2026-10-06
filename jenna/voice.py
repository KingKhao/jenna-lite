"""Her voice: Kokoro text-to-speech (runs locally) -> a .wav for the app, or an OGG voice note for Telegram.

The model files (kokoro-v1.0.onnx, voices-v1.0.bin) are downloaded by the installer into voices/.
"""
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from .settings import ROOT, load_config

log = logging.getLogger("jenna")
KOKORO_DIR = ROOT / "voices"
MAX_SPOKEN_CHARS = 900
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
KOKORO_VOICES = {  # friendly name -> kokoro voice id (54 exist; the app lists every English one)
    "heart": "af_heart", "bella": "af_bella", "nicole": "af_nicole", "sarah": "af_sarah",
    "aoede": "af_aoede", "kore": "af_kore", "emma": "bf_emma", "isabella": "bf_isabella",
    "michael": "am_michael", "fenrir": "am_fenrir", "george": "bm_george", "lewis": "bm_lewis",
}
_kokoro = None
_kokoro_lock = threading.Lock()


def available():
    return (KOKORO_DIR / "kokoro-v1.0.onnx").exists() and (KOKORO_DIR / "voices-v1.0.bin").exists()


def _ffmpeg():
    for mac in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if not shutil.which("ffmpeg") and Path(mac).exists():
            return mac
    return shutil.which("ffmpeg") or next(
        (str(p) for p in Path.home().glob(r"AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg*\**\bin\ffmpeg.exe")), None)


def clean_for_speech(text: str) -> str:
    t = re.sub(r"https?://\S+", "a link", text or "")
    t = re.sub(r"`[^`]*`", "", t)                                  # inline code / commands
    t = re.sub(r"[*_#>\[\]{}|~]", "", t)                           # markdown symbols
    t = re.sub(r"\(id [0-9a-f]+\)|#[0-9a-f]{5,8}\b", "", t)         # internal ids
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", t)  # emoji
    t = re.sub(r"^\s*[-•]\s*", "", t, flags=re.M)                    # bullets
    t = re.sub(r"\s*\n\s*", ". ", t.strip())
    t = re.sub(r"([.!?:;,])\s*\.", r"\1", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    if len(t) > MAX_SPOKEN_CHARS:
        cut = t[:MAX_SPOKEN_CHARS].rsplit(". ", 1)[0]
        t = cut + ". The rest is in the text."
    return t


def engine():
    global _kokoro
    from kokoro_onnx import Kokoro
    with _kokoro_lock:
        if _kokoro is None:
            _kokoro = Kokoro(str(KOKORO_DIR / "kokoro-v1.0.onnx"), str(KOKORO_DIR / "voices-v1.0.bin"))
    return _kokoro


def kokoro_wav(spoken, voice_id, speed, wav):
    import soundfile as sf
    k = engine()
    with _kokoro_lock:
        audio, sr = k.create(spoken, voice=voice_id, speed=speed, lang="en-gb" if voice_id.startswith("b") else "en-us")
    sf.write(str(wav), audio, sr)


def voice_id(name=None):
    name = name or load_config().get("voice", "heart")
    return KOKORO_VOICES.get(name, name)


def synthesize_wav(text: str):
    """Return path to a .wav of her saying `text` (the app and push-to-talk play this), or None."""
    spoken = clean_for_speech(text)
    if not spoken or not available():
        return None
    wav = Path(tempfile.gettempdir()) / f"jenna_lite_{uuid.uuid4().hex[:8]}.wav"
    try:
        kokoro_wav(spoken, voice_id(), float(load_config().get("kokoro_speed", 1.0)), wav)
        return wav
    except Exception:
        log.exception("text-to-speech failed")
        return None


def synthesize(text: str):
    """Return path to an .ogg voice note (Telegram), or None if there's nothing to say / it failed."""
    wav = synthesize_wav(text)
    if not wav:
        return None
    ogg = Path(tempfile.gettempdir()) / f"jenna_lite_{uuid.uuid4().hex[:8]}.ogg"
    ff = _ffmpeg()
    if not ff:
        log.error("ffmpeg not found - can't make a Telegram voice note")
        wav.unlink(missing_ok=True)
        return None
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libopus", "-b:a", "32k",
                        "-ac", "1", "-ar", "48000", str(ogg)], capture_output=True, creationflags=_NO_WINDOW,
                       timeout=120)
    wav.unlink(missing_ok=True)
    if r.returncode != 0 or not ogg.exists():
        log.error("ffmpeg failed: %s", r.stderr.decode("utf-8", "replace")[-500:])
        return None
    return ogg
