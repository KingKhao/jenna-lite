"""Slack: talk to her in a direct message (Socket Mode - no public web address needed), and let her post to a
channel after the user's Yes.

The first person to DM the pairing code becomes the owner; she ignores everyone else, exactly like Telegram.
Messages go through the same pipeline as the app and Telegram (Bot.handle_text), so it's the same assistant.
"""
import logging
import re
import secrets
import threading
import time
from pathlib import Path

from . import connections, live, memory

log = logging.getLogger("jenna")
_state = {"client": None, "thread": None, "bot": None}


def test(f):
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    bot, app = f.get("bot_token", ""), f.get("app_token", "")
    if not bot.startswith("xoxb-"):
        raise ValueError("The bot token starts with xoxb- (OAuth & Permissions page).")
    if not app.startswith("xapp-"):
        raise ValueError("The app-level token starts with xapp- (Basic Information > App-Level Tokens).")
    try:
        me = WebClient(token=bot, timeout=20).auth_test()
        WebClient(token=app, timeout=20).apps_connections_open(app_token=app)
    except SlackApiError as e:
        err = e.response.get("error", "error")
        hint = {"invalid_auth": "a token is wrong or was revoked", "not_allowed_token_type": "the two tokens are swapped",
                "missing_scope": "the app-level token needs the connections:write scope"}.get(err, err)
        raise ValueError(f"Slack didn't accept that: {hint}.") from None
    return {"account": f"{me.get('team', 'Slack')} (@{me.get('user', 'bot')})", "bot_user": me.get("user_id", "")}


def start_pairing():
    memory.set_state(slack_pairing=f"{secrets.randbelow(900000) + 100000}")
    connections.update_saved("slack", owner="")
    restart()


def _reply(client, channel, out):
    for item in out:
        if item.get("type") == "text" and item.get("text"):
            client.chat_postMessage(channel=channel, text=item["text"][:3900])
        elif item.get("type") == "confirm":
            client.chat_postMessage(channel=channel, text=f"Need your OK:\n\n{item['summary'][:3500]}\n\nReply *yes* or *no*.")


def _handle(client, req):
    from slack_sdk.socket_mode.response import SocketModeResponse
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))   # ack first, Slack retries otherwise
    if req.type != "events_api":
        return
    ev = (req.payload or {}).get("event") or {}
    if ev.get("type") != "message" or ev.get("channel_type") != "im" or ev.get("bot_id") or ev.get("subtype"):
        return
    user, text, channel = ev.get("user", ""), (ev.get("text") or "").strip(), ev.get("channel", "")
    saved = connections.saved("slack") or {}
    if not saved.get("owner"):
        code = memory.get_state().get("slack_pairing")
        if code and text == code:
            connections.update_saved("slack", owner=user)
            memory.set_state(slack_pairing=None)
            client.web_client.chat_postMessage(channel=channel, text="Paired! I'll only listen to you here. Say hi, or ask me anything.")
            live.publish("assistant", "Slack is connected.", "app", kind="paired")
        return
    if user != saved["owner"] or not text:
        return
    if saved.get("dm_channel") != channel:
        connections.update_saved("slack", dm_channel=channel)   # where finished pictures go
    bot = _state["bot"]
    if not bot:
        return

    def go():
        from .settings import busy
        try:
            live.publish("user", text, "slack")
            with busy(), live.conversation(), bot.capture() as out:
                bot.handle_text(text)
            for item in out:
                if item.get("type") == "text":
                    live.publish("assistant", item["text"], "slack")
            _reply(client.web_client, channel, out)
        except Exception:
            log.exception("slack message failed")
            client.web_client.chat_postMessage(channel=channel, text="Sorry - something went wrong on my end. It's in my log.")
    threading.Thread(target=go, name="slack-turn", daemon=True).start()


def run(bot):
    """Keep a Socket Mode connection open while Slack is connected (picks up connects/disconnects within ~30 s)."""
    _state["bot"] = bot
    while True:
        try:
            if connections.connected("slack") and not _state["client"]:
                from slack_sdk import WebClient
                from slack_sdk.socket_mode.builtin import SocketModeClient
                s = connections.secrets("slack")
                client = SocketModeClient(app_token=s["app_token"], web_client=WebClient(token=s["bot_token"], timeout=30),
                                          auto_reconnect_enabled=True)
                client.socket_mode_request_listeners.append(_handle)
                client.connect()
                _state["client"] = client
                log.info("slack connected (socket mode)")
            elif not connections.connected("slack") and _state["client"]:
                restart()
        except Exception:
            log.exception("slack connection failed - retrying in a minute")
            restart()
            time.sleep(60)
        time.sleep(30)


def restart():
    c, _state["client"] = _state["client"], None
    if c:
        try:
            c.close()
        except Exception as e:
            log.debug("slack close: %r", e)


def send_files(paths, text):
    """Finished pictures into the Slack DM with the owner (if Slack is connected and they've messaged her there)."""
    s, saved = connections.secrets("slack"), connections.saved("slack") or {}
    if not s.get("bot_token") or not saved.get("dm_channel"):
        return
    from slack_sdk import WebClient
    WebClient(token=s["bot_token"], timeout=120).files_upload_v2(
        channel=saved["dm_channel"], initial_comment=text,
        file_uploads=[{"file": str(p), "filename": Path(p).name} for p in paths])


def post(channel, text):
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
    s = connections.secrets("slack")
    ch = (channel or "").strip()
    if not re.fullmatch(r"#?[\w.-]{1,80}|[CDG][A-Z0-9]{6,}", ch):
        return "Not posted: give a channel like #general."
    try:
        WebClient(token=s["bot_token"], timeout=20).chat_postMessage(channel=ch if ch[0] in "CDG#" else "#" + ch, text=text[:3900])
    except SlackApiError as e:
        err = e.response.get("error", "error")
        if err in ("not_in_channel", "channel_not_found"):
            return f"Not posted: add the Jenna Lite app to {ch} first (in Slack: open the channel > Integrations > Add apps)."
        return f"Slack said: {err}"
    return f"Posted in {ch}."
