"""Entry point: one poll of every configured watch, then exit.

Scheduling is systemd's job (the NixOS module ships a timer), so this stays a
oneshot -- no daemon, no in-process sleep loop.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import Config, Watch
from .listing import Listing
from .notify import Notifier, StdoutNotifier, build as build_notifier
from .state import SeenStore
from .vinted import VintedClient, VintedError

log = logging.getLogger("vinted-watch")


def run_watch(
    watch: Watch,
    client: VintedClient,
    notifier: Notifier,
    state_dir: Path,
    max_notifications: int,
    dry_run: bool,
    reseed: bool,
) -> int:
    """Poll one watch. Returns the number of notifications sent."""
    raw_items = client.search(watch.params)
    listings = [Listing.from_api(entry) for entry in raw_items]
    matches = [item for item in listings if watch.filters.matches(item)]

    store = SeenStore(state_dir, watch.name)
    # First ever run (or an explicit reseed) records the current results
    # silently. Without this, enabling a watch dumps 40 notifications at once.
    seeding = reseed or not store.usable
    fresh = [item for item in matches if store.is_new(item.id)]

    log.info(
        "%s: %d results, %d match filters, %d above id %d%s",
        watch.name,
        len(raw_items),
        len(matches),
        len(fresh),
        store.high_water,
        " (seeding, not notifying)" if seeding else "",
    )

    sent = 0
    if not seeding and fresh:
        # The API returns newest first; send oldest first so the newest
        # listing ends up on top of the notification list.
        batch = fresh[:max_notifications]
        if len(fresh) > len(batch):
            log.warning(
                "%s: %d new listings, notifying about the newest %d",
                watch.name,
                len(fresh),
                len(batch),
            )
        for item in reversed(batch):
            notifier.send(watch.name, item)
            sent += 1

    if not dry_run:
        # The high water mark tracks every id the search returned, matching or
        # not: it is a statement about time, and ids are handed out in order.
        store.observe(item.id for item in listings)
        # Only matching items are recorded as notified. Anything filtered out
        # stays unrecorded on purpose, so a later price drop still alerts --
        # provided the listing is still above the mark.
        store.record(item.id for item in matches)
        store.save()

    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vinted-watch", description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=os.environ.get("VINTED_WATCH_CONFIG"),
        help="path to the JSON config (env: VINTED_WATCH_CONFIG)",
    )
    parser.add_argument(
        "--state-dir", type=Path, help="override the state directory from the config"
    )
    parser.add_argument(
        "--watch", action="append", help="only run this watch (repeatable)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print matches to stdout and leave state untouched",
    )
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="record current results without notifying, then exit",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    if args.config is None:
        parser.error("no config given (--config or VINTED_WATCH_CONFIG)")

    config = Config.load(Path(args.config))
    state_dir = args.state_dir or config.state_dir
    state_dir.mkdir(parents=True, exist_ok=True)

    notifier = StdoutNotifier() if args.dry_run else build_notifier(config.notifier)
    client = VintedClient(domain=config.domain, user_agent=config.user_agent)

    selected = [
        watch
        for watch in config.watches
        if watch.enabled and (not args.watch or watch.name in args.watch)
    ]
    if not selected:
        log.warning("no enabled watches to run")
        return 0

    sent = 0
    failed = 0
    for watch in selected:
        try:
            sent += run_watch(
                watch,
                client,
                notifier,
                state_dir,
                config.max_notifications,
                args.dry_run,
                args.reseed,
            )
        except VintedError as exc:
            # One broken query should not stop the others.
            log.error("%s: %s", watch.name, exc)
            failed += 1

    log.info("done: %d notification(s), %d watch(es) failed", sent, failed)
    return 1 if failed == len(selected) else 0


if __name__ == "__main__":
    raise SystemExit(main())
