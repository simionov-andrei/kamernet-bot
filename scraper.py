"""
Scrapes Kamernet search-result pages (HTML) with cloudscraper + BeautifulSoup
and normalises each listing card into the shape the rest of the project uses:
    id, title, city, rent, area, property_type, furnished,
    available_from, available_to, description, url

Field extraction is pinned to Kamernet's actual markup:
  - card root:   <a class="… SearchResultCard_root__… " href="…/room-2380154">
  - name/city:   two <span class="… MuiTypography-subtitle1 …"> in a content row
  - rent:        <span class="… MuiTypography-h5 …">€1,503</span>
  - area/type:   <p>84 m²</p> … <p>Room</p>
  - dates:       <p>14 Jul 2026 - 13 Jul 2027</p>
The listing id and property type also come from the href
(…/room-amsterdam/…/room-2380154 → id 2380154, type "room").

There is no description on the search page, so keyword filters in config.yaml
have nothing to match here (kept for completeness only).

Set your search URL(s) in config.yaml under `search_urls`.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import cloudscraper
import yaml
from bs4 import BeautifulSoup

log = logging.getLogger("kamernet.scraper")

CONFIG_PATH = Path("config.yaml")

# The card is the <a> wrapper; each card contains several contentRow divs.
CARD_SELECTOR = 'a[class*="SearchResultCard_root"]'

_AREA_RE = re.compile(r"(\d+)\s*m[²2]")
_DATE_RANGE_RE = re.compile(
    r"(\d{1,2}\s+\w{3,}\s+\d{4})\s*-\s*(\d{1,2}\s+\w{3,}\s+\d{4})"
)
_TYPE_WORDS = {"room", "studio", "apartment", "anti-squat", "anti squat",
               "student residence"}
_FURNISH_WORDS = {"furnished", "unfurnished", "uncarpeted", "shell"}


def _load_search_urls() -> list[str]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    urls = cfg.get("search_urls") or []
    if not urls:
        raise RuntimeError("No `search_urls` configured in config.yaml.")
    return urls


def _city_from_url(url: str) -> str:
    m = re.search(r"/for-rent/[a-z]+-([a-z\-]+)", url)
    return m.group(1).replace("-", " ") if m else ""


def _digits_to_number(s: str) -> float | None:
    digits = re.sub(r"[^\d]", "", s)          # "€1,503" -> "1503"
    return float(digits) if digits else None


def _id_and_type_from_href(href: str) -> tuple[str, str]:
    """'/en/for-rent/room-amsterdam/…/room-2380154' -> ('2380154', 'room')."""
    last = href.rstrip("/").split("/")[-1]    # 'room-2380154'
    m = re.search(r"(\d+)$", last)
    listing_id = m.group(1) if m else last
    ptype = re.sub(r"-?\d+$", "", last).strip("-")   # 'room' / 'anti-squat'
    return listing_id, ptype


def _normalise(card, page_url: str) -> dict:
    href = card.get("href", "") or ""
    full_url = "https://kamernet.nl" + href if href.startswith("/") else href
    listing_id, href_type = _id_and_type_from_href(href)

    # Name (street) + city: the two subtitle1 spans, in order.
    subs = card.select('span[class*="MuiTypography-subtitle1"]')
    street = subs[0].get_text(strip=True).rstrip(",").strip() if len(subs) > 0 else ""
    city = subs[1].get_text(strip=True) if len(subs) > 1 else _city_from_url(page_url)

    # Rent: the h5 span (e.g. "€1,503").
    rent_el = card.select_one('span[class*="MuiTypography-h5"]')
    rent = _digits_to_number(rent_el.get_text()) if rent_el else None

    # Everything else lives in <p> tags: area, furnishing, type, date range.
    p_texts = [p.get_text(strip=True) for p in card.select("p")]

    area = None
    furnished = ""
    ptype_label = ""
    avail_from = avail_to = ""
    for t in p_texts:
        low = t.lower()
        if area is None:
            m = _AREA_RE.search(t)
            if m:
                area = float(m.group(1))
                continue
        if not furnished and low in _FURNISH_WORDS:
            furnished = t
            continue
        if not ptype_label and low in _TYPE_WORDS:
            ptype_label = t            # keep original case for display ("Room")
            continue
        if not avail_from:
            m = _DATE_RANGE_RE.search(t)
            if m:
                avail_from, avail_to = m.group(1), m.group(2)

    property_type = ptype_label or href_type   # fall back to href-derived type

    return {
        "id": listing_id,
        "title": street,
        "city": city,
        "rent": rent,
        "area": area,
        "property_type": property_type,
        "furnished": furnished,
        "available_from": avail_from,
        "available_to": avail_to,
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