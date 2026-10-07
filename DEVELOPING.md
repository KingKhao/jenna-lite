# Developing Jenna Lite

## Layout

| Path | What it is |
|---|---|
| `run_jenna.py` | Supervisor: single-instance lock (port 8793), starts and restarts the worker |
| `jenna/brain.py` | The conversation loop with the local model (Ollama, qwen3 4b/8b/14b picked by memory) |
| `jenna/tools.py` | Her tools; anything that sends, posts or spends goes through a Yes card |
| `jenna/connections.py`, `jenna/conn_*.py` | The Connect tab: email, calendars, Slack, Notion, social, ComfyUI |
| `jenna/conn_comfy.py`, `workflows/*.json` | Pictures, photo edits and video through ComfyUI (API-format workflows) |
| `jenna/pc_api.py`, `pc/app.html` | The app (port 8794). `pc/app.html` is plain HTML/JS; edit it directly |
| `jenna/onboarding.py` | First-run setup: name, voice, model download, the Brain folder |
| `install.ps1`, `install-mac.sh` | Installers (Windows / macOS) |
| `skills/*.md` | The /skills shown in the Skills tab |
| `tests/run_tests.py` | Offline tests: no model calls, no network, temp data |

Secrets (app passwords, tokens) live in the system keychain under the service name `jenna-lite`. `config.json` holds
only non-secret settings. Nothing in `data/`, `config.json` or `voices/` is committed.

## Run the tests

```
.venv\Scripts\python.exe tests\run_tests.py        # Windows
.venv/bin/python tests/run_tests.py                # macOS
```

GitHub Actions runs them on every push, on Windows, and runs the real Mac installer on an Apple Silicon Mac.

## Release

1. Push to `main` and wait for the Actions run to pass.
2. `git archive --format=zip --prefix="Jenna Lite/" -o dist/Jenna-Lite.zip HEAD`
3. `gh release create vX.Y.Z dist/Jenna-Lite.zip --latest --notes-file notes.md`

The website's download button points at `releases/latest/download/Jenna-Lite.zip`, so a new release is live
immediately. Users update by unzipping over their folder (settings and data are kept). If `requirements.lock`
changed, say in the notes that they should run the installer again.

## Rules

- Tests never reach the network or a real account. Fake servers stand in for IMAP, ComfyUI and the rest.
- Every outbound action (email, posts, Slack, calendar changes, pictures) asks the user first.
- Content the model reads from outside (email, web pages, posts) is wrapped as untrusted, and never treated as
  instructions.
- Keep the README honest: state real timings and requirements, and mark anything untested by real users as beta.
