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


def describe(item: Listing) -> tuple[str, str]:
    """Title/body pair shared by every sink."""
    price = f"{item.buyer_price:.2f}" if item.buyer_price is not None else "?"
    title = f"{price} {item.currency} — {item.title}".strip()
    details = [part for part in (item.brand, item.size, item.condition) if part]
    if item.price is not None and item.buyer_price is not None and item.price != item.buyer_price:
        details.append(f"item {item.price:.2f} + fees")
    return title, " · ".join(details) or item.url


class StdoutNotifier:
    def send(self, watch: str, item: Listing) -> None:
        title, body = describe(item)
        print(f"[{watch}] {title}\n    {body}\n    {item.url}", flush=True)


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
        headers = {
            "Title": _header_safe(f"{watch}: {title}"),
            "Priority": self.priority,
            "Tags": self.tags,
            # Tapping the notification opens the listing directly.
            "Click": item.url,
            "Content-Type": "text/plain; charset=utf-8",
        }
        if item.photo:
            headers["Attach"] = item.photo
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(
            self.endpoint,
            data=f"{body}\n{item.url}".encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            # A dead notifier must not abort the run -- the item is still
            # recorded as seen, matching the "only alert once" contract.
            log.error("ntfy delivery failed for item %s: %s", item.id, exc)


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
