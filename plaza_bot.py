import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright


LISTINGS_URL = (
    "https://plaza.newnewnew.space/en/availables-places/living-place"
    "#?gesorteerd-op=zoekprofiel&locatie=Amsterdam-Nederland%2B-%2BNoord-Holland"
)

CARD_SELECTOR = "div[id^='object-tile-']"
LINK_SELECTOR = "a[href*='/en/availables-places/living-place/details/']"
TITLE_SELECTOR = None   # use link text or parse address separately

NTFY_TOPIC = "OurDomain_Studio_andreisimi7742"     
STATE_FILE = Path(__file__).with_name("plaza_seen_listings.json")
CHECK_INTERVAL_SECONDS = 3         
WAIT_AFTER_LOAD_MS = 4000            # extra wait for the JS-rendered list to settle


def send_notification(title: str, url: str, timestamp: str):
    message = f"{title}\nTime: {timestamp}\n{url}"
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "New Plaza listing!",
            "Priority": "high",
            "Tags": "house,white_check_mark",
        },
    )


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def fetch_listings(page, debug: bool = False):
    """Load the page in a real browser and return list of (id_url, title)."""
    page.goto(LISTINGS_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

    if debug:
        Path("rendered_page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path="rendered_page.png", full_page=True)
        print("Saved rendered_page.html and rendered_page.png for inspection.")

    cards = page.query_selector_all(CARD_SELECTOR)
    listings = []

    for card in cards:
        link_el = card.query_selector(LINK_SELECTOR)
        href = link_el.get_attribute("href") if link_el else None
        if not href:
            continue
        if href.startswith("/"):
            href = "https://plaza.newnewnew.space" + href

        if TITLE_SELECTOR:
            title_el = card.query_selector(TITLE_SELECTOR)
            title = title_el.inner_text().strip() if title_el else href
        else:
            title = (link_el.inner_text().strip() if link_el else href) or href

        listings.append((href, title))

    return listings


def run_once(page, seen: set, debug: bool = False):
    listings = fetch_listings(page, debug=debug)

    if debug:
        print(f"Found {len(listings)} card(s) with selector '{CARD_SELECTOR}'")
        for href, title in listings:
            print("  -", title, "->", href)
        return seen  # don't notify in debug mode

    current_ids = {href for href, _ in listings}
    new_ids = current_ids - seen

    if new_ids:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for href, title in listings:
            if href in new_ids:
                print("NEW LISTING:", title, href)
                send_notification(title, href, now)

    # Keep the full current set as "seen" so listings that disappear
    # and reappear later still count as new again only if truly gone
    # and re-added 
    seen = current_ids
    save_seen(seen)
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run once, dump rendered HTML/screenshot and found cards, then exit (no notifications).",
    )
    args = parser.parse_args()

    seen = load_seen()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()

        if args.debug:
            run_once(page, seen, debug=True)
            browser.close()
            return

        while True:
            try:
                print("Checking:", LISTINGS_URL)
                seen = run_once(page, seen, debug=False)
            except Exception as e:
                print("Failed to check listings:", e)

            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()