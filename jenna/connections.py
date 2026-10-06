"""Connections: the apps she can reach (the app's Connect tab).

Each provider has: what she can do with it, step-by-step setup the user follows, the fields they paste, and a test
that runs before anything is saved. Secrets go to Windows Credential Manager (one entry per provider, "conn:<id>");
config.json keeps only non-secret details (which account, when it was connected).

Status: "ready" (paste a key or password), "advanced" (the user makes their own developer app - no review needed for
their own account), "paid" (the platform bills the user per use), "later" (needs an approved app first - shown as
coming later, never offered). "beta" marks ones that haven't been tested against a real account yet.
"""
import json
import logging
from datetime import datetime

from .settings import delete_secret, get_secret, load_config, set_secret, update_config

log = logging.getLogger("jenna")

EMAIL_STEPS_TAIL = "Paste your email address and the app password below. She only reads mail when you ask, and she never sends anything without your Yes."
SLACK_MANIFEST = {
    "display_information": {"name": "Jenna Lite", "description": "Your private AI assistant, running on your own PC."},
    "features": {"bot_user": {"display_name": "Jenna Lite", "always_online": True},
                 "app_home": {"messages_tab_enabled": True, "messages_tab_read_only_enabled": False}},
    "oauth_config": {"scopes": {"bot": ["chat:write", "im:history", "im:read", "im:write", "channels:read", "users:read"]}},
    "settings": {"event_subscriptions": {"bot_events": ["message.im"]}, "socket_mode_enabled": True,
                 "org_deploy_enabled": False, "token_rotation_enabled": False},
}

