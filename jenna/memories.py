"""Her long-term memory: one markdown file per memory in Brain/About-Me/<assistant>/memories/.

Each file: frontmatter (type, hook, created, updated, source) + a body saying the fact, why it matters and how to
apply it. The FILES are the source of truth - the user can open, edit or delete any of them. MEMORY.md lists every
hook for browsing. data/memory_index.json holds embeddings and is derived: delete it and it rebuilds.

Recall is by meaning (local nomic-embed-text via Ollama) and falls back to keywords when embeddings are missing or
Ollama is down - recall degrades, never breaks.

Never stored: secrets, other people's contact details or health details. Every save goes through save(), which
filters, de-duplicates and refuses rather than piling up near-copies.
"""
import json
import logging
import math
import re
import shutil
import threading
from datetime import datetime

from .settings import DATA, load_config

log = logging.getLogger("jenna")

TYPES = {
    "about-me": "lasting facts about the user (background, goals, tastes, values, routines)",
    "how-i-like-it": "how the user wants you to work: preferences, corrections they made, formats, things to skip",
    "project": "decisions and status on the user's projects, and why",
    "people": "who someone is to the user (names and roles only - no contact or health details)",
    "reference": "where things live: links, folders, accounts, tools",
}
EMBED_MODEL = "nomic-embed-text"
# Calibrated on nomic-embed-text: the same fact reworded scored 0.73-0.94; a question vs. the memory that answers
# it 0.57-0.67, vs. unrelated memories up to 0.57.
DUP_SIM = 0.86
RELATED_SIM = 0.62
KEYWORD_BONUS = 0.08
_lock = threading.RLock()


def mem_dir():
    from . import memory
    return memory.my_dir() / "memories"


def index_path():
    return DATA / "memory_index.json"


# ---------------- guards: what never gets remembered ----------------
_HEALTH = re.compile(r"\b(injur\w*|surgery|diagnos\w*|medical|medication|meds|prescri\w*|diabet\w*|blood pressure|"
                     r"pregnan\w*|therap\w*|disorder|illness)\b", re.I)
_PHONE = re.compile(r"(\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b")
_ADDRESS = re.compile(r"\b\d{2,6} [A-Z][a-z]+ (St|Street|Rd|Road|Ave|Avenue|Ln|Lane|Dr|Drive|Hwy|Highway|Blvd|Ct|Way)\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")


def refuse_reason(mtype, hook, body):
    """'' if this may be stored, else why not."""
    from . import security
    text = f"{hook}\n{body}"
    if security.looks_secret(text) or re.search(r"\b(password|passcode|api key|token|pin)\s*[:=]", text, re.I):
        return "it looks like a password, key or token - those are never stored"
    if mtype == "people" and _HEALTH.search(text):
        return "it has someone else's health details - those aren't kept"
    if mtype == "people" and (_PHONE.search(text) or _ADDRESS.search(text) or _EMAIL.search(text)):
        return "it has someone's phone, address or email - remember who they are, not their contact details"
    return ""


# ---------------- files (source of truth) ----------------
def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "memory"


def _parse(p):
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    m = re.match(r"---\s*\n(.*?)\n---\s*\n?(.*)", text, re.S)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep:
            fm[k.strip()] = v.strip().strip('"')
    if fm.get("type") not in TYPES or not fm.get("hook"):
        return None
    return {"id": p.stem, "path": str(p), "type": fm["type"], "hook": fm["hook"], "body": m.group(2).strip(),
            "created": fm.get("created", ""), "updated": fm.get("updated", ""), "source": fm.get("source", "")}


def all_memories():
    d = mem_dir()
    if not d.exists():
        return []
    return [m for m in (_parse(p) for p in sorted(d.glob("*.md")) if p.name != "MEMORY.md") if m]


def _write(m):
    d = mem_dir()
    d.mkdir(parents=True, exist_ok=True)
    fm = [f"type: {m['type']}", f'hook: "{m["hook"].replace(chr(34), chr(39))}"', f"created: {m['created']}",
          f"updated: {m['updated']}", f"source: {m['source']}"]
    p = d / f"{m['id']}.md"
    p.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + m["body"].strip() + "\n", encoding="utf-8")
    return p


