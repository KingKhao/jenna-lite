"""Email over IMAP (read) and SMTP (send) with an app password - Gmail, Yahoo, iCloud, AOL, Zoho, Fastmail or any
mailbox. Reads open the inbox read-only (nothing is marked as read or moved); sending always goes through the
user's Yes card first. Everything read is marked untrusted before she sees it (anyone can email you)."""
import email
import email.utils
import imaplib
import logging
import re
import smtplib
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage

from . import connections

log = logging.getLogger("jenna")
PRESETS = {   # IMAP host, IMAP port, SMTP host, SMTP port (465 = SSL, 587 = STARTTLS)
    "gmail": ("imap.gmail.com", 993, "smtp.gmail.com", 465),
    "yahoo": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465),
    "icloud_mail": ("imap.mail.me.com", 993, "smtp.mail.me.com", 587),
    "aol": ("imap.aol.com", 993, "smtp.aol.com", 465),
    "zoho": ("imap.zoho.com", 993, "smtp.zoho.com", 465),
    "fastmail": ("imap.fastmail.com", 993, "smtp.fastmail.com", 465),
}
TIMEOUT = 30


def _servers(pid, f):
    if pid in PRESETS:
        return PRESETS[pid]
    try:
        return (f["imap_host"], int(f.get("imap_port") or 993), f["smtp_host"], int(f.get("smtp_port") or 465))
    except (KeyError, ValueError):
        raise ValueError("Check the server names and ports.") from None


def _creds(pid, f=None):
    f = f or {**(connections.saved(pid) or {}), **connections.secrets(pid)}
    user = f.get("username") or f.get("address", "")
    return f, user, f.get("password", "").replace(" ", "")   # Google shows app passwords in groups of four


def _imap(pid, f=None):
    f, user, pw = _creds(pid, f)
    host, port, _, _ = _servers(pid, f)
    m = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    try:
        m.login(user, pw)
    except imaplib.IMAP4.error as e:
        m.shutdown()
        raise ValueError("The mailbox said no to that address and password. Use an app password (not your normal "
                         "password), and make sure IMAP is on.") from e
    return m


def test(pid, f):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f.get("address", "")):
        raise ValueError("That doesn't look like an email address.")
    try:
        m = _imap(pid, f)
    except (OSError, imaplib.IMAP4.error) as e:
        raise ValueError(f"Couldn't reach the mail server ({type(e).__name__}). Check the server name and your internet.") from None
    try:
        typ, _ = m.select("INBOX", readonly=True)
        if typ != "OK":
            raise ValueError("Signed in, but couldn't open the inbox.")
    finally:
        m.logout()
    return {"account": f["address"]}


def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _accounts(want=None):
    ids = connections.connected_ids("email")
    if not ids:
        raise ValueError("no email is connected")
    return [want] if want in ids else ids[:1]