PROVIDERS = [
    # ---------------- chat with her ----------------
    {"id": "telegram", "group": "Chat with her", "name": "Telegram", "status": "ready", "color": "#2AABEE",
     "does": "Text or voice-note her from anywhere.", "special": "telegram"},
    {"id": "phone", "group": "Chat with her", "name": "Your phone", "status": "ready", "color": "#29B885",
     "does": "Her full app on your phone, privately, through Tailscale.", "special": "phone"},
    {"id": "slack", "group": "Chat with her", "name": "Slack", "status": "ready", "beta": True, "color": "#4A154B",
     "does": "Message her in Slack like a coworker, and have her post to a channel after your Yes.",
     "steps": ["Open [api.slack.com/apps](https://api.slack.com/apps) and sign in to your workspace.",
               "Click Create New App > From a manifest, pick your workspace, choose JSON, and paste the manifest below. Click Create.",
               "Click Install to Workspace and allow it. Then open OAuth & Permissions and copy the Bot User OAuth Token (starts with xoxb-).",
               "Open Basic Information > App-Level Tokens > Generate Token and Scopes. Name it 'socket', add the connections:write scope, generate, and copy the token (starts with xapp-).",
               "Paste both tokens below. Then in Slack, open the Jenna Lite app's Messages tab and send her the pairing code she shows you."],
     "copy": json.dumps(SLACK_MANIFEST, indent=2),
     "fields": [{"key": "bot_token", "label": "Bot token (xoxb-...)", "secret": True},
                {"key": "app_token", "label": "App-level token (xapp-...)", "secret": True}]},

    # ---------------- email ----------------
    {"id": "gmail", "group": "Email", "name": "Gmail", "status": "ready", "color": "#EA4335", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["Turn on 2-Step Verification at [myaccount.google.com/security](https://myaccount.google.com/security) (app passwords need it).",
               "Open [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), type 'Jenna Lite' and click Create. Copy the 16-letter password.",
               EMAIL_STEPS_TAIL,
               "Business Gmail (Google Workspace) can't use app passwords - that one is coming later."],
     "fields": [{"key": "address", "label": "Gmail address"}, {"key": "password", "label": "App password", "secret": True}]},
    {"id": "yahoo", "group": "Email", "name": "Yahoo Mail", "status": "ready", "beta": True, "color": "#6001D2", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["Open [login.yahoo.com/account/security](https://login.yahoo.com/account/security).",
               "Click Generate app password (or Manage app passwords), name it 'Jenna Lite' and copy the password.", EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "Yahoo address"}, {"key": "password", "label": "App password", "secret": True}]},
    {"id": "icloud_mail", "group": "Email", "name": "iCloud Mail", "status": "ready", "beta": True, "color": "#3693F3", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["Open [account.apple.com](https://account.apple.com) and sign in.",
               "Go to Sign-In and Security > App-Specific Passwords, click +, name it 'Jenna Lite' and copy the password.",
               "Use your @icloud.com (or @me.com) address. " + EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "iCloud email address"}, {"key": "password", "label": "App-specific password", "secret": True}]},
    {"id": "aol", "group": "Email", "name": "AOL Mail", "status": "ready", "beta": True, "color": "#31459B", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["Open [login.aol.com/account/security](https://login.aol.com/account/security).",
               "Click Generate app password, name it 'Jenna Lite' and copy it.", EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "AOL address"}, {"key": "password", "label": "App password", "secret": True}]},
    {"id": "zoho", "group": "Email", "name": "Zoho Mail", "status": "ready", "beta": True, "color": "#E42527", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["In Zoho Mail, open Settings > Mail Accounts > IMAP and make sure IMAP Access is on.",
               "Open [accounts.zoho.com](https://accounts.zoho.com) > Security > App Passwords, generate one named 'Jenna Lite' and copy it.",
               "Outside the US? Use 'Other email' instead with your region's server (for example imap.zoho.eu). " + EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "Zoho address"}, {"key": "password", "label": "App password", "secret": True}]},
    {"id": "fastmail", "group": "Email", "name": "Fastmail", "status": "ready", "beta": True, "color": "#0067B9", "kind": "email",
     "does": "Check, search and read your inbox; send replies after your Yes.",
     "steps": ["In Fastmail, open Settings > Privacy & Security > Manage app passwords and keys.",
               "Create a new app password with IMAP and SMTP access, name it 'Jenna Lite' and copy it.", EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "Fastmail address"}, {"key": "password", "label": "App password", "secret": True}]},
    {"id": "other_email", "group": "Email", "name": "Other email (your domain)", "status": "ready", "beta": True, "color": "#56677A", "kind": "email",
     "does": "Any mailbox with IMAP - your own domain, your web host's email, Proton Mail Bridge and more.",
     "steps": ["Find your provider's IMAP and SMTP settings (search '<your provider> IMAP settings').",
               "If your provider offers app passwords, make one for 'Jenna Lite'; otherwise use your mailbox password.",
               EMAIL_STEPS_TAIL],
     "fields": [{"key": "address", "label": "Email address"}, {"key": "password", "label": "Password or app password", "secret": True},
                {"key": "imap_host", "label": "IMAP server (e.g. mail.yourdomain.com)"}, {"key": "imap_port", "label": "IMAP port", "placeholder": "993"},
                {"key": "smtp_host", "label": "SMTP server"}, {"key": "smtp_port", "label": "SMTP port", "placeholder": "465"},
                {"key": "username", "label": "Username, if it isn't your email address", "optional": True}]},
    {"id": "outlook_mail", "group": "Email", "name": "Outlook, Hotmail & Microsoft 365", "status": "later", "color": "#0078D4",
     "does": "Microsoft turned off app passwords for Outlook.com in 2024; this needs a 'Sign in with Microsoft' app first. Your Outlook calendar works today - see Calendars."},
    {"id": "workspace_mail", "group": "Email", "name": "Google Workspace (business Gmail)", "status": "later", "color": "#34A853",
     "does": "Google removed app passwords for Workspace in 2025; this needs Google's review of a sign-in app first."},

    # ---------------- calendars ----------------
    {"id": "google_cal", "group": "Calendars", "name": "Google Calendar", "status": "ready", "color": "#4285F4", "kind": "calendar",
     "does": "Your appointments show on the Today tab and in her morning check-in, and she can answer 'what's on tomorrow?'",
     "steps": ["Open [calendar.google.com](https://calendar.google.com) on a computer, click the gear > Settings.",
               "Under 'Settings for my calendars' on the left, click the calendar you want.",
               "Scroll to 'Integrate calendar' and copy the 'Secret address in iCal format' (it ends in basic.ics).",
               "Paste it below. She can read it but not change it - add appointments by telling her, and they're kept on this PC."],
     "fields": [{"key": "url", "label": "Secret address in iCal format", "secret": True}]},
    {"id": "outlook_cal", "group": "Calendars", "name": "Outlook Calendar", "status": "ready", "beta": True, "color": "#0078D4", "kind": "calendar",
     "does": "Your appointments show on the Today tab and in her morning check-in, and she can answer 'what's on tomorrow?'",
     "steps": ["Open [outlook.live.com/calendar](https://outlook.live.com/calendar) (or Outlook on the web for work accounts) and click the gear > Calendar > Shared calendars.",
               "Under 'Publish a calendar', choose your calendar and 'Can view all details', then click Publish.",
               "Copy the ICS link and paste it below. (Some work accounts have publishing turned off by their admin.)"],
     "fields": [{"key": "url", "label": "ICS link", "secret": True}]},
    {"id": "icloud_cal", "group": "Calendars", "name": "Apple iCloud Calendar", "status": "ready", "beta": True, "color": "#FF3B30", "kind": "calendar",
     "does": "Your iPhone and Mac calendars on the Today tab and in her morning check-in.",
     "steps": ["Open [account.apple.com](https://account.apple.com) > Sign-In and Security > App-Specific Passwords, click +, name it 'Jenna Lite' and copy it.",
               "Paste your Apple ID email and that password below. She reads your calendars; she doesn't change them."],
     "fields": [{"key": "username", "label": "Apple ID email"}, {"key": "password", "label": "App-specific password", "secret": True}]},
    {"id": "other_cal", "group": "Calendars", "name": "Other calendar (iCal link)", "status": "ready", "beta": True, "color": "#56677A", "kind": "calendar",
     "does": "Yahoo, Proton, Fastmail, Zoho, a booking app or a sports schedule - anything that gives you an iCal / ICS link.",
     "steps": ["In your calendar app, look for Share, Publish, Export or 'Subscribe' and copy the iCal (.ics) link.",
               "Paste it below. A private link is best - it stays on this PC."],
     "fields": [{"key": "url", "label": "iCal / ICS link", "secret": True}, {"key": "label", "label": "Name for it (e.g. Work)", "optional": True}]},

    # ---------------- notes & work ----------------
    {"id": "notion", "group": "Notes & work", "name": "Notion", "status": "ready", "color": "#191919",
     "does": "Search and read your Notion pages, and add notes to them after your Yes.",
     "steps": ["Open [notion.so/profile/integrations](https://www.notion.so/profile/integrations) and click New integration.",
               "Name it 'Jenna Lite', pick your workspace, keep it Internal, and save. Copy the Internal Integration Secret (starts with ntn_).",
               "In Notion, open each page you want her to see, click ••• > Connections, and add Jenna Lite. She can only see pages you share this way.",
               "Paste the secret below."],
     "fields": [{"key": "token", "label": "Internal Integration Secret", "secret": True}]},

    # ---------------- social media ----------------
    {"id": "facebook", "group": "Social media", "name": "Facebook Page", "status": "advanced", "beta": True, "color": "#1877F2", "kind": "social",
     "does": "Draft and publish posts to your Page after your Yes, and read recent comments.",
     "steps": ["Open [developers.facebook.com/apps](https://developers.facebook.com/apps) and create an app. Choose the use case for managing a Page (Business type). It stays in development mode - that's fine for your own Page.",
               "Open Tools > [Graph API Explorer](https://developers.facebook.com/tools/explorer/), pick your app, and add the permissions pages_show_list, pages_manage_posts and pages_read_engagement. Click Generate Access Token and allow it.",
               "In the 'User or Page' menu pick your Page to get a Page access token. Make it long-lived: open the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/), paste it and click Extend Access Token.",
               "Paste the long-lived Page token and your Page ID (Page > About > Page transparency, or in the Explorer) below."],
     "fields": [{"key": "page_id", "label": "Page ID"}, {"key": "token", "label": "Page access token (long-lived)", "secret": True}]},
    {"id": "instagram", "group": "Social media", "name": "Instagram", "status": "advanced", "beta": True, "color": "#E1306C", "kind": "social",
     "does": "Publish photo posts with captions after your Yes, and check how recent posts did. Needs a Business or Creator account.",
     "steps": ["Make sure your Instagram is a Professional account (Business or Creator) - personal accounts can't post through Instagram's API.",
               "Open [developers.facebook.com/apps](https://developers.facebook.com/apps), create an app and add the Instagram product (API setup with Instagram login).",
               "Under App roles, add your Instagram account as an Instagram Tester, then accept the invite in Instagram (Settings > Apps and websites > Tester invites).",
               "Back in the app's Instagram setup, click Generate token next to your account, allow it, and copy the token. She renews it automatically every month.",
               "Instagram posts need a picture: when you ask her to post, give her a link to an image that's online."],
     "fields": [{"key": "token", "label": "Instagram access token", "secret": True}]},
    {"id": "threads", "group": "Social media", "name": "Threads", "status": "advanced", "beta": True, "color": "#101010", "kind": "social",
     "does": "Publish text posts to Threads after your Yes, and see your recent posts.",
     "steps": ["Open [developers.facebook.com/apps](https://developers.facebook.com/apps), create an app and choose the 'Access the Threads API' use case.",
               "Under App roles, add your Threads account as a Threads Tester and accept the invite in Threads (Settings > Account > Website permissions > Invites).",
               "In the use case settings, use the User Token Generator to make a token for your account and copy it. She renews it automatically every month."],
     "fields": [{"key": "token", "label": "Threads access token", "secret": True}]},
    {"id": "x", "group": "Social media", "name": "X (Twitter)", "status": "paid", "beta": True, "color": "#0F1419", "kind": "social",
     "does": "Publish posts to X after your Yes. X charges per post (about 1.5 cents, or about 20 cents with a link) to the credit on your developer account.",
     "steps": ["Open [developer.x.com](https://developer.x.com), sign in and create a project and app. Add a little credit - X bills each post (no free tier since 2026).",
               "In the app's User authentication settings, set App permissions to Read and write.",
               "Under Keys and tokens, copy the API Key and Secret, then generate an Access Token and Secret (made after you set Read and write).",
               "Paste all four below. Connecting runs one small test (a fraction of a cent)."],
     "fields": [{"key": "api_key", "label": "API Key", "secret": True}, {"key": "api_secret", "label": "API Key Secret", "secret": True},
                {"key": "access_token", "label": "Access Token", "secret": True}, {"key": "access_secret", "label": "Access Token Secret", "secret": True}]},
    # ---------------- add-ons (separate free apps the user installs) ----------------
    {"id": "image_video", "group": "Add-ons", "name": "Image & video creation", "status": "ready", "addon": True, "color": "#8B5CF6",
     "kind": "pictures",
     "does": "She makes pictures and edits your photos on your own PC, free, through ComfyUI (a separate free app you "
             "install once). Ask her: \"make a flyer for my bake sale\" or send a photo and say what to change.",
     "links": [{"label": "Download ComfyUI Desktop (free)", "url": "https://docs.comfy.org/installation/desktop/windows"}],
     "steps": ["Download ComfyUI Desktop for Windows (NVIDIA) from [docs.comfy.org](https://docs.comfy.org/installation/desktop/windows) and install it like any app. It needs an NVIDIA graphics card; each model is a few GB.",
               "Open ComfyUI, click Workflow > Browse Templates. It offers to download the model files a template needs - say yes.",
               "Pictures: open the Z-Image Turbo text-to-image template ('Text to Image') once so it downloads the model. It's fast (8 steps) and can put readable text on images.",
               "Photo editing: open the FLUX.2 [klein] image-edit template once too, so she can change your photos with words ('swap the background for a beach at sunset').",
               "Video: open the Video templates and pick Wan 2.2 5B (text or picture to video) - it runs on cards with 8 GB.",
               "Then just ask her: \"make a picture of...\" (she writes the detailed prompt), or send a photo with the paperclip and say what to change. Pictures are saved in Pictures/Jenna Lite.",
               "Tip: new pictures handle lettering well (signs, flyers); photo edits are less reliable with words - for text, ask for a new picture instead.",
               "Tip: she and ComfyUI share your graphics card - she hands it over automatically for each picture, so her next reply takes a few seconds longer.",
               "Leave ComfyUI open, then press Test & connect below (it finds ComfyUI by itself). Video from chat is coming next; for now make videos in ComfyUI."],
     "fields": [{"key": "url", "label": "ComfyUI address (leave empty to find it)", "optional": True,
                 "placeholder": "auto"}]},
    {"id": "tiktok", "group": "Social media", "name": "TikTok", "status": "later", "color": "#010101",
     "does": "Until an app passes TikTok's 2-4 week audit, every post it makes is forced to private. Coming once Jenna Lite is approved."},
    {"id": "linkedin", "group": "Social media", "name": "LinkedIn", "status": "later", "color": "#0A66C2",
     "does": "Coming later."},
    {"id": "youtube", "group": "Social media", "name": "YouTube", "status": "later", "color": "#FF0000",
     "does": "Coming later."},
    {"id": "pinterest", "group": "Social media", "name": "Pinterest", "status": "later", "color": "#E60023",
     "does": "Coming later."},
]
BY_ID = {p["id"]: p for p in PROVIDERS}
SOCIAL = ("facebook", "instagram", "threads", "x")


