"""
Scrapes Pararius search-result pages (HTML) with cloudscraper + BeautifulSoup
and normalises each listing card into the shape the rest of the project uses:
    id, title, city, rent, area, property_type, furnished,
    available_from, available_to, description, url

Field extraction targets Pararius's known markup (BEM-style class names):
  - card root:     <section class="listing-search-item listing-search-item--for-rent …">
  - title/link:    <a class="listing-search-item__link listing-search-item__link--title"
                       href="/apartment-for-rent/amsterdam/<id>/<street-slug>">Street name</a>
  - location:      <div class="listing-search-item__sub-title'">1015 AB Amsterdam</div>
  - price:         <div class="listing-search-item__price">€ 1,750 per month</div>
  - features list: <li class="illustrated-features__item illustrated-features__item--surface-area">75 m²</li>
                    <li class="illustrated-features__item illustrated-features__item--number-of-rooms">3 rooms</li>
                    <li class="illustrated-features__item illustrated-features__item--interior">Furnished</li>

NOTE: this sandbox couldn't reach pararius.com directly (network + Cloudflare
both blocked the fetch used to double-check markup), so the selectors above are
based on Pararius's long-standing, publicly documented site structure rather
than a live inspection. Every selector uses a `class*=` partial match plus a
regex fallback over the card's raw text, so small class-name drift (hashes,
renamed modifiers) shouldn't break extraction — but if Pararius has since
redesigned the search page, re-inspect a card in devtools and adjust
CARD_SELECTOR / the `[class*=…]` lookups below.

There is no full description on the search page, so keyword filters in
config.yaml have nothing to match here (kept for completeness only).

Set your search URL(s) in pararius_config.yaml under `search_urls`.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import cloudscraper
import yaml
from bs4 import BeautifulSoup

log = logging.getLogger("pararius.scraper")

CONFIG_PATH = Path("pararius_config.yaml")
BASE_URL = "https://www.pararius.com"

# The card is a <section>; partial match so BEM modifier classes don't matter.
CARD_SELECTOR = 'section[class*="listing-search-item"]'

_AREA_RE = re.compile(r"(\d+)\s*m[²2]")
_ROOMS_RE = re.compile(r"(\d+)\s*room")
_PRICE_RE = re.compile(r"€\s*([\d.,]+)")
_DATE_RE = re.compile(r"(\d{1,2}[-/]\d{1,2}[-/]\d{4})")
_TYPE_RE = re.compile(r"^/([a-z]+)-for-rent/")
_FURNISH_WORDS = {"furnished", "upholstered", "shell"}


def _load_search_urls() -> list[str]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    urls = cfg.get("search_urls") or []
    if not urls:
        raise RuntimeError("No `search_urls` configured in pararius_config.yaml.")
    return urls


def _city_from_url(url: str) -> str:
    m = re.search(r"/apartments/([a-z\-]+)", url)
    return m.group(1).replace("-", " ") if m else ""


def _digits_to_number(s: str) -> float | None:
    # "€ 1,750" / "€1.750" -> 1750  (Pararius uses a thousands separator, no decimals)
    digits = re.sub(r"[^\d]", "", s)
    return float(digits) if digits else None


def _property_type_from_href(href: str) -> str:
    m = _TYPE_RE.match(href)
    return m.group(1) if m else ""


def _normalise(card, page_url: str) -> dict:
    link = card.select_one('a[class*="listing-search-item__link--title"]')
    if link is None:
        link = card.select_one('a[href*="-for-rent/"]')

    href = (link.get("href", "") if link else "") or ""
    full_url = BASE_URL + href if href.startswith("/") else href
    title = link.get_text(strip=True) if link else ""

    # The href path is unique and stable per listing, so use it as the id
    # rather than guessing at the exact shape of Pararius's internal hash.
    listing_id = href.strip("/")
    property_type = _property_type_from_href(href)

    sub_title_el = card.select_one('div[class*="listing-search-item__sub-title"]')
    location = sub_title_el.get_text(strip=True) if sub_title_el else ""
    city = location or _city_from_url(page_url)

    price_el = card.select_one('div[class*="listing-search-item__price"]')
    rent = _digits_to_number(price_el.get_text()) if price_el else None

    area_el = card.select_one('li[class*="illustrated-features__item--surface-area"]')
    rooms_el = card.select_one('li[class*="illustrated-features__item--number-of-rooms"]')
    interior_el = card.select_one('li[class*="illustrated-features__item--interior"]')

    card_text = card.get_text(" ", strip=True)

    area = None
    if area_el is not None:
        m = _AREA_RE.search(area_el.get_text())
        area = float(m.group(1)) if m else None
    if area is None:
        m = _AREA_RE.search(card_text)
        area = float(m.group(1)) if m else None

    rooms = None
    if rooms_el is not None:
        m = _ROOMS_RE.search(rooms_el.get_text())
        rooms = int(m.group(1)) if m else None
    if rooms is None:
        m = _ROOMS_RE.search(card_text)
        rooms = int(m.group(1)) if m else None

    furnished = ""
    if interior_el is not None:
        furnished = interior_el.get_text(strip=True)
    else:
        for word in _FURNISH_WORDS:
            if word in card_text.lower():
                furnished = word
                break

    if rent is None:
        m = _PRICE_RE.search(card_text)
        rent = _digits_to_number(m.group(1)) if m else None

    avail_match = _DATE_RE.search(card_text)
    available_from = avail_match.group(1) if avail_match else ""

    return {
        "id": listing_id,
        "title": title,
        "city": city,
        "rent": rent,
        "area": area,
        "rooms": rooms,
        "property_type": property_type,
        "furnished": furnished,
        "available_from": available_from,
        "available_to": "",
        "description": "",             # not present on the search page
        "url": full_url or page_url,
    }


def fetch_listings() -> list[dict]:
    """Fetch every configured search URL and return normalised, de-duped cards."""
    scraper = cloudscraper.create_scraper()
    listings: list[dict] = []
    seen_ids: set[str] = set()

    for url in _load_search_urls():
        resp = scraper.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.select(CARD_SELECTOR)
        log.info("Fetched %d cards from %s", len(cards), _city_from_url(url) or url)

        for card in cards:
            try:
                item = _normalise(card, url)
            except Exception as exc:  # noqa: BLE001 - one bad card shouldn't kill the run
                log.warning("Skipped a card I couldn't parse: %s", exc)
                continue
            if not item["id"] or item["id"] in seen_ids:
                continue
            seen_ids.add(item["id"])
            listings.append(item)

    return listings


def fetch_with_retries(retries: int = 3, backoff: float = 3.0) -> list[dict]:
    """fetch_listings with simple retry/backoff so a blip doesn't kill a run."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return fetch_listings()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            log.warning("Fetch attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise last_exc  # type: ignore[misc]
