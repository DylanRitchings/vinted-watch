"""Per-watch record of what has already been notified about.

One JSON file per watch under the state dir. Writes are atomic (temp file +
rename) so a killed run cannot leave a truncated file that would re-notify the
entire search on the next tick.

Two things are tracked, because a seen-set alone is not enough:

* **seen** — ids already notified about.
* **high water** — the largest listing id ever *observed*, matching or not.

Vinted's catalog endpoint ignores the `order` parameter and answers each
request with a different sample of the (fuzzily matched) result pool, so two
polls seconds apart share only about half their ids. A seen-set treats every
unsampled-until-now listing as new, which means a permanent trickle of
notifications about listings that are often months old. Vinted ids are
allocated in ascending order, so anything genuinely new is above the high water
mark and everything churning below it can be ignored.

The mark only advances when a larger id is actually observed, so a new listing
that the sample misses stays notifiable across later polls rather than being
lost.
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
        # `usable` is False for a first run, a corrupt file, or a file written
        # before the high water mark existed. In all three cases the caller
        # seeds instead of notifying.
        self.usable = False
        if self.path.exists():
            self.usable = self._load()

    def _load(self) -> bool:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            # Treat a corrupt file as "no history" rather than crashing; the
            # run below re-seeds it instead of notifying about everything.
            log.warning("unreadable state file %s (%s), reseeding", self.path, exc)
            return False

        seen = data.get("seen", {})
        if isinstance(seen, dict):
            self._seen = {str(k): float(v) for k, v in seen.items()}

        high_water = data.get("high_water")
        if not isinstance(high_water, int) or high_water <= 0:
            # A v1 file has no mark. Adopting one from this poll's sample and
            # notifying in the same run would fire off the whole churn backlog,
            # so treat the file as needing a reseed.
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
