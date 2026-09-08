"""Per-watch record of what has already been notified about.

Tracks a seen-set *and* a high water mark (the largest listing id ever
observed), because a seen-set alone does not work here: Vinted answers each
request with a different sample of the matched pool, so two polls seconds apart
share only about half their ids and every unsampled-until-now listing looks
new. Ids are allocated in ascending order, so the mark separates genuinely new
listings from the churn below it. See the README for the measurements.

The mark only advances when a larger id is actually observed, so a new listing
that one sample misses stays notifiable on later polls.

Writes are atomic (temp file + rename); a killed run cannot leave a truncated
file that would re-notify the entire search.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

_SLUG = re.compile(r"[^a-z0-9_-]+")

STATE_VERSION = 2


def slugify(name: str) -> str:
    slug = _SLUG.sub("-", name.strip().casefold()).strip("-")
    return slug or "watch"


class SeenStore:
    def __init__(self, state_dir: Path, name: str, max_entries: int = 2000) -> None:
        self.path = state_dir / f"{slugify(name)}.json"
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._high_water = 0
        # False for a first run, a corrupt file, or a pre-high-water file —
        # the caller seeds instead of notifying in all three cases.
        self.usable = False
        if self.path.exists():
            self.usable = self._load()

    def _load(self) -> bool:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable state file %s (%s), reseeding", self.path, exc)
            return False

        seen = data.get("seen", {})
        if isinstance(seen, dict):
            self._seen = {str(k): float(v) for k, v in seen.items()}

        high_water = data.get("high_water")
        if not isinstance(high_water, int) or high_water <= 0:
            # Adopting a mark from this poll's sample and notifying in the same
            # run would fire the whole churn backlog, so a v1 file reseeds.
            log.info("%s predates the high water mark, reseeding", self.path)
            return False

        self._high_water = high_water
        return True

    @property
    def high_water(self) -> int:
        return self._high_water

    def is_new(self, item_id: int) -> bool:
        """True if this listing is unnotified *and* newer than everything seen."""
        return item_id > self._high_water and str(item_id) not in self._seen

    def observe(self, item_ids: Iterable[int]) -> None:
        """Note that these ids exist, without marking them as notified."""
        for item_id in item_ids:
            self._high_water = max(self._high_water, item_id)

    def record(self, item_ids: Iterable[int]) -> None:
        now = time.time()
        for item_id in item_ids:
            self._seen[str(item_id)] = now

    def save(self) -> None:
        if len(self._seen) > self.max_entries:
            newest = sorted(self._seen.items(), key=lambda kv: kv[1], reverse=True)
            self._seen = dict(newest[: self.max_entries])

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": STATE_VERSION,
                    "high_water": self._high_water,
                    "seen": self._seen,
                }
            )
        )
        os.replace(tmp, self.path)
        self.usable = True
