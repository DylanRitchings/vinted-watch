"""Per-watch record of listing IDs already notified about.

One JSON file per watch under the state dir. Writes are atomic (temp file +
rename) so a killed run cannot leave a truncated file that would re-notify the
entire search on the next tick.
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


def slugify(name: str) -> str:
    slug = _SLUG.sub("-", name.strip().casefold()).strip("-")
    return slug or "watch"


class SeenStore:
    def __init__(self, state_dir: Path, name: str, max_entries: int = 2000) -> None:
        self.path = state_dir / f"{slugify(name)}.json"
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self.existed = self.path.exists()
        if self.existed:
            self._seen = self._load()

    def _load(self) -> dict[str, float]:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            # Treat a corrupt file as "no history" rather than crashing; the
            # run below re-seeds it instead of notifying about everything.
            log.warning("unreadable state file %s (%s), reseeding", self.path, exc)
            self.existed = False
            return {}
        seen = data.get("seen", {})
        return {str(k): float(v) for k, v in seen.items()} if isinstance(seen, dict) else {}

    def is_new(self, item_id: int) -> bool:
        return str(item_id) not in self._seen

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
        tmp.write_text(json.dumps({"version": 1, "seen": self._seen}))
        os.replace(tmp, self.path)
        self.existed = True
