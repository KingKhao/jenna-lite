#!/bin/bash
# Removes Jenna Lite's app, Desktop shortcut and login item on macOS, turns off phone access and forgets the Telegram
# token. Your Brain notes folder is NOT deleted (it's yours). Ollama and its models stay; drag Ollama to the Trash if
# you like. Delete this folder afterwards to remove the rest.
HERE="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.clinchvalleydigital.jennalite"
echo; echo "  Removing Jenna Lite..."; echo
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null && echo "  stopped her"
pkill -f "$HERE/run_jenna.py" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist" && echo "  removed the login item"
rm -rf "$HOME/Applications/Jenna Lite.app" "$HOME/Desktop/Jenna Lite.app" && echo "  removed the app and Desktop shortcut"
TS="/Applications/Tailscale.app/Contents/MacOS/Tailscale"
if [ -x "$TS" ] && grep -q '"pc_remote_hosts": *\[ *"' "$HERE/config.json" 2>/dev/null; then
  "$TS" serve --https=443 off >/dev/null 2>&1 && echo "  phone access (tailscale serve) turned off"
fi
if [ -x "$HERE/.venv/bin/python" ]; then
  "$HERE/.venv/bin/python" -c "import keyring; keyring.delete_password('jenna-lite', 'telegram_token')" 2>/dev/null
  echo "  Telegram token removed from the Keychain (if there was one)"
fi
echo; echo "  Done. Your Brain folder was kept. Delete $HERE to remove the program files."
read -r -p "  Press Return to close" _ || true