# ---------------- storage ----------------
def secrets(pid):
    raw = get_secret(f"conn:{pid}")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def saved(pid):
    return (load_config().get("connections") or {}).get(pid)


def connected(pid):
    p = BY_ID.get(pid) or {}
    if p.get("special") == "telegram":
        return bool(get_secret("telegram_token")) and bool(load_config().get("telegram_user_id"))
    if p.get("special") == "phone":
        return bool(load_config().get("pc_remote_hosts"))
    needs_secret = any(f.get("secret") for f in p.get("fields", []))
    return bool(saved(pid)) and (bool(secrets(pid)) or not needs_secret)


def connected_ids(kind=None):
    return [p["id"] for p in PROVIDERS if (not kind or p.get("kind") == kind) and p["status"] not in ("later", "addon")
            and not p.get("special") and connected(p["id"])]


def _save(pid, fields, info):
    p = BY_ID[pid]
    secret = {f["key"]: fields.get(f["key"], "") for f in p["fields"] if f.get("secret")}
    public = {f["key"]: fields.get(f["key"], "") for f in p["fields"] if not f.get("secret")}
    set_secret(f"conn:{pid}", json.dumps(secret))
    conns = dict(load_config().get("connections") or {})
    conns[pid] = {**public, **info, "connected": f"{datetime.now():%Y-%m-%d %H:%M}"}
    update_config(connections=conns)


