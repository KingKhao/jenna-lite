"""Open the Jenna Lite app (the Desktop / Start menu icon on Windows, the Jenna Lite app on a Mac).
Opens her in its own app window (Edge/Chrome app mode) on this PC. If she isn't running yet, the window opens at
once on a "Waking her up" splash that starts her and switches to the app when she answers."""
import subprocess
import time
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOKEN_FILE = ROOT / "data" / "pc_token.txt"
URL = "http://127.0.0.1:8794/"
MAC = sys.platform == "darwin"
BROWSERS = ([str(Path(base) / app) for base in ("/Applications", str(Path.home() / "Applications"))
             for app in ("Google Chrome.app/Contents/MacOS/Google Chrome", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                         "Brave Browser.app/Contents/MacOS/Brave Browser")] if MAC else
            [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
             r"C:\Program Files\Google\Chrome\Application\chrome.exe"])


def app_key():
    """The app key, made here if she hasn't started yet. The installer opens this window a moment after starting
    her; reading a key that didn't exist yet opened the app with none ("open the app from its Desktop icon")."""
    import secrets
    TOKEN_FILE.parent.mkdir(exist_ok=True)
    try:
        with TOKEN_FILE.open("x", encoding="utf-8") as f:   # exclusive create: only one side ever writes it
            f.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    for _ in range(20):
        key = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
        time.sleep(0.1)   # the other side is mid-write
    return key


def running():
    try:
        urllib.request.urlopen(URL, timeout=2)  # nosec B310 - fixed http://127.0.0.1 address of her own app
    except urllib.error.HTTPError:
        return True        # 403 without the key = she's up
    except Exception:
        return False
    return True


SPLASH = """<!doctype html><html><head><meta charset="utf-8"><title>Jenna Lite</title><style>
html,body{margin:0;height:100%;background:#02040b;color:#e6e9ef;font:15px system-ui,sans-serif;display:grid;place-items:center}
.o{display:block;width:120px;height:120px;margin:0 auto 22px;filter:drop-shadow(0 0 24px #29b88566);animation:p 2.2s ease-in-out infinite}
@keyframes p{50%{transform:scale(1.06);filter:drop-shadow(0 0 40px #29b885aa)}}
@media (prefers-reduced-motion:reduce){.o{animation:none}} p{text-align:center;margin:6px}.m{color:#8b93a1;font-size:13px}</style></head>
<body><div><svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" class="o" viewBox="0 0 1024 1024" role="img"><title>Jenna Lite 03-submark-brandmark/orb-color-on-dark</title><g transform="translate(0 0) scale(1.024)"><path fill="#5EE6BE" d="M 298 795 C 152 666 395 415 732 359 C 516 444 235 677 298 795 Z"/><circle cx="456" cy="519" r="318" fill="none" stroke="#29B885" stroke-width="44"/><circle cx="811" cy="214" r="63" fill="#F2C14E"/></g></svg><p id="t">Waking her up...</p><p class="m" id="m">Starting on this PC - a few seconds.</p></div><script>
const APP = "__APP__", T0 = Date.now();
async function poll() {
  try { await fetch("__URL__", { mode: "no-cors", cache: "no-store" }); location.replace(APP); return; } catch (e) {}
  if (Date.now() - T0 > 90000) { document.getElementById("t").textContent = "She didn't start.";
    document.getElementById("m").textContent = "Check data/jenna.log in her folder, or run the installer again. This window keeps trying."; }
  setTimeout(poll, 1000);
}
poll();
</script></body></html>"""


def main():
    token = app_key()
    browser = next((b for b in BROWSERS if Path(b).exists()), None)
    app_url = f"{URL}?t={token}"
    start_url = app_url
    if not running():   # she's not up (e.g. right after login): open at once on a splash, start her, swap when she answers
        if MAC:   # the login item normally runs her; this covers right after install or if it was stopped
            subprocess.Popen([sys.executable, str(ROOT / "run_jenna.py")], cwd=str(ROOT), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            pyw = Path(sys.executable).with_name("pythonw.exe")
            subprocess.Popen([str(pyw), str(ROOT / "run_jenna.py")], cwd=str(ROOT))   # single-instance lock: safe twice
        splash = ROOT / "data" / "app-splash.html"   # data/ is private (it carries the app key)
        splash.write_text(SPLASH.replace("__APP__", app_url).replace("__URL__", URL), encoding="utf-8")
        start_url = splash.as_uri()
    profile = ROOT / "data" / "app-window"   # own profile: remembers mic permission + window size
    if browser:
        subprocess.Popen([browser, f"--app={start_url}", f"--user-data-dir={profile}", "--window-size=520,820",
                          "--no-first-run", "--no-default-browser-check"])
    else:
        import webbrowser   # Safari or the default browser (no app-window mode there)
        webbrowser.open(start_url)


if __name__ == "__main__":
    main()
