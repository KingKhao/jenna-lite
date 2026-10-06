"""Humanize: keeps her writing sounding like a person.

Two layers: WRITING_RULES go in her system prompt (so she writes like a person), and clean()
mechanically strips the tells that slip through anyway (em dashes, sycophantic openers,
help-desk sign-offs, AI vocabulary).
"""
import re

WRITING_RULES = """How you write (humanize rules - always):
- Specific beats smooth. Name the real thing, number or person, never the vague category.
- Say it plainly and commit. No hedging ("it's worth noting", "generally", "arguably").
- Vary sentence length a lot. Some short. Some longer when the thought needs room.
- Never open with "Great question", "Certainly", "Absolutely", "I'd be happy to". Just answer.
- Never close with "Let me know if you need anything else" or a recap of what you just said. Stop when you're done.
- No em dashes, no "not just X but Y", no lists of three by reflex.
- Skip words like delve, leverage, seamless, robust, crucial, navigate, elevate, unlock, journey.
- Don't fake casual either: no forced slang or random "honestly"/"look". Just talk like yourself.
- At most one emoji per message, and none when it's about work. Exclamation points are for real wins, not every line.
- Never say you're glad about something that went wrong for them (a dead phone, a cancelled client, a bad day).
  Show you get it, or move on.
- Don't end with a pep-talk line ("You've got this!", "Good luck!") unless they're about to do something big."""

_OPENERS = re.compile(r"^\s*(great question|certainly|absolutely|of course|sure thing|i'?d be (happy|glad) to( help)?|"
                      r"happy to help|i'?m here to help|based on the information( (available|provided|you shared))?)"
                      r"[!,.:]*\s*", re.IGNORECASE)
_CLOSERS = re.compile(
    r"\s*(let me know (if|what|how|when)[^.!?\n]*[.!?]*|just let me know[^.!?\n]*[.!?]*|"
    r"(feel free to|don'?t hesitate to) (reach out|ask|let me know)[^.!?\n]*[.!?]*|"
    r"i hope (this|that) helps[^.!?\n]*[.!?]*|is there anything else[^?\n]*\?)\s*(\S{0,4})\s*$",
    re.IGNORECASE)
# Generic assistant filler. Once she lost her instructions (context overflow) she answered with only this,
# and the closer strip above left "If you have any questions or need assistance with anything," hanging.
_FILLER = re.compile(r"\s*(i'?m (always )?(here|ready)( and ready)? (to help|for you)( you)?( with anything( you need)?)?"
                     r"[^.!?\n]*[.!?]*|i'?m here for you[^.!?\n]*[.!?]*)\s*$", re.IGNORECASE)
# a final sentence that starts with "If" and never ends ("If you ever need any changes or updates,") is
# always a sign-off the closer strip cut in half - only removed when the text before it is a full sentence
# her internal "[System check] you didn't call a tool" nudge sometimes leaks into the reply
_CHECK_LEAK = re.compile(r"[^.!?\n]*\b(no tool was called|(didn'?t|did not) call (a|any) tools?|"
                         r"no action was taken|this (system )?check)\b[^.!?\n]*[.!?]*\s*", re.IGNORECASE)
_DANGLING = re.compile(r"(?<=[.!?])\s+if\b[^.!?\n]*[,;:]?\s*$", re.IGNORECASE)


def is_filler(text):
    """A reply with nothing in it besides generic 'I'm here to help' filler."""
    t = (text or "").strip()
    if not t:
        return True
    left = t
    for _ in range(4):   # filler, then the dangling "if you have any..." it hid behind, then filler again
        new = _DANGLING.sub("", _FILLER.sub("", _CLOSERS.sub("", left))).strip(" ,.!-\n")
        if new == left:
            break
        left = new
    left = re.sub(r"^(no,? )?(i'?m sorry[^.!?]*[.!?]|sorry[^.!?]*[.!?]|yes,? |no,? )", "", left, flags=re.I).strip(" ,.!")
    return len(_without_name(left).strip(" ,.!")) < 12


def _without_name(text):
    """The text with the user's name taken out ("Thanks, Sam!" is still filler)."""
    try:
        from .settings import load_config
        name = (load_config().get("owner_name") or "").strip()
    except Exception:
        name = ""
    return re.sub(rf"\b{re.escape(name)}\b", "", text, flags=re.I) if name else text


_SWAPS = {r"\bdelve into\b": "dig into", r"\bdelve\b": "dig", r"\bleverage\b": "use", r"\butilize\b": "use",
          r"\bseamless(ly)?\b": "smooth", r"\brobust\b": "solid", r"\bcrucial\b": "key",
          r"\bin today's fast-paced world,?\s*": "", r"\bit'?s worth noting that\s*": ""}


def clean(text: str) -> str:
    if not text:
        return text
    t = _strip_foreign(text.strip())
    t = _CHECK_LEAK.sub("", t).strip() or t
    t = _OPENERS.sub("", t, count=1)
    if t[:1].islower():
        t = t[0].upper() + t[1:]
    for _ in range(3):                       # strip stacked sign-offs (and the half-sentence they leave)
        new = _DANGLING.sub("", _FILLER.sub("", _CLOSERS.sub("", t))).rstrip()
        if not new or new == t:
            break
        t = new
    t = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), t)   # Telegram shows ** literally
    t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)
    t = re.sub(r"\s*—\s*", ", ", t)           # em dash -> comma
    t = re.sub(r"(?<=\w) – (?=\w)", ", ", t)  # spaced en dash used as a dash
    for pat, rep in _SWAPS.items():
        t = re.sub(pat, rep, t, flags=re.IGNORECASE)
    t = re.sub(r",\s*([.!?])", r"\1", t)
    t = _cap_emoji(t)
    t = re.sub(r"‍(?![\U0001F300-\U0001FAFF☀-➿])", "", t)   # joiner left dangling by a removed emoji
    t = _cap_exclaim(t)
    return t.strip() or text.strip()


# qwen3 sometimes ends an English reply with a stray word in another script ("Enjoy! 🌲 отдыхает").
_FOREIGN_WORD = re.compile(r"[^\s]*[Ѐ-ӿ؀-ۿ぀-ヿ㐀-鿿가-힯][^\s]*")


def _strip_foreign(t):
    latin = len(re.findall(r"[A-Za-z]", t))
    foreign = sum(len(w) for w in _FOREIGN_WORD.findall(t))
    if not foreign or latin < 4 * foreign:   # leave genuinely non-English replies alone
        return t
    return re.sub(r"[ \t]{2,}", " ", _FOREIGN_WORD.sub("", t)).strip()


# Emoji and "!" piled up in nearly every reply even with the rules above - cap them mechanically.
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]️?")
MAX_EMOJI, MAX_EXCLAIM = 1, 2


def _cap_emoji(t):
    seen = 0

    def keep(m):
        nonlocal seen
        seen += 1
        return m.group(0) if seen <= MAX_EMOJI else ""
    t = _EMOJI.sub(keep, t)
    return re.sub(r"[ \t]+(\n|$)", r"\1", re.sub(r" {2,}", " ", t))


def _cap_exclaim(t):
    seen = 0

    def keep(m):
        nonlocal seen
        seen += 1
        return "!" if seen <= MAX_EXCLAIM else "."
    return re.sub(r"!+", keep, t)   # "!!" counts as one and comes out as a single "!"
