"""Blocklist that notifications can add to, via ntfy action buttons.

Each notification carries "Ignore" and "Block seller" buttons. ntfy's `http`
action makes the phone POST a short command back to a *control topic* on the
same ntfy server; the next poll drains that topic and folds the commands into
`blocklist.json` in the state dir.

Using ntfy as the transport keeps this a oneshot timer job: no long-running
listener, no extra port, nothing new to reach from the phone. The cost is
latency -- an ignore applies on the next poll, not instantly.

Commands are idempotent (they add to a set), so replaying them is harmless.

Anyone who can publish to the control topic can add entries to the blocklist.
On a LAN-only ntfy that is the same set of people who can already read the
notifications; set an access token on the topic if that is not true for you.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

IGNORE_ID = "ignore-id"
IGNORE_SELLER = "ignore-seller"


class Blocklist:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "blocklist.json"
        self.ids: set[int] = set()
        self.sellers: set[str] = set()
        self.since: str = "all"
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable blocklist %s (%s), starting empty", self.path, exc)
            return
        self.ids = {int(i) for i in data.get("ids", [])}
        self.sellers = {str(s) for s in data.get("sellers", [])}
        self.since = str(data.get("since", "all"))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "version": 1,
                    "since": self.since,
                    "ids": sorted(self.ids),
                    "sellers": sorted(self.sellers),
                }
            )
        )
        os.replace(tmp, self.path)

    def apply(self, command: str) -> bool:
        """Fold one control message into the blocklist. True if it changed it."""
        verb, _, argument = command.strip().partition(" ")
        # The action button percent-encodes its argument to keep the ntfy
        # header ASCII, so sellers with accents or spaces arrive intact.
        argument = urllib.parse.unquote(argument.strip())
        if not argument:
            return False
        if verb == IGNORE_ID:
            try:
                item_id = int(argument)
            except ValueError:
                log.warning("bad %s argument: %r", IGNORE_ID, argument)
                return False
            if item_id in self.ids:
                return False
            self.ids.add(item_id)
            log.info("ignoring listing %d", item_id)
            return True
        if verb == IGNORE_SELLER:
            if argument in self.sellers:
                return False
            self.sellers.add(argument)
            log.info("ignoring seller %s", argument)
            return True
        log.warning("unknown control command: %r", verb)
        return False


def drain(blocklist: Blocklist, url: str, topic: str, timeout: int = 15) -> int:
    """Read new control messages off the topic and apply them. Returns count."""
    query = urllib.parse.urlencode({"poll": "1", "since": blocklist.since})
    endpoint = f"{url.rstrip('/')}/{urllib.parse.quote(topic)}/json?{query}"

    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError) as exc:
        # An unreachable control topic must not stop the poll it precedes.
        log.error("could not read control topic %s: %s", topic, exc)
        return 0

    applied = 0
    latest = 0
    for line in body.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "message":
            continue
        latest = max(latest, int(event.get("time", 0)))
        if blocklist.apply(str(event.get("message", ""))):
            applied += 1

    if latest:
        # +1 so the message that moved the cursor is not read again.
        blocklist.since = str(latest + 1)
    if applied or latest:
        blocklist.save()
    return applied
