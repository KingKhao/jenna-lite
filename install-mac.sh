#!/bin/bash
# Jenna Lite installer for macOS. Run it by double-clicking "Install Jenna Lite (Mac).command" (no admin password needed).
# Safe to run again any time: it only adds what's missing and never touches your Brain notes or settings.
#   1. Python 3.12 (through uv, into this folder - nothing system-wide) and her Python packages
#   2. Ollama (her AI engine), if it isn't installed
#   3. her voice (Kokoro, ~340 MB) and her brain (a Qwen3 model sized for your Mac's memory, 2.5-9 GB)
#   4. a "Jenna Lite" app in your Applications folder (+ Desktop), and a login item so reminders always arrive
# JENNA_CI=1 skips the big downloads and launching (used by the automatic Mac test on GitHub).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
mkdir -p data
exec > >(tee "data/install-log.txt") 2>&1
CI="${JENNA_CI:-}"
LABEL="com.clinchvalleydigital.jennalite"
APP="$HOME/Applications/Jenna Lite.app"
step() { printf '\n\033[36m[%s/7] %s\033[0m\n' "$1" "$2"; }
ok() { printf '\033[32m  %s\033[0m\n' "$1"; }
fail() {
  printf '\n\033[31m  Something went wrong: %s\033[0m\n  A log of this window is in %s/data/install-log.txt\n' "$1" "$HERE"
  [ -z "$CI" ] && read -r -p "  Press Return to close" _ || true
  exit 1
}
trap 'fail "the step above stopped (line $LINENO)"' ERR

printf '\n\033[35m  Jenna Lite - a private AI assistant that runs on this Mac\n  by Clinch Valley Digital  |  built with ideas from hellotrillion.ai\033[0m\n'
# a downloaded zip marks every file "from the internet"; clear that for her own folder so Python can load them
xattr -dr com.apple.quarantine "$HERE" 2>/dev/null || true

# ---------------------------------------------------------------- 1. Python + packages
step 1 "Python and her packages (a few minutes the first time)"
UV="$(command -v uv || true)"
if [ -z "$UV" ]; then
  [ -x "$HOME/.local/bin/uv" ] || curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
  UV="$HOME/.local/bin/uv"
fi
[ -x "$HERE/.venv/bin/python" ] || "$UV" venv --python 3.12 "$HERE/.venv"
PY="$HERE/.venv/bin/python"
REQS="requirements.lock"; [ -f "$REQS" ] || REQS="requirements.txt"
"$UV" pip install --python "$PY" -r "$REQS" --quiet || fail "installing her packages failed (see above)"
"$PY" -m playwright install chromium >/dev/null 2>&1 || true
ok "Packages ready."

# ---------------------------------------------------------------- 2. Ollama
step 2 "Ollama (her AI engine)"
ollama_bin() {
  command -v ollama 2>/dev/null && return
  for a in "/Applications/Ollama.app" "$HOME/Applications/Ollama.app"; do
    [ -x "$a/Contents/Resources/ollama" ] && { echo "$a/Contents/Resources/ollama"; return; }
  done
}
up() { curl -s -m 3 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; }
if [ -n "$CI" ]; then
  echo "  (skipped in the automatic test)"
else
  if [ -z "$(ollama_bin)" ]; then
    echo "  Downloading Ollama..."
    TMP="$(mktemp -d)"
    curl -L --fail -o "$TMP/Ollama.zip" "https://ollama.com/download/Ollama-darwin.zip" || fail "couldn't download Ollama - get it from ollama.com, then run this again"
    unzip -q "$TMP/Ollama.zip" -d "$TMP"
    if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; mkdir -p "$DEST"; fi
    rm -rf "$DEST/Ollama.app"; mv "$TMP/Ollama.app" "$DEST/"
    xattr -dr com.apple.quarantine "$DEST/Ollama.app" 2>/dev/null || true
  fi
  if ! up; then
    open -a Ollama 2>/dev/null || open "$(dirname "$(dirname "$(dirname "$(ollama_bin)")")")" || true
    for _ in $(seq 1 45); do up && break; sleep 2; done
  fi
  up || fail "Ollama is installed but didn't start. Open Ollama from Applications, then run this again."
  ok "Ollama is running."
fi

# ---------------------------------------------------------------- 3. ffmpeg (optional)
step 3 "FFmpeg (only for Telegram voice notes)"
if command -v ffmpeg >/dev/null || [ -x /opt/homebrew/bin/ffmpeg ] || [ -x /usr/local/bin/ffmpeg ]; then
  ok "FFmpeg found."
