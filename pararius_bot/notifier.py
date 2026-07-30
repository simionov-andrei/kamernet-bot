"""
Sends an instant alert to your phone via a *separate* Telegram bot dedicated
to Pararius matches (so Kamernet and Pararius alerts don't get mixed into one
chat/bot).

One-time setup (2 minutes):
  1. In Telegram, message @BotFather -> /newbot -> follow prompts.
     It gives you a TOKEN like 123456:ABC-DEF... (this must be a DIFFERENT
     bot than the one used for kamernet_bot).
  2. Message your new bot once (say "hi") so it's allowed to message you.
  3. Get your chat id: open in a browser
        https://api.telegram.org/bot<TOKEN>/getUpdates
     and copy the "chat":{"id": <number> } value.
  4. Put TOKEN and chat id into the PARARIUS_TELEGRAM_TOKEN and
     PARARIUS_TELEGRAM_CHAT_ID environment variables (see README / .env).
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
import requests

log = logging.getLogger("pararius.notifier")

load_dotenv()
TOKEN = os.getenv("PARARIUS_TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("PARARIUS_TELEGRAM_CHAT_ID", "")


def notify(listing: dict, message_template: str) -> None:
    """Send a formatted alert about one matching listing."""
    if not TOKEN or not CHAT_ID:
        log.error("PARARIUS_TELEGRAM_TOKEN / PARARIUS_TELEGRAM_CHAT_ID not set — cannot send alert.")
        return

    rent = listing.get("rent")
    area = listing.get("area")
    rooms = listing.get("rooms")
    prefilled = message_template.format(
        title=listing.get("title", ""),
        city=listing.get("city", ""),
    )

    text = (
        f"🏠 <b>New Pararius match</b>\n"
        f"<b>{_esc(listing.get('title',''))}</b>\n"
        f"{_esc(listing.get('city',''))} · "
        f"{'€'+str(int(rent)) if rent else '?'} · "
        f"{str(int(area))+'m²' if area else '?'} · "
        f"{str(rooms)+' rooms' if rooms else '?'} · "
        f"{_esc(listing.get('property_type',''))}\n\n"
        f'<a href="{listing.get("url","")}">Open listing ↗</a>\n\n'
        f"<b>Tap to copy your reply:</b>\n"
        f"<code>{_esc(prefilled)}</code>"
    )

    resp = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
        timeout=15,
    )
    if not resp.ok:
        log.error("Telegram send failed: %s %s", resp.status_code, resp.text)
    else:
        log.info("Alerted: %s", listing.get("title", ""))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
