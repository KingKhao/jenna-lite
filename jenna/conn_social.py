"""Social media: Facebook Pages, Instagram (Business/Creator), Threads and X.

The user makes their own developer app (Meta in development mode needs no review for their own account; X bills
per post), so nothing here depends on an approved Jenna Lite app. Posting always goes through the Yes card.
Instagram and Threads tokens last 60 days - refresh() renews them monthly (the scheduler calls it daily).
"""
import logging
import time
from datetime import datetime, timedelta

import requests

from . import connections

log = logging.getLogger("jenna")
FB = "https://graph.facebook.com"
IG = "https://graph.instagram.com"
TH = "https://graph.threads.net/v1.0"
X = "https://api.x.com/2"


def _s(pid):
    return {**(connections.saved(pid) or {}), **connections.secrets(pid)}


def _check(r, who):
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code >= 400 or "error" in d:
        err = d.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        msg = msg or d.get("detail") or d.get("title") or f"error {r.status_code}"
        if r.status_code in (401, 403) and who == "X" and "credit" in str(d).lower():
            msg = "your X developer account is out of credit"
        raise ValueError(f"{who} said: {msg}")
    return d


def _x_session(f):
    from requests_oauthlib import OAuth1Session
    return OAuth1Session(f["api_key"], client_secret=f["api_secret"], resource_owner_key=f["access_token"],
                         resource_owner_secret=f["access_secret"])


def test(pid, f):
    try:
        if pid == "facebook":
            d = _check(requests.get(f"{FB}/{f['page_id']}", params={"fields": "name", "access_token": f["token"]}, timeout=20), "Facebook")
            return {"account": d.get("name", "Facebook Page")}
        if pid == "instagram":
            d = _check(requests.get(f"{IG}/me", params={"fields": "user_id,username,account_type", "access_token": f["token"]}, timeout=20), "Instagram")
            if str(d.get("account_type", "")).upper() not in ("BUSINESS", "MEDIA_CREATOR", "CREATOR", ""):
                raise ValueError("That's a personal Instagram account - switch it to Professional (Business or Creator) first.")
            return {"account": "@" + d.get("username", "instagram"), "refreshed": f"{datetime.now():%Y-%m-%d}"}
        if pid == "threads":
            d = _check(requests.get(f"{TH}/me", params={"fields": "id,username", "access_token": f["token"]}, timeout=20), "Threads")
            return {"account": "@" + d.get("username", "threads"), "refreshed": f"{datetime.now():%Y-%m-%d}"}
        if pid == "x":
            d = _check(_x_session(f).get(f"{X}/users/me", timeout=20), "X")
            return {"account": "@" + (d.get("data") or {}).get("username", "x")}
    except requests.RequestException as e:
        raise ValueError(f"Couldn't reach it right now ({type(e).__name__}).") from None
    raise ValueError("unknown platform")


def post(pid, text, image_url=""):
    f = _s(pid)
    text = (text or "").strip()
    if pid == "facebook":
        body = {"message": text, "access_token": f["token"]}
        if image_url:
            d = _check(requests.post(f"{FB}/{f['page_id']}/photos", data={**body, "url": image_url, "caption": text}, timeout=60), "Facebook")
        else:
            d = _check(requests.post(f"{FB}/{f['page_id']}/feed", data=body, timeout=30), "Facebook")
        return f"Posted on your Facebook Page (id {d.get('post_id') or d.get('id')})."
    if pid == "instagram":
        if not image_url:
            return "Not posted: Instagram posts need a picture. Ask the user for a link to an image that's online."
        c = _check(requests.post(f"{IG}/me/media", data={"image_url": image_url, "caption": text, "access_token": f["token"]}, timeout=60), "Instagram")
        for _ in range(15):   # the photo has to finish processing before it can be published
            st = _check(requests.get(f"{IG}/{c['id']}", params={"fields": "status_code", "access_token": f["token"]}, timeout=20), "Instagram")
            if st.get("status_code") in ("FINISHED", None):
                break
            if st.get("status_code") == "ERROR":
                return "Not posted: Instagram couldn't use that picture (it must be a public JPG link)."
            time.sleep(2)
        d = _check(requests.post(f"{IG}/me/media_publish", data={"creation_id": c["id"], "access_token": f["token"]}, timeout=60), "Instagram")
        return f"Posted on Instagram (id {d.get('id')})."
    if pid == "threads":
        data = {"media_type": "IMAGE" if image_url else "TEXT", "text": text[:500], "access_token": f["token"]}
        if image_url:
            data["image_url"] = image_url
        c = _check(requests.post(f"{TH}/me/threads", data=data, timeout=60), "Threads")
        time.sleep(3 if image_url else 1)   # Meta recommends a short wait before publishing
        d = _check(requests.post(f"{TH}/me/threads_publish", data={"creation_id": c["id"], "access_token": f["token"]}, timeout=60), "Threads")
        return f"Posted on Threads (id {d.get('id')})."
    if pid == "x":
        if image_url:
            text = f"{text} {image_url}".strip()
        if len(text) > 280:
            return f"Not posted: X allows 280 characters and this is {len(text)}. Shorten it first."
        d = _check(_x_session(f).post(f"{X}/tweets", json={"text": text}, timeout=30), "X")
        return f"Posted on X (id {(d.get('data') or {}).get('id')})."
    return "unknown platform"


