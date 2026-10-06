"""Her Brain: a plain folder of markdown notes on this PC (opens in Obsidian, or any text editor).

Layout (made by setup from brain_template/):
  Index/     short maps of what exists and where - search looks here first
  About-Me/  who the user is; her memories live in About-Me/<assistant>/memories
  People/  Projects/  Reference/  Wiki/   the user's own collections
  Inbox/     quick captures (save_to_brain, notes)
  Raw/       unreviewed material: her daily conversation logs
Rules: never any secrets (everything is redacted on the way in), and she writes only her own files - changing
any other note goes through propose_brain_edit, which asks the user first.
"""
import difflib
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path

from .settings import ROOT, load_config

TEMPLATE = ROOT / "brain_template"
SEARCH_DIRS = ["Index", "Wiki", "About-Me", "People", "Projects", "Reference", "Inbox", "Raw"]
_lock = threading.Lock()


def default_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "Jenna Brain"


def vault() -> Path:
    return Path(load_config().get("brain_dir") or default_dir())


def convo_dir():
    return vault() / "Raw" / "conversations"


def inbox():
    return vault() / "Inbox"


def create(path=None) -> Path:
    """Build a new Brain from the template (never overwrites a note that's already there)."""
    dest = Path(path) if path else vault()
    for src in TEMPLATE.rglob("*"):
        rel = src.relative_to(TEMPLATE)
        out = dest / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        elif not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8")
            cfg = load_config()
            text = (text.replace("{{owner}}", cfg.get("owner_name") or "you")
                        .replace("{{assistant}}", cfg.get("assistant_name") or "Jenna")
                        .replace("{{date}}", f"{datetime.now():%Y-%m-%d}"))
            out.write_text(text, encoding="utf-8")
    for d in SEARCH_DIRS:
        (dest / d).mkdir(parents=True, exist_ok=True)
    return dest


# Anything that looks like a credential gets masked before it touches the Brain.
_SECRET_PATTERNS = [
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"),                                  # Telegram bot token
    re.compile(r"\b(sk|pk|rk|ghp|gho|github_pat|xox[abp]|AIza|ya29)[-_A-Za-z0-9.]{16,}"),  # common API keys
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),  # JWTs
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(password|passwd|pwd|pin(?: code)?|passcode|api[_ -]?key|secret|token)\b(\s*(?:is|:|=)\s*)"
               r"(?=\S*[\d_\-!@#$%^&*])\S{3,}"),
    re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}\b"),                                  # long opaque strings
    re.compile(r"\b(?:\d{4}[ -]){3}\d{4}\b"),                                         # card numbers
    re.compile(r"\b\d{9,17}\b"),                                                      # account/routing numbers
]


def redact(text: str) -> str:
    t = text or ""
    for p in _SECRET_PATTERNS:
        if p.groups >= 2:
            t = p.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", t)
        else:
            t = p.sub("[redacted]", t)
    return t


def log_exchange(user_text: str, reply: str, from_voice=False):
    """Append one back-and-forth to today's conversation log in Raw/."""
    cfg = load_config()
    who, me = cfg.get("owner_name") or "Me", cfg.get("assistant_name") or "Jenna"
    now = datetime.now()
    path = convo_dir() / f"{now:%Y-%m-%d}.md"
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(f"---\nsource: {me}\ndate: {now:%Y-%m-%d}\nstatus: raw\n---\n\n"
                            f"# Conversations with {me} - {now:%A, %B %d, %Y}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(f"**{now:%H:%M} {who}{' (voice)' if from_voice else ''}:** {redact(user_text).strip()}\n\n"
                    f"**{me}:** {redact(reply).strip()}\n\n")


def log_summary(summary: str):
    now = datetime.now()
    path = convo_dir() / f"{now:%Y-%m-%d}.md"
    with _lock:
        if path.exists():
            with path.open("a", encoding="utf-8") as f:
                f.write(f"---\n\n## Summary of the day\n\n{redact(summary).strip()}\n")


def save_note(title: str, note: str, kind: str = "note") -> str:
    """Quick capture into Inbox/ as its own file (ideas, decisions, tasks, things to remember)."""
    now = datetime.now()
    slug = re.sub(r"[^a-z0-9]+", "-", (title or kind).lower()).strip("-")[:50] or kind
    path = inbox() / f"{now:%Y-%m-%d} {slug}.md"
    n = 2
    while path.exists():
        path = inbox() / f"{now:%Y-%m-%d} {slug}-{n}.md"
        n += 1
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nsource: {load_config().get('assistant_name') or 'Jenna'}\ntype: {kind}\n"
                        f"created: {now:%Y-%m-%d %H:%M}\n---\n\n# {redact(title).strip()}\n\n{redact(note).strip()}\n",
                        encoding="utf-8")
    return f"Saved to the Brain: Inbox/{path.name}"


def guide() -> str:
    cfg = load_config()
    who = cfg.get("owner_name") or "the user"
    return f"""How {who}'s Brain works (a folder of notes on this PC: {vault()}):
- Index/ = short maps of what exists and where. search_brain checks Index first.
- About-Me/, People/, Projects/, Reference/, Wiki/ = {who}'s own notes. Raw/ = your conversation logs (unreviewed).
- Inbox/ = quick captures (where save_to_brain and notes go).
Rules: never store secrets. You write only your own files (Raw/, Inbox/, your memories); to change any other note use
propose_brain_edit, which asks {who} first. Say where you found something ("per Projects/garden.md ...")."""


def index_maps() -> str:
    """One line per Index map: file name + its title."""
    out = []
    for p in sorted((vault() / "Index").glob("*.md")):
        try:
            first = next((l.lstrip("# ").strip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                          if l.strip() and not l.startswith("---")), p.stem)
        except OSError:
            continue
        out.append(f"- Index/{p.name}: {first}")
    return "\n".join(out) or "- (no Index maps yet)"