def write_index():
    """MEMORY.md: one line per memory, by type - for browsing."""
    mems = all_memories()
    name = load_config().get("assistant_name") or "Jenna"
    lines = [f"# {name}'s memories", "", "One file per memory in this folder - edit or delete any of them. This list "
             "is regenerated automatically.", ""]
    for t, what in TYPES.items():
        group = [m for m in mems if m["type"] == t]
        if group:
            lines += [f"## {t} ({what})", ""] + [f"- [{m['hook']}]({m['id']}.md)" for m in group] + [""]
    mem_dir().mkdir(parents=True, exist_ok=True)
    (mem_dir() / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------- embeddings index (derived, rebuildable) ----------------
_status = {"embeddings": None}


def _client(timeout):
    import ollama
    return ollama.Client(host=load_config().get("ollama_url"), timeout=timeout)


def _embed(texts):
    """Vectors, or None if the embedding model isn't available (then recall uses keywords)."""
    try:
        r = _client(60).embed(model=EMBED_MODEL, input=[f"search_document: {t}" for t in texts])
        vecs = getattr(r, "embeddings", None) or r["embeddings"]
        _status["embeddings"] = True
        return [list(map(float, v)) for v in vecs]
    except Exception as e:
        if _status["embeddings"] is not False:
            log.warning("memories: embeddings unavailable (%s) - keyword recall", str(e)[:120])
        _status["embeddings"] = False
        return None


def _embed_query(q):
    if _status["embeddings"] is False:
        return None
    try:
        r = _client(30).embed(model=EMBED_MODEL, input=[f"search_query: {q}"])
        vecs = getattr(r, "embeddings", None) or r["embeddings"]
        return list(map(float, vecs[0]))
    except Exception as e:
        log.debug("memories: query embedding failed: %r", e)
        return None


def _text_for(m):
    return f"{m['hook']}\n{m['body'][:600]}"


def _load_index():
    try:
        return json.loads(index_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def refresh_index(rebuild=False):
    """Bring the derived index in line with the files: embed new/changed memories, drop deleted ones."""
    with _lock:
        idx = {} if rebuild else _load_index()
        mems = {m["id"]: m for m in all_memories()}
        stale = [i for i, m in mems.items() if idx.get(i, {}).get("text") != _text_for(m)]
        for gone in set(idx) - set(mems):
            idx.pop(gone)
        if stale:
            vecs = _embed([_text_for(mems[i]) for i in stale])
            if vecs:
                for i, v in zip(stale, vecs, strict=True):
                    idx[i] = {"text": _text_for(mems[i]), "vec": v}
        index_path().write_text(json.dumps(idx), encoding="utf-8")
        return idx


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b, strict=False))
    den = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return num / den if den else 0.0


_STOP = set("the a an and or of to in on for with is are was were be it this that my me i you your what how "
            "about do does did have has had at by from as we he his him she her they them".split())


def _keywords(s):
    return {w for w in re.findall(r"[a-z0-9$]+", (s or "").lower()) if len(w) > 2 and w not in _STOP}


def search(query, k=5, types=None, use_embeddings=True):
    """[(memory, score, how)] best first. By meaning when possible, by keywords otherwise."""
    mems = [m for m in all_memories() if not types or m["type"] in types]
    if not mems or not (query or "").strip():
        return []
    scored, how = [], "keywords"
    qv = _embed_query(query) if use_embeddings else None
    if qv:
        idx = refresh_index()
        if all(m["id"] in idx for m in mems):
            how = "meaning"
            qk = _keywords(query)
            scored = [(m, _cos(qv, idx[m["id"]]["vec"]) + KEYWORD_BONUS * min(2, len(qk & _keywords(_text_for(m)))))
                      for m in mems]
    if how == "keywords":
        qk = _keywords(query)
        for m in mems:
            mk = _keywords(_text_for(m))
            hit = len(qk & mk) + 0.5 * sum(1 for w in qk for x in mk if len(w) > 4 and (w in x or x in w) and w != x)
            if hit:
                scored.append((m, hit / max(1, len(qk))))
    scored.sort(key=lambda x: -x[1])
    return [(m, round(s, 3), how) for m, s in scored[:k]]


def _related(query, k, types=None):
    try:
        return [(m, s, h) for m, s, h in search(query, k=k, types=types)
                if (s >= RELATED_SIM if h == "meaning" else s >= 0.5)]
    except Exception:
        log.exception("memory recall failed")
        return []


