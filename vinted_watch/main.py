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
    seeding = reseed or not store.usable
    fresh = [item for item in matches if store.is_new(item.id)]
    # Vinted returns its results in no useful order, but ids are chronological.
    fresh.sort(key=lambda item: item.id, reverse=True)

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
        batch = fresh[:max_notifications]
        if len(fresh) > len(batch):
            log.warning(
                "%s: %d new listings, notifying about the newest %d",
                watch.name,
                len(fresh),
                len(batch),
            )
        # Oldest first, so the newest listing lands on top of the phone's list.
        for item in reversed(batch):
            notifier.send(watch.name, item)
            sent += 1

    if not dry_run:
        # The mark covers every id returned, including filtered-out ones: it
        # records how far through Vinted's ids this watch has looked, not what
        # it liked.
        store.observe(item.id for item in listings)
        store.record(item.id for item in matches)
        store.save()

    return sent


def send_test(watch: Watch, client, notifier: Notifier, count: int) -> int:
    """Notify about the newest current matches, ignoring state entirely.

    Exists so "did my ntfy setup actually work" can be answered without
    waiting for a genuinely new listing or hand-editing a state file.
    """
    matches = [
        item
        for item in (Listing.from_api(entry) for entry in client.search(watch.params))
        if watch.filters.matches(item)
    ]
    matches.sort(key=lambda item: item.id, reverse=True)
    batch = matches[:count]

    log.info("%s: sending %d test notification(s)", watch.name, len(batch))
    for item in reversed(batch):
        notifier.send(watch.name, item)
    return len(batch)


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
    parser.add_argument(
        "--send-test",
        type=int,
        nargs="?",
        const=1,
        metavar="N",
        help=(
            "notify about the N newest current matches (default 1) to prove the "
            "notifier works, ignoring and preserving state"
        ),
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
            if args.send_test is not None:
                sent += send_test(watch, client, notifier, args.send_test)
                continue
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
            log.error("%s: %s", watch.name, exc)
            failed += 1

    log.info("done: %d notification(s), %d watch(es) failed", sent, failed)
    return 1 if failed == len(selected) else 0


if __name__ == "__main__":
    raise SystemExit(main())