def update_saved(pid, **changes):
    conns = dict(load_config().get("connections") or {})
    if pid in conns:
        conns[pid] = {**conns[pid], **changes}
        update_config(connections=conns)


def update_secret(pid, **changes):
    s = secrets(pid)
    s.update(changes)
    set_secret(f"conn:{pid}", json.dumps(s))


# ---------------- for the app ----------------
def overview():
    out = []
    for p in PROVIDERS:
        card = {k: v for k, v in p.items() if k not in ("fields",)}
        card["fields"] = [{k: v for k, v in f.items()} for f in p.get("fields", [])]
        card["connected"] = connected(p["id"])
        s = saved(p["id"]) or {}
        card["account"] = s.get("account", "")
        card["since"] = s.get("connected", "")
        if p["id"] == "slack" and card["connected"]:
            from . import memory
            card["pairing_code"] = "" if s.get("owner") else memory.get_state().get("slack_pairing", "")
        out.append(card)
    return {"providers": out}


def connect(pid, fields):
    p = BY_ID.get(pid)
    if not p or p["status"] in ("later", "addon") or p.get("special"):
        raise ValueError("That one can't be connected here.")
    fields = {k: str(v).strip() for k, v in (fields or {}).items()}
    missing = [f["label"] for f in p["fields"] if not f.get("optional") and not fields.get(f["key"]) and not f.get("placeholder")]
    if missing:
        raise ValueError("Fill in: " + ", ".join(missing))
    for f in p["fields"]:
        if not fields.get(f["key"]) and f.get("placeholder"):
            fields[f["key"]] = f["placeholder"]
    info = _test(pid, fields)   # raises ValueError with a plain reason if it doesn't work
    _save(pid, fields, info)
    log.info("connection added: %s", pid)
    if pid == "slack":
        from . import conn_slack
        conn_slack.start_pairing()
    return overview()


