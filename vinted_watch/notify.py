"""Notification sinks. ntfy is the real one; stdout exists for --dry-run."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .listing import Listing

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, watch: str, item: Listing) -> None: ...

    def send_digest(self, watch: str, items: list[Listing]) -> None: ...


def price_of(item: Listing) -> str:
    amount = f"{item.buyer_price:.2f}" if item.buyer_price is not None else "?"
    return f"{amount} {item.currency}".strip()


def describe(item: Listing) -> tuple[str, str]:
    """Title/body pair shared by every sink."""
    title = f"{price_of(item)} — {item.title}".strip()
    details = [part for part in (item.brand, item.size, item.condition) if part]
    if item.price is not None and item.buyer_price is not None and item.price != item.buyer_price:
        details.append(f"item {item.price:.2f} + fees")
    if item.seller:
        details.append(f"by {item.seller}")
    return title, " · ".join(details) or item.url


def describe_digest(watch: str, items: list[Listing]) -> tuple[str, str]:
    """One notification covering several listings.

    ntfy allows a single click target per message, so each listing carries its
    own URL inline instead; the app makes those tappable.
    """
    title = f"{watch}: {len(items)} new listings"
    lines = [f"{price_of(item)} — {item.title}\n{item.url}" for item in items]
    return title, "\n\n".join(lines)


class StdoutNotifier:
    def send(self, watch: str, item: Listing) -> None:
        title, body = describe(item)
        print(f"[{watch}] {title}\n    {body}\n    {item.url}", flush=True)

    def send_digest(self, watch: str, items: list[Listing]) -> None:
        title, body = describe_digest(watch, items)
        print(f"[{title}]\n{body}\n", flush=True)


class NtfyNotifier:
    def __init__(
        self,
        url: str,
        topic: str,
        priority: str = "default",
        tags: str = "shopping_cart",
        token_file: str | None = None,
        timeout: int = 15,
    ) -> None:
        self.endpoint = f"{url.rstrip('/')}/{topic}"
        self.priority = priority
        self.tags = tags
        self.timeout = timeout
        self.token = Path(token_file).read_text().strip() if token_file else None

    def send(self, watch: str, item: Listing) -> None:
        title, body = describe(item)
        headers = {"Click": item.url}
        if item.photo:
            headers["Attach"] = item.photo
        self._post(f"{watch}: {title}", f"{body}\n{item.url}", headers, item.id)

    def send_digest(self, watch: str, items: list[Listing]) -> None:
        title, body = describe_digest(watch, items)
        self._post(title, body, {}, f"digest of {len(items)}")

    def _post(self, title: str, body: str, extra: dict[str, str], what: object) -> None:
        headers = {
            "Title": _header_safe(title),
            "Priority": self.priority,
            "Tags": self.tags,
            "Content-Type": "text/plain; charset=utf-8",
            **extra,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(
            self.endpoint, data=body.encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            # Swallowed deliberately: the caller still records the listing, so
            # a dead ntfy costs this one alert rather than replaying the whole
            # backlog once it comes back.
            log.error("ntfy delivery failed for %s: %s", what, exc)


def _header_safe(value: str) -> str:
    """ntfy reads headers as latin-1; strip anything that cannot survive it."""
    return json.dumps(value, ensure_ascii=True)[1:-1]


def build(config: dict) -> Notifier:
    kind = config.get("type", "ntfy")
    if kind == "stdout":
        return StdoutNotifier()
    if kind == "ntfy":
        return NtfyNotifier(
            url=config["url"],
            topic=config["topic"],
            priority=config.get("priority", "default"),
            tags=config.get("tags", "shopping_cart"),
            token_file=config.get("tokenFile") or config.get("token_file"),
        )
    raise ValueError(f"unknown notifier type: {kind!r}")