def _headers(m, uids):
    out = []
    for uid in reversed(uids):
        typ, data = m.uid("fetch", uid, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            continue
        msg = email.message_from_bytes(data[0][1])
        flags = data[0][0].decode(errors="replace")
        out.append({"uid": uid.decode() if isinstance(uid, bytes) else str(uid), "from": _dec(msg.get("From")),
                    "subject": _dec(msg.get("Subject")) or "(no subject)", "date": msg.get("Date", "")[:25],
                    "unread": "\\Seen" not in flags})
    return out


def _fmt(pid, rows, title):
    if not rows:
        return f"{title}: nothing found."
    return f"{title} ({connections.BY_ID[pid]['name']}):\n" + "\n".join(
        f"- id {pid}:{r['uid']} | {'UNREAD | ' if r['unread'] else ''}{r['date']} | from {r['from'][:60]} | {r['subject'][:120]}" for r in rows)


def inbox(account=None, unread_only=False, count=10):
    pid = _accounts(account)[0]
    m = _imap(pid)
    try:
        m.select("INBOX", readonly=True)
        typ, data = m.uid("search", None, "UNSEEN" if unread_only else "ALL")
        uids = data[0].split()[-max(1, min(int(count or 10), 25)):] if typ == "OK" and data and data[0] else []
        return _fmt(pid, _headers(m, uids), "Unread emails" if unread_only else "Recent emails")
    finally:
        m.logout()


def search(query, account=None):
    pid = _accounts(account)[0]
    q = (query or "").replace('"', "").strip()[:80]
    if not q:
        return "Give me a word, a sender or a subject to look for."
    m = _imap(pid)
    try:
        m.select("INBOX", readonly=True)
        if pid == "gmail":   # Gmail's own search syntax, the same as the Gmail search box
            typ, data = m.uid("search", None, "X-GM-RAW", f'"{q}"')
        else:
            m._encoding = "utf-8"
            typ, data = m.uid("search", "CHARSET", "UTF-8", "OR", "OR", "FROM", f'"{q}"', "SUBJECT", f'"{q}"', "TEXT", f'"{q}"')
        uids = data[0].split()[-10:] if typ == "OK" and data and data[0] else []
        return _fmt(pid, _headers(m, uids), f"Emails matching '{q}'")
    finally:
        m.logout()


def _text_of(msg):
    plain, html = [], []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        (plain if part.get_content_type() == "text/plain" else html if part.get_content_type() == "text/html" else []).append(text)
    if plain:
        return "\n".join(plain)
    raw = "\n".join(html)
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return re.sub(r"\s{3,}", "\n\n", re.sub(r"<[^>]+>", " ", raw)).strip()


def read(mid):
    pid, _, uid = (mid or "").partition(":")
    if pid not in connections.connected_ids("email") or not uid.isdigit():
        return "Use an id from email_inbox or email_search (it looks like gmail:1234)."
    m = _imap(pid)
    try:
        m.select("INBOX", readonly=True)
        typ, data = m.uid("fetch", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not isinstance(data[0], tuple):
            return "That email couldn't be found (it may have been moved or deleted)."
        msg = email.message_from_bytes(data[0][1])
        atts = [_dec(p.get_filename()) for p in msg.walk() if p.get_filename()]
        body = _text_of(msg)
        return (f"From: {_dec(msg.get('From'))}\nTo: {_dec(msg.get('To'))}\nDate: {msg.get('Date', '')}\n"
                f"Subject: {_dec(msg.get('Subject'))}\n" + (f"Attachments: {', '.join(atts)}\n" if atts else "")
                + f"\n{body[:4000]}" + ("\n[...longer - trimmed]" if len(body) > 4000 else ""))
    finally:
        m.logout()


def send(to, subject, body, account=None, reply_to_id=""):
    pid = _accounts(account)[0]
    f, user, pw = _creds(pid)
    to = (to or "").strip()
    if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", to):
        return "Not sent: that isn't a single valid email address."
    if re.search(r"@(example|test|domain|email|company)\.(com|org|net)$", to, re.I):
        return "Not sent: that address looks made up. Ask the user for the real one."
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = f.get("address"), to, subject or "(no subject)"
    msg["Date"], msg["Message-ID"] = email.utils.formatdate(localtime=True), email.utils.make_msgid()
    if reply_to_id:   # thread the reply under the original
        rp, _, ruid = reply_to_id.partition(":")
        if rp == pid and ruid.isdigit():
            try:
                m = _imap(pid)
                m.select("INBOX", readonly=True)
                typ, data = m.uid("fetch", ruid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
                m.logout()
                orig = email.message_from_bytes(data[0][1]).get("Message-ID") if typ == "OK" and isinstance(data[0], tuple) else None
                if orig:
                    msg["In-Reply-To"] = msg["References"] = orig
            except Exception as e:
                log.info("couldn't thread the reply: %s", e)
    msg.set_content(body or "")
    _, _, host, port = _servers(pid, f)
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=TIMEOUT) as s:
            s.login(user, pw)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=TIMEOUT) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
    log.info("email sent from %s", pid)
    return f"Sent to {to} from {f.get('address')}."


def execute(name, a):
    try:
        if name == "email_inbox":
            return inbox(a.get("account"), bool(a.get("unread_only")), a.get("count") or 10)
        if name == "email_search":
            return search(a.get("query", ""), a.get("account"))
        if name == "email_read":
            return read(a.get("id", ""))
        if name == "email_send":
            return send(a.get("to", ""), a.get("subject", ""), a.get("body", ""), a.get("account"), a.get("reply_to_id", ""))
    except ValueError as e:
        return f"Email problem: {e}"
    except (OSError, imaplib.IMAP4.error, smtplib.SMTPException) as e:
        return f"Couldn't reach the mail server right now ({type(e).__name__}). Try again in a minute."
    return f"There's no tool called {name}."
