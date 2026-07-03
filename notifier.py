"""
Sends an instant alert to your phone via a Telegram bot.

Why Telegram: it's free, instant, arrives as a phone push notification, and the
send is a single HTTPS call with no browser automation — nothing that risks your
Kamernet account.

One-time setup (2 minutes):
  1. In Telegram, message @BotFather -> /newbot -> follow prompts.
     It gives you a TOKEN like 123456:ABC-DEF...
  2. Message your new bot once (say "hi") so it's allowed to message you.
  3. Get your chat id: open in a browser
        https://api.telegram.org/bot<TOKEN>/getUpdates
     and copy the "chat":{"id": <number> } value.
  4. Put TOKEN and chat id into the TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
     environment variables (see README).
"""

from __future__ import annotations

import logging
import os
from urllib.parse import quote
from dotenv import load_dotenv

import requests

log = logging.getLogger("kamernet.notifier")

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def notify(listing: dict, message_template: str) -> None:
    """Send a formatted alert about one matching listing."""
    if not TOKEN or not CHAT_ID:
        log.error("TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set — cannot send alert.")
        return

    rent = listing.get("rent")
    area = listing.get("area")
    prefilled = message_template.format(
        title=listing.get("title", ""),
        city=listing.get("city", ""),
    )

    # HTML-formatted message with the listing link + a copy-ready reply.
    text = (
        f"🏠 <b>New match</b>\n"
        f"<b>{_esc(listing.get('title',''))}</b>\n"
        f"{_esc(listing.get('city',''))} · "
        f"{'€'+str(int(rent)) if rent else '?'} · "
        f"{str(int(area))+'m²' if area else '?'} · "
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


# ── OPTIONAL / AT YOUR OWN RISK ──────────────────────────────────────────────
# If you later decide you want fully automatic sending on Kamernet itself,
# this is where it would go. Be aware it needs your authenticated (paid)
# session, violates Kamernet's Terms, and can get that account banned. The
# notify() approach above already lets you reply from your phone in seconds,
# which is why it's the default. Left intentionally unimplemented.
#
# def auto_send_on_kamernet(listing: dict, message: str) -> None:
#     raise NotImplementedError("See the note above before enabling this.")