elif command -v brew >/dev/null && [ -z "$CI" ]; then
  brew install ffmpeg || echo "  FFmpeg skipped (only needed for Telegram voice notes)."
else
  echo "  Skipped - only needed for Telegram voice notes. (With Homebrew: brew install ffmpeg)"
fi

# ---------------------------------------------------------------- 4. voice
step 4 "Her voice (Kokoro)"
mkdir -p voices
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
for f in kokoro-v1.0.onnx voices-v1.0.bin; do
  if [ -n "$CI" ]; then echo "  (skipped in the automatic test)"; break; fi
  if [ ! -s "voices/$f" ] || [ "$(stat -f%z "voices/$f")" -lt 1000000 ]; then
    echo "  Downloading $f..."
    curl -L --fail -o "voices/$f.part" "$BASE/$f" && mv "voices/$f.part" "voices/$f"
  fi
done
ok "Voice ready."

# ---------------------------------------------------------------- 5. brain (model sized to this Mac's memory)
step 5 "Her brain (the AI model)"
RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if [ "$(uname -m)" = "arm64" ]; then
  if [ "$RAM_GB" -ge 31 ]; then MODEL="qwen3:14b"; CTX=12288; elif [ "$RAM_GB" -ge 15 ]; then MODEL="qwen3:8b"; CTX=8192; else MODEL="qwen3:4b"; CTX=8192; fi
else
  MODEL="qwen3:4b"; CTX=8192   # Intel Macs run it on the processor: the small one keeps her responsive
fi
# keeps a model already chosen (a re-install never switches it); macOS bash 3.2: no here-doc inside $( )
"$PY" - "$MODEL" "$CTX" > data/.model <<'PYEOF'
import json, sys
from pathlib import Path
p = Path("config.json")
cfg = json.loads(p.read_text(encoding="utf-8-sig")) if p.exists() else {}
if not cfg.get("model"):
    cfg["model"], cfg["num_ctx"] = sys.argv[1], int(sys.argv[2])
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
print(cfg["model"])
PYEOF
MODEL="$(cat data/.model)"
echo "  Memory: ${RAM_GB} GB -> $MODEL"
if [ -z "$CI" ]; then
  echo "  Downloading $MODEL (one time; this is the big one)..."
  "$(ollama_bin)" pull "$MODEL" || fail "downloading $MODEL failed - check the internet connection and run this again"
  "$(ollama_bin)" pull nomic-embed-text   # small: lets her recall memories by meaning
fi
ok "Brain ready."

# ---------------------------------------------------------------- 6. the app + login item
step 6 "The Jenna Lite app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Jenna Lite</string>
  <key>CFBundleDisplayName</key><string>Jenna Lite</string>
  <key>CFBundleIdentifier</key><string>$LABEL.launcher</string>
  <key>CFBundleExecutable</key><string>JennaLite</string>
  <key>CFBundleIconFile</key><string>jenna-lite</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.2</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
</dict></plist>
EOF
printf '#!/bin/bash\nexec "%s" "%s"\n' "$PY" "$HERE/open_app.py" > "$APP/Contents/MacOS/JennaLite"
chmod +x "$APP/Contents/MacOS/JennaLite"
cp "$HERE/pc/brand/jenna-lite.icns" "$APP/Contents/Resources/jenna-lite.icns"
touch "$APP"   # Finder picks up the icon
ln -sfn "$APP" "$HOME/Desktop/Jenna Lite.app" 2>/dev/null || true
mkdir -p "$HOME/Library/LaunchAgents"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$HERE/run_jenna.py</string></array>
  <key>WorkingDirectory</key><string>$HERE</string>
  <key>RunAtLoad</key><true/>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>StandardOutPath</key><string>$HERE/data/launchd.log</string>
  <key>StandardErrorPath</key><string>$HERE/data/launchd.log</string>
</dict></plist>
EOF
plutil -lint "$PLIST" >/dev/null && plutil -lint "$APP/Contents/Info.plist" >/dev/null
ok "Added Jenna Lite to Applications and your Desktop; she starts in the background when you log in."

# ---------------------------------------------------------------- 7. start
step 7 "Starting her"
if [ -n "$CI" ]; then
  "$PY" tests/run_tests.py
  ok "Automatic test finished."
  exit 0
fi
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
open "$APP"
printf '\n\033[32m  All set. Her setup screen is opening - answer a few questions and she'"'"'s yours.\033[0m\n'
read -r -p "  Press Return to close" _ || true