def _best_lines(text, words, n):
    """The n lines that match the most distinct query words (ties: earlier first), in note order."""
    scored = []
    for i, l in enumerate(text.splitlines()):
        low = l.lower()
        k = sum(1 for w in set(words) if w in low)
        if k and l.strip():
            scored.append((-k, i, l.strip()))
    top = sorted(scored)[:n]
    return [l for _, _, l in sorted(top, key=lambda t: t[1])]


def _rel(p: Path) -> str:
    return str(p.relative_to(vault())).replace("\\", "/")


def search(query: str, max_hits=8) -> str:
    """Index first, then the rest of the Brain. Returns file paths + matching lines."""
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if len(w) > 2]
    if not words:
        return "Give me a word or two to search for."
    root = vault()
    idx_hits = []
    for p in (root / "Index").glob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = _best_lines(text, words, 4)
        strong = [l for l in lines if sum(w in l.lower() for w in set(words)) >= min(2, len(set(words)))]
        if strong or any(w in p.stem.lower() for w in words):
            idx_hits.append(f"{_rel(p)}\n  " + "\n  ".join(l[:220] for l in (strong or lines or text.splitlines()[:3])))
    hits = []
    for d in SEARCH_DIRS:
        base = root / d
        if d == "Index" or not base.exists():
            continue
        for p in base.rglob("*.md"):
            if any(part.startswith(".") or part == "_forgotten" for part in p.parts):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            low = text.lower()
            score = sum(low.count(w) for w in words) + 5 * sum(w in p.name.lower() for w in words)
            if score == 0 or not all(w in low or w in p.name.lower() for w in words[:3]):
                continue
            hits.append((score, p, _best_lines(text, words, 4)))
    if not hits and not idx_hits:
        return f"Nothing in the Brain matches '{query}'. Try fewer or different words.\nIndex maps:\n" + index_maps()
    hits.sort(key=lambda h: -h[0])
    out = []
    if idx_hits:
        out.append("INDEX MAPS (start here - they say where things live):")
        out += idx_hits[:4]
    if hits:
        out.append("NOTES:")
        for _, p, lines in hits[:max_hits]:
            tag = " [Raw - unreviewed]" if _rel(p).startswith("Raw/") else ""
            out.append(f"{_rel(p)}{tag}\n  " + "\n  ".join(l[:200] for l in lines))
    return "\n".join(out)


def _inside(p: Path) -> bool:
    try:
        p.resolve().relative_to(vault().resolve())
        return True
    except ValueError:
        return False


def edit_check(rel_path: str, mode: str, text: str, old_text: str = ""):
    """Validate a proposed edit. Returns (ok, message, resolved_path)."""
    p = (vault() / rel_path.replace("\\", "/").lstrip("/")).resolve()
    if not _inside(p) or p.suffix.lower() != ".md" or _rel(p).lower().startswith(".obsidian"):
        return False, "Only .md notes inside the Brain can be edited.", None
    if mode == "replace":
        if not p.is_file():
            return False, "That note doesn't exist, so there's nothing to replace.", None
        count = p.read_text(encoding="utf-8", errors="replace").count(old_text) if old_text else 0
        if count != 1:
            return False, (f"old_text must match exactly once in the note (found {count}). "
                           "Read the note and copy the exact text."), None
    if redact(text) != text:
        return False, "That edit contains something that looks like a secret - not allowed in the Brain.", None
    return True, "ok", p


def apply_edit(rel_path: str, mode: str, text: str, old_text: str = "") -> str:
    ok, msg, p = edit_check(rel_path, mode, text, old_text)
    if not ok:
        return msg
    now = datetime.now()
    with _lock:
        if mode == "replace":
            body = p.read_text(encoding="utf-8", errors="replace")
            shutil.copyfile(p, p.with_name(p.name + ".bak"))
            p.write_text(body.replace(old_text, text, 1), encoding="utf-8")
            return f"Updated {_rel(p)} (replaced one passage)."
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        with p.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## Update {now:%Y-%m-%d}\n\n{text.strip()}\n" if existed else f"# {p.stem}\n\n{text.strip()}\n")
        return f"{'Added to' if existed else 'Created'} {_rel(p)}."


def read_note(rel_path: str) -> str:
    p = (vault() / str(rel_path).replace("\\", "/").lstrip("/")).resolve()
    if not _inside(p) or p.suffix.lower() != ".md" or not p.is_file():
        return "That's not a note in the Brain."
    return p.read_text(encoding="utf-8", errors="replace")[:6000]


def stats() -> dict:
    """For the app's Brain page: how big her Brain is and what's newest."""
    root = vault()
    notes = [p for p in root.rglob("*.md") if not any(x.startswith(".") for x in p.parts)] if root.exists() else []
    by = {}
    for p in notes:
        top = _rel(p).split("/", 1)[0]
        by[top] = by.get(top, 0) + 1
    newest = sorted(notes, key=lambda p: p.stat().st_mtime, reverse=True)[:8]
    return {"path": str(root), "exists": root.exists(), "notes": len(notes),
            "folders": [{"name": k, "notes": v} for k, v in sorted(by.items())],
            "recent": [{"path": _rel(p), "when": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                       for p in newest]}


def similar_line_exists(path: Path, line: str) -> bool:
    if not path.exists():
        return False
    key = line.lower().strip()
    return any(difflib.SequenceMatcher(None, key, l.lower().strip()).ratio() > 0.9
               for l in path.read_text(encoding="utf-8").splitlines() if l.strip())
