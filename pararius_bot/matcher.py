"""Decide whether a listing matches the user's preferences."""

from __future__ import annotations


def matches(listing: dict, prefs: dict) -> bool:
    """Return True if `listing` satisfies every configured preference in `prefs`."""
    s = prefs.get("search", {})

    # NOTE: fields scraped from HTML can occasionally be unreadable (None/"").
    # Since the search URL already filters server-side, we only REJECT when a
    # field is known and fails the check — unknown fields don't drop a listing.

    # City
    cities = [c.lower() for c in (s.get("cities") or [])]
    if cities:
        city = (listing.get("city") or "").lower()
        if city and not any(c in city for c in cities):
            return False

    # Max rent — cap depends on the listing's property type, with a fallback.
    cap = _rent_cap(listing, s)
    if cap is not None:
        rent = listing.get("rent")
        if rent is not None and rent > cap:
            return False

    # Min area
    min_area = s.get("min_area")
    if min_area is not None:
        area = listing.get("area")
        if area is not None and area < min_area:
            return False

    # Min rooms
    min_rooms = s.get("min_rooms")
    if min_rooms is not None:
        rooms = listing.get("rooms")
        if rooms is not None and rooms < min_rooms:
            return False

    # Property type
    types = [t.lower() for t in (s.get("property_types") or [])]
    if types:
        ptype = (listing.get("property_type") or "").lower()
        if ptype and not any(t in ptype for t in types):
            return False

    desc = (listing.get("description") or "").lower()

    # Exclude keywords
    for kw in (s.get("exclude_keywords") or []):
        if kw.lower() in desc:
            return False

    # Require keywords (at least one must be present, if any configured)
    required = s.get("require_keywords") or []
    if required and not any(kw.lower() in desc for kw in required):
        return False

    return True


def _rent_cap(listing: dict, search: dict):
    """Pick the rent cap for this listing's type, falling back to max_rent."""
    ptype = (listing.get("property_type") or "").lower()
    for key, cap in (search.get("max_rent_by_type") or {}).items():
        if key.lower() in ptype:
            return cap
    return search.get("max_rent")