def disconnect(pid):
    if pid not in BY_ID or BY_ID[pid].get("special"):
        raise ValueError("unknown connection")
    delete_secret(f"conn:{pid}")
    conns = dict(load_config().get("connections") or {})
    conns.pop(pid, None)
    update_config(connections=conns)
    log.info("connection removed: %s", pid)
    return overview()


def _test(pid, f):
    kind = BY_ID[pid].get("kind")
    if kind == "email":
        from . import conn_email
        return conn_email.test(pid, f)
    if kind == "calendar":
        from . import conn_calendar
        return conn_calendar.test(pid, f)
    if pid == "notion":
        from . import conn_notion
        return conn_notion.test(f)
    if pid == "slack":
        from . import conn_slack
        return conn_slack.test(f)
    if kind == "social":
        from . import conn_social
        return conn_social.test(pid, f)
    if kind == "pictures":
        from . import conn_comfy
        return conn_comfy.test(f)
    raise ValueError("unknown connection")


# ---------------- what she knows and the tools she gets ----------------
def prompt_line():
    """One line for her system prompt: what's connected right now."""
    names = [BY_ID[i]["name"] for i in connected_ids()]
    return ("Connected apps right now: " + ", ".join(names) + ". Never claim to use an app that isn't on this list."
            if names else "No apps are connected yet (the user adds them in the Connect tab). Never claim to read email, "
                          "calendars, Notion, Slack or social media until they're connected.")


