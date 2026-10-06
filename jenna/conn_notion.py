"""Notion through an internal integration token. She only sees pages the user shared with the integration
(••• > Connections). Search and read freely; adding to a page goes through the Yes card. Page text is untrusted
(people paste web text into notes)."""
import logging
import re

import requests

from . import connections

log = logging.getLogger("jenna")
API = "https://api.notion.com/v1"
VERSION = "2022-06-28"


def _h(token=None):
    token = token or connections.secrets("notion").get("token", "")
    return {"Authorization": f"Bearer {token}", "Notion-Version": VERSION, "Content-Type": "application/json"}


def _req(method, path, token=None, **kw):
    r = requests.request(method, API + path, headers=_h(token), timeout=25, **kw)
    if r.status_code == 401:
        raise ValueError("Notion didn't accept the secret - copy it again from your integration.")
    if r.status_code == 404:
        raise ValueError("Notion can't find that page - share it with Jenna Lite (••• > Connections).")
    if r.status_code >= 400:
        raise ValueError(f"Notion said: {r.json().get('message', r.status_code)}")
    return r.json()


def test(f):
    if not re.fullmatch(r"(ntn_|secret_)[A-Za-z0-9]{30,}", f.get("token", "")):
        raise ValueError("That doesn't look like a Notion secret (it starts with ntn_).")
    me = _req("GET", "/users/me", f["token"])
    shared = _req("POST", "/search", f["token"], json={"page_size": 5})
    return {"account": (me.get("bot") or {}).get("workspace_name") or me.get("name") or "Notion",
            "pages_shared": len(shared.get("results", []))}


def _title(obj):
    props = obj.get("properties") or {}
    for p in props.values():
        if p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in p.get("title", [])) or "(untitled)"
    return "".join(t.get("plain_text", "") for t in obj.get("title", [])) or "(untitled)"


def search(query):
    d = _req("POST", "/search", json={"query": (query or "")[:100], "page_size": 10})
    rows = d.get("results", [])
    if not rows:
        return f"No Notion pages match '{query}' (she only sees pages shared with Jenna Lite)."
    return "Notion pages:\n" + "\n".join(f"- {_title(o)} | {o['object']} | id {o['id']} | edited {o.get('last_edited_time', '')[:10]}"
                                         for o in rows)


def _block_text(b):
    t = b.get("type")
    rich = (b.get(t) or {}).get("rich_text") or []
    text = "".join(x.get("plain_text", "") for x in rich)
    prefix = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ", "bulleted_list_item": "- ", "numbered_list_item": "1. ",
              "to_do": "[x] " if (b.get("to_do") or {}).get("checked") else "[ ] ", "quote": "> "}.get(t, "")
    if t == "child_page":
        return f"(sub-page: {(b.get('child_page') or {}).get('title', '')}, id {b['id']})"
    return prefix + text if text else ""


def read(page_id):
    m = re.search(r"[0-9a-f]{32}", (page_id or "").replace("-", "").lower())   # an id, or a Notion link that ends in one
    if not m:
        return "Use a page id from notion_search (or the page's Notion link)."
    pid = m.group(0)
    page = _req("GET", f"/pages/{pid}")
    blocks = _req("GET", f"/blocks/{pid}/children?page_size=100").get("results", [])
    body = "\n".join(x for x in (_block_text(b) for b in blocks) if x)
    return f"{_title(page)}\n\n{body[:5000]}" + ("\n[...longer - trimmed]" if len(body) > 5000 else "")


def append(page_id, text):
    chunks = [text[i:i + 1900] for i in range(0, len(text or ""), 1900)] or [""]
    _req("PATCH", f"/blocks/{page_id}/children", json={"children": [
        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": c}}]}}
        for c in chunks]})
    return "Added to the Notion page."


def execute(name, a):
    try:
        if name == "notion_search":
            return search(a.get("query", ""))
        if name == "notion_read":
            return read(a.get("page_id", ""))
        if name == "notion_append":
            return append(a.get("page_id", ""), a.get("text", ""))
    except ValueError as e:
        return f"Notion problem: {e}"
    except requests.RequestException as e:
        return f"Couldn't reach Notion right now ({type(e).__name__})."
    return f"There's no tool called {name}."
