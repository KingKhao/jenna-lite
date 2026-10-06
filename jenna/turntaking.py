"""Knowing when to stop (2026-10-02, from the 'Make Your Voice AI Feel Human' prompt, Tier 5).

When the user wraps up ("okay, thanks", "sounds good", "great, I'll do that"), a person lets the conversation
end. Jenna used to answer every one ("You're welcome, Kevi!"), and once even re-answered the previous question.
This check runs before any model call, so a goodbye costs nothing.

It is CONSERVATIVE on purpose: going quiet when he wanted an answer looks broken, while answering a borderline
goodbye is just the old behavior. Any doubt -> she replies. Every list below is a one-line change; misses go in
the tests (tests/run_tests.py: sign_off_*).
"""
import re
import time
import logging

log = logging.getLogger("jenna")

# A real sign-off phrase must be present (checked longest first).
SIGN_OFFS = [
    "thank you so much", "thanks so much", "thanks a lot", "thanks a bunch", "thank you", "thanks", "thank u",
    "thx", "ty", "appreciate it", "appreciate you", "got it", "gotcha", "sounds good", "sounds great",
    "sounds perfect", "that works", "works for me", "will do", "on it", "noted", "perfect", "awesome", "great",
    "cool", "nice", "love it", "love that", "right on", "bet", "good night", "goodnight", "night night",
    "bye", "goodbye", "bye bye", "see ya", "see you", "later", "talk later", "talk soon", "talk to you later",
    "catch you later", "have a good one", "all good", "we're good", "im good", "i'm good", "that's all",
    "thats all", "that's it", "thats it", "all set", "we're all set", "i'm set", "im set", "\U0001F44D", "\U0001F64F", "❤️", "❤",
]
# Committing to do it himself is a goodbye ("great, I'll send that"); telling HER to do it is not.
COMMITMENT = re.compile(r"\b(i'll|i will|we'll|we will|gonna|going to)\s+(do|try|send|check|look at|call|text|get|"
                        r"make|start|handle|work on|think about|read|eat|cook|grab|go|head out|hop|run)\b"
                        r"( (it|that|this|them|those|one|now|later|tonight|tomorrow|today|in a bit|soon))*", re.I)
# Words that carry no new content around a sign-off.
FILLER = set("ok okay okey k kk alright alrighty yeah yes yep yup yea sure so much a lot very really just well "
             "jenna jen girl babe hun lady again man oh ah aight then too as always".split())
# Any sign he wants something back.
QUESTION_START = re.compile(r"^\s*(what|how|why|when|where|who|which|can|could|would|will you|should|is|are|"
                            r"do|does|did|have you|has|any)\b", re.I)
REQUEST = re.compile(r"\?|\b(can you|could you|would you|will you|please|pls|how about|what about|one more|"
                     r"also|another|remind|tell me|let me know|show me|send|book|add|schedule|set|check|make|"
                     r"find|search|look up|call|text|email|write|draft|plan|move|cancel|change|update|delete|"
                     r"log|save|remember|but|actually|wait|hold on|hang on)\b", re.I)
MAX_WORDS = 9            # real goodbyes are short
# Her last question was an offer ("want me to book it?"): "okay" could be a yes, so never treat it as goodbye.
OFFER = re.compile(r"\b(want me to|should i|shall i|do you want|would you like|want to|should we|ready to|"
                   r"can i|may i|is that (ok|okay|good|alright)|sound good|work for you|deal)\b", re.I)


def _last_question(text):
    """The last sentence of her message, if it's a question ('' otherwise)."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return parts[-1] if parts and parts[-1].rstrip().endswith("?") else ""
BARE_POSITIVE = {"great", "cool", "nice", "perfect", "awesome", "bet", "noted", "love it", "love that"}
BARE_MAX_WORDS = 4       # a lone "great" ends things only in a very short message
RECENT_S = 20 * 60       # only end a conversation she's actually been part of, lately


def _norm(text):
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"[.!,;:]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_sign_off(text, last_assistant=None, last_assistant_age_s=None):
    """True only for a clear sign-off right after Jenna said something. Never raises."""
    try:
        raw = (text or "").strip()
        if not raw or not last_assistant:
            return False   # never swallow the first thing he says
        if last_assistant_age_s is not None and last_assistant_age_s > RECENT_S:
            return False
        if OFFER.search(_last_question(last_assistant)):
            return False   # she offered to do something: his "okay" may mean yes
        t = _norm(raw)
        words = t.split()
        if not words or len(words) > MAX_WORDS:
            return False
        if "?" in raw or QUESTION_START.search(t):
            return False
        found = [p for p in sorted(SIGN_OFFS, key=len, reverse=True) if re.search(rf"(^|\s){re.escape(p)}(\s|$)", t)]
        if not found:
            return False
        rest = COMMITMENT.sub(" ", t)             # "I'll do that" is part of the goodbye
        for p in found:
            rest = re.sub(rf"(^|\s){re.escape(p)}(?=\s|$)", " ", rest)
        if REQUEST.search(rest):
            return False                          # "great, send that email" / "thanks, also..."
        leftover = [w for w in rest.split() if w not in FILLER]
        if leftover:
            return False                          # "okay, so the revenue is up" - he's still talking
        if all(p in BARE_POSITIVE for p in found) and len(words) > BARE_MAX_WORDS and not COMMITMENT.search(t):
            return False
        return True
    except Exception as _ignored:
        log.debug("ignored in turntaking.is_sign_off: %r", _ignored)
        return False


def last_assistant(history):
    """(text, age in seconds) of her latest real message in the stored history, or (None, None)."""
    for m in reversed(history or []):
        if m.get("role") == "user" and not m.get("signoff"):
            return None, None                     # he spoke last (and it wasn't a goodbye): not an ending
        if m.get("role") == "assistant" and (m.get("content") or "").strip() and not m.get("tool_calls"):
            age = None
            try:
                age = time.time() - time.mktime(time.strptime(m.get("time", ""), "%Y-%m-%d %H:%M"))
            except Exception as _ignored:
                log.debug("ignored in turntaking.last_assistant: %r", _ignored)
            return m["content"], age
    return None, None


# ---- End of turn (Tier 2): is he done talking? ----
# Her speech-to-text (Whisper) has no live "end of sentence" signal, so the transcript of what he's said so far
# decides: a finished sentence -> take the turn after a short quiet; trailing off -> wait longer.
TRAILING = re.compile(r"\b(and|but|so|or|because|cause|cuz|like|um+|uh+|er|the|a|an|to|of|with|for|if|then|"
                      r"which|that|my|your|our|i|we|is|was|are|just|maybe|also|plus|when|while|until|about)\W*$",
                      re.I)


def sounds_finished(transcript):
    """True when the words so far read like a complete thought (so a short pause means he's done)."""
    t = (transcript or "").strip()
    if not t or t.endswith(("...", "\u2026", ",", "-", "\u2014", ";", ":")):
        return False
    if TRAILING.search(t):
        return False
    return t[-1] in ".?!" or len(t.split()) >= 4