def recent(pid):
    f = _s(pid)
    if pid == "facebook":
        d = _check(requests.get(f"{FB}/{f['page_id']}/posts", params={
            "fields": "message,created_time,permalink_url,comments.summary(true).limit(3){message,from}", "limit": 5,
            "access_token": f["token"]}, timeout=30), "Facebook")
        rows = d.get("data", [])
        return "\n".join(f"- {p.get('created_time', '')[:10]}: {(p.get('message') or '(photo)')[:160]} | "
                         f"{(p.get('comments') or {}).get('summary', {}).get('total_count', 0)} comments"
                         + "".join(f"\n    comment: {c.get('message', '')[:140]}" for c in (p.get('comments') or {}).get('data', []))
                         for p in rows) or "No posts yet."
    if pid == "instagram":
        d = _check(requests.get(f"{IG}/me/media", params={"fields": "caption,timestamp,like_count,comments_count,permalink",
                                                          "limit": 5, "access_token": f["token"]}, timeout=30), "Instagram")
        return "\n".join(f"- {p.get('timestamp', '')[:10]}: {(p.get('caption') or '')[:140]} | {p.get('like_count', 0)} likes, "
                         f"{p.get('comments_count', 0)} comments | {p.get('permalink', '')}" for p in d.get("data", [])) or "No posts yet."
    if pid == "threads":
        d = _check(requests.get(f"{TH}/me/threads", params={"fields": "text,timestamp,permalink", "limit": 5,
                                                            "access_token": f["token"]}, timeout=30), "Threads")
        return "\n".join(f"- {p.get('timestamp', '')[:10]}: {(p.get('text') or '')[:160]} | {p.get('permalink', '')}"
                         for p in d.get("data", [])) or "No posts yet."
    if pid == "x":
        return "Reading posts on X costs money per post, so I don't check X automatically. Open X to see replies."
    return "unknown platform"


def refresh():
    """Renew Instagram and Threads tokens about once a month (they expire after 60 days unused)."""
    for pid, url, grant in (("instagram", f"{IG}/refresh_access_token", "ig_refresh_token"),
                            ("threads", "https://graph.threads.net/refresh_access_token", "th_refresh_token")):
        if not connections.connected(pid):
            continue
        last = (connections.saved(pid) or {}).get("refreshed", "")
        if last and datetime.now() - datetime.strptime(last, "%Y-%m-%d") < timedelta(days=25):
            continue
        try:
            d = _check(requests.get(url, params={"grant_type": grant, "access_token": _s(pid)["token"]}, timeout=30), pid)
            if d.get("access_token"):
                connections.update_secret(pid, token=d["access_token"])
                connections.update_saved(pid, refreshed=f"{datetime.now():%Y-%m-%d}")
                log.info("%s token renewed", pid)
        except Exception as e:
            log.warning("%s token renewal failed: %s", pid, e)


def execute(name, a):
    pid = a.get("platform", "")
    if pid not in connections.SOCIAL or not connections.connected(pid):
        return f"{pid or 'That platform'} isn't connected."
    try:
        if name == "social_post":
            return post(pid, a.get("text", ""), a.get("image_url", ""))
        if name == "social_recent":
            return recent(pid)
    except ValueError as e:
        return f"Not done - {e}"
    except requests.RequestException as e:
        return f"Couldn't reach {connections.BY_ID[pid]['name']} right now ({type(e).__name__})."
    return f"There's no tool called {name}."