def relevant(query, k=3):
    """For the per-message block: the few memories that matter to what the user just said ('' if none)."""
    facts = [m for m, _, _ in _related(query, k) if m["type"] != "how-i-like-it"]   # their rules go last
    if not facts:
        return ""
    return ("Memories that may matter here (written on the date shown - a status or number in them is a lead to "
            "verify, not a guarantee):\n" + "\n".join(
                f"- [{m['type']}, {m['updated'] or m['created']}] {m['hook']}: {m['body'][:300]}" for m in facts))


def standing_rules(query):
    """Their how-i-like-it memories that apply to this message, worded as orders for the very end of it. As
    background facts a small model ignores them; at the end of the message it follows them."""
    hits = [m for m, _, _ in _related(query, 4, types=("how-i-like-it",))]
    if not hits:
        return ""
    return "BEFORE YOU SEND - their standing rules for this, follow them exactly: " + " / ".join(m["hook"] for m in hits)


# ---------------- writing ----------------
def find_duplicate(hook, body=""):
    """An existing memory that already covers this, or None (by meaning, else by near-identical wording)."""
    import difflib
    probe = f"{hook}\n{body[:600]}"
    if _embed_query(probe):
        idx = refresh_index()
        pv = (_embed([probe]) or [None])[0]
        best = max(((m, _cos(pv, idx[m["id"]]["vec"])) for m in all_memories() if m["id"] in idx and pv),
                   key=lambda x: x[1], default=(None, 0))
        if best[0] and best[1] >= DUP_SIM:
            return best[0]
    for m in all_memories():
        if difflib.SequenceMatcher(None, m["hook"].lower(), hook.lower()).ratio() >= 0.85:
            return m
    return None


def save(mtype, hook, body="", source="chat"):
    """(memory, message). Refuses secrets/health/contact details; a near-duplicate updates nothing and says so."""
    mtype = (mtype or "").strip().lower()
    hook = " ".join((hook or "").split())[:160]
    body = (body or "").strip()[:2000]
    if mtype not in TYPES:
        return None, f"not saved: type must be one of {', '.join(TYPES)}"
    if len(hook) < 8:
        return None, "not saved: the hook (one-line summary) is missing or too short"
    why = refuse_reason(mtype, hook, body)
    if why:
        log.info("memory refused (%s)", why.split(" - ")[0])
        return None, f"not saved: {why}"
    with _lock:
        dup = find_duplicate(hook, body)
        if dup:
            return dup, f"already remembered as '{dup['hook']}' ({dup['id']}) - not saved twice"
        now = f"{datetime.now():%Y-%m-%d}"
        base = f"{mtype}--{_slug(hook)}"
        mid, n = base, 2
        while (mem_dir() / f"{mid}.md").exists():
            mid, n = f"{base}-{n}", n + 1
        m = {"id": mid, "type": mtype, "hook": hook, "body": body or hook, "created": now, "updated": now,
             "source": source}
        _write(m)
        write_index()
        refresh_index()
    log.info("memory saved: %s (%s)", mid, source)
    return m, f"saved as {mid}"


def forget(mem_id):
    """Moves the file to memories/_forgotten (she no longer recalls it; the user can still restore it by hand)."""
    with _lock:
        p = mem_dir() / f"{mem_id}.md"
        if not p.exists():
            return False
        dest = mem_dir() / "_forgotten"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.move(str(p), str(dest / p.name))
        write_index()
        refresh_index()
    return True


def stable_summary(max_chars=1800, types=("about-me", "how-i-like-it")):
    """For the stable prompt: the hooks of what she knows about the user and how they like things."""
    mems = [m for m in all_memories() if m["type"] in types]
    out, size = [], 0
    for m in sorted(mems, key=lambda m: (m["type"] != "how-i-like-it", m["created"])):
        line = f"- ({'THEIR RULE - always follow' if m['type'] == 'how-i-like-it' else 'about them'}) {m['hook']}"
        if size + len(line) > max_chars:
            out.append(f"- ...and {len(mems) - len(out)} more (recall_memory finds them)")
            break
        out.append(line)
        size += len(line)
    return "\n".join(out) or "- nothing yet (you're still getting to know them)"
