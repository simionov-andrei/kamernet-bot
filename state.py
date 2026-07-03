"""
Tracks which listing IDs we've already alerted on, so "new" means new.

The state is a plain JSON file (seen_ids.json). On an always-on server this
just works. On GitHub Actions the filesystem resets between runs, so the
workflow commits this file back to the repo after each run (see poll.yml).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("kamernet.state")

STATE_FILE = Path("seen_ids.json")
# Cap how many IDs we remember so the file doesn't grow forever.
MAX_REMEMBERED = 2000


def load_seen() -> set[str]:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except Exception as exc:  # noqa: BLE001
            log.warning("Couldn't read state file, starting fresh: %s", exc)
    return set()


def save_seen(seen: set[str]) -> None:
    # Keep only the most recent IDs (sets are unordered, so this is a rough cap).
    trimmed = list(seen)[-MAX_REMEMBERED:]
    STATE_FILE.write_text(json.dumps(trimmed))
