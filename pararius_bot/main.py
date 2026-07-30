"""
Entry point. Two modes:

  python -m pararius_bot.main once     # one poll cycle, then exit  (GitHub Actions)
  python -m pararius_bot.main loop     # poll forever                (always-on server)
  python -m pararius_bot.main mock     # test the pipeline with fake data, no network
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import yaml

from . import matcher, notifier, scraper, state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pararius.main")

CONFIG_PATH = Path("pararius_config.yaml")


def load_config() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text())


def run_once(prefs: dict, listings: list[dict] | None = None) -> int:
    """Fetch, filter, alert on new matches, persist state. Returns #alerts sent."""
    seen = state.load_seen()
    if listings is None:
        listings = scraper.fetch_with_retries()

    template = prefs.get("message", {}).get("template", "Hi, I'm interested!")
    sent = 0
    new_seen = set(seen)

    for listing in listings:
        lid = listing["id"]
        if lid in seen:
            continue
        new_seen.add(lid)          # mark seen regardless, so we don't re-check
        if matcher.matches(listing, prefs):
            notifier.notify(listing, template)
            sent += 1

    state.save_seen(new_seen)
    log.info("Cycle done: %d listings, %d new alerts", len(listings), sent)
    return sent


def run_loop(prefs: dict) -> None:
    interval = int(prefs.get("poll_interval_seconds", 60))
    log.info("Starting loop, polling every %ds. Ctrl+C to stop.", interval)
    while True:
        try:
            run_once(prefs)
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            log.error("Cycle failed, will retry next interval: %s", exc)
        time.sleep(interval)


def _mock_listings() -> list[dict]:
    return [
        {"id": "/apartment-for-rent/amsterdam/mock-1/mock-street", "title": "Bright apartment near center",
         "city": "Amsterdam", "rent": 1400.0, "area": 55.0, "rooms": 2, "property_type": "apartment",
         "furnished": "Furnished", "description": "Available now, working professionals welcome.",
         "url": "https://www.pararius.com/apartment-for-rent/amsterdam/mock-1/mock-street"},
        {"id": "/room-for-rent/amsterdam/mock-2/mock-room", "title": "Room in shared house",
         "city": "Amsterdam", "rent": 700.0, "area": 14.0, "rooms": 1, "property_type": "room",
         "furnished": "Furnished", "description": "No students please.",
         "url": "https://www.pararius.com/room-for-rent/amsterdam/mock-2/mock-room"},
        {"id": "/apartment-for-rent/amsterdam/mock-3/mock-penthouse", "title": "Expensive penthouse",
         "city": "Amsterdam", "rent": 2600.0, "area": 90.0, "rooms": 4, "property_type": "apartment",
         "furnished": "Furnished", "description": "Luxury living.",
         "url": "https://www.pararius.com/apartment-for-rent/amsterdam/mock-3/mock-penthouse"},
    ]


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    prefs = load_config()

    if mode == "loop":
        run_loop(prefs)
    elif mode == "mock":
        # mock-1 should match the default config; the others should be filtered out.
        run_once(prefs, listings=_mock_listings())
    else:  # "once"
        run_once(prefs)


if __name__ == "__main__":
    main()