def _fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


S = {"type": "string"}


def tool_schemas():
    """Tools for whatever is connected, in a fixed order (the list only changes when a connection does)."""
    out = []
    mail = connected_ids("email")
    if mail:
        acct = {"type": "string", "enum": mail, "description": "which mailbox (default: the first)"}
        out += [_fn("email_inbox", "List recent emails in the user's inbox (newest first).",
                    {"account": acct, "unread_only": {"type": "boolean"}, "count": {"type": "integer"}}),
                _fn("email_search", "Search the user's email (sender, subject or words in the message).",
                    {"query": S, "account": acct}, ["query"]),
                _fn("email_read", "Read one email in full by the id from email_inbox / email_search.", {"id": S}, ["id"]),
                _fn("email_send", "Send an email (or a reply) from the user's mailbox. They confirm with Yes first. Never invent an address.",
                    {"to": S, "subject": S, "body": S, "account": acct, "reply_to_id": S}, ["to", "subject", "body"])]
    if connected("notion"):
        out += [_fn("notion_search", "Search the user's Notion pages (only pages they shared with Jenna Lite).", {"query": S}, ["query"]),
                _fn("notion_read", "Read a Notion page by its id (from notion_search).", {"page_id": S}, ["page_id"]),
                _fn("notion_append", "Add text to the end of a Notion page. The user confirms with Yes first.",
                    {"page_id": S, "text": S}, ["page_id", "text"])]
    if connected("slack"):
        out.append(_fn("slack_post", "Post a message to a Slack channel the app was added to (e.g. #general). The user confirms first.",
                       {"channel": S, "text": S}, ["channel", "text"]))
    if connected("image_video"):
        out += [_fn("make_image", "Make a picture with ComfyUI on the user's PC (the user confirms first). Write the prompt "
                    "yourself: 40-80 words - subject, setting, style, colors, lighting; exact words for any text in double "
                    "quotes. It runs in the background (about a minute) and appears in the chat when done.",
                    {"prompt": S, "aspect": {"type": "string", "enum": ["square", "portrait", "landscape"]},
                     "count": {"type": "integer", "description": "1-4 (default 1)"}}, ["prompt"]),
                _fn("edit_photo", "Edit the last photo the user sent (paperclip in the app, or a photo on Telegram) from a "
                    "plain instruction like 'replace the background with a beach at sunset'. The user confirms first.",
                    {"instruction": S}, ["instruction"])]
    social = [i for i in SOCIAL if connected(i)]
    if social:
        plat = {"type": "string", "enum": social}
        out += [_fn("social_post", "Publish a post to one of the user's social accounts. They confirm with Yes first. Instagram needs "
                    "image_url (a public link to a picture). X charges the user per post.",
                    {"platform": plat, "text": S, "image_url": S}, ["platform", "text"]),
                _fn("social_recent", "The user's recent posts on a platform, with likes and comments where available.",
                    {"platform": plat}, ["platform"])]
    return out


CONFIRM = {"email_send", "notion_append", "slack_post", "social_post", "make_image", "edit_photo"}
UNTRUSTED = {"email_inbox": "email", "email_search": "email", "email_read": "email", "notion_search": "notion",
             "notion_read": "notion", "social_recent": "social media"}


def confirm_summary(name, a):
    if name == "email_send":
        return f"Send this email?\n\nTo: {a.get('to')}\nSubject: {a.get('subject')}\n\n{str(a.get('body', ''))[:900]}"
    if name == "notion_append":
        return f"Add this to the Notion page?\n\n{str(a.get('text', ''))[:700]}"
    if name == "slack_post":
        return f"Post this in Slack {a.get('channel')}?\n\n{str(a.get('text', ''))[:700]}"
    if name == "make_image":
        n = max(1, min(int(a.get("count") or 1), 4))
        return (f"Make {'this picture' if n == 1 else f'{n} pictures'} ({a.get('aspect') or 'square'})?\n\n{str(a.get('prompt', ''))[:700]}"
                "\n\nShe hands the graphics card to ComfyUI for about a minute.")
    if name == "edit_photo":
        return f"Edit your last photo like this?\n\n{str(a.get('instruction', ''))[:500]}"
    if name == "social_post":
        plat = BY_ID.get(a.get("platform"), {}).get("name", a.get("platform"))
        cost = "\n\n(X charges about 1.5 cents for this post, about 20 cents if it has a link.)" if a.get("platform") == "x" else ""
        img = f"\nPicture: {a['image_url']}" if a.get("image_url") else ""
        return f"Publish this on {plat}?\n\n{str(a.get('text', ''))[:900]}{img}{cost}"
    return None


def execute(name, a):
    if name.startswith("email_"):
        from . import conn_email
        return conn_email.execute(name, a)
    if name.startswith("notion_"):
        from . import conn_notion
        return conn_notion.execute(name, a)
    if name == "slack_post":
        from . import conn_slack
        return conn_slack.post(a.get("channel", ""), a.get("text", ""))
    if name.startswith("social_"):
        from . import conn_social
        return conn_social.execute(name, a)
    if name in ("make_image", "edit_photo"):
        from . import conn_comfy
        try:
            if name == "make_image":
                return conn_comfy.start_picture(a.get("prompt", ""), a.get("aspect") or "square", a.get("count") or 1)
            return conn_comfy.start_edit(a.get("instruction", ""))
        except Exception as e:
            return f"Couldn't reach ComfyUI ({type(e).__name__}) - is it open?"
    return f"There's no tool called {name}."
