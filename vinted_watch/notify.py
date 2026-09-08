"""Notification sinks. ntfy is the real one; stdout exists for --dry-run."""

from __future__ import annotations

import base64
import logging
import urllib.error
import urllib.parse
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
        control_topic: str | None = None,
    ) -> None:
        self.base = url.rstrip("/")
        self.endpoint = f"{self.base}/{topic}"
        self.control_endpoint = f"{self.base}/{control_topic}" if control_topic else None
        self.priority = priority
        self.tags = tags
        self.timeout = timeout
        self.token = Path(token_file).read_text().strip() if token_file else None

    def send(self, watch: str, item: Listing) -> None:
        title, body = describe(item)
        headers = {"Click": item.url}
        if item.photo:
            headers["Attach"] = item.photo
        actions = self._actions(item)
        if actions:
            headers["Actions"] = actions
        self._post(f"{watch}: {title}", f"{body}\n{item.url}", headers, item.id)

    def _actions(self, item: Listing) -> str:
        """ntfy action buttons that publish a command to the control topic."""
        if not self.control_endpoint:
            return ""
        actions = [
            _http_action("Ignore", self.control_endpoint, "ignore-id", str(item.id))
        ]
        if item.seller:
            actions.append(
                _http_action(
                    "Block seller", self.control_endpoint, "ignore-seller", item.seller
                )
            )
        return "; ".join(actions)

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


def _http_action(label: str, url: str, verb: str, argument: str) -> str:
    # ntfy parses actions as comma-separated key=value, so the body is quoted
    # to protect its space and the argument percent-encoded to keep the whole
    # header ASCII. clear=true dismisses the notification once tapped.
    return (
        f"http, {label}, {url}, method=POST, "
        f"body='{verb} {urllib.parse.quote(argument)}', clear=true"
    )


def _header_safe(value: str) -> str:
    """Encode a header value ntfy will render correctly.

    ntfy reads headers as latin-1. Passing non-ASCII through unchanged shows
    up as mojibake or escape sequences, so anything outside ASCII goes as an
    RFC 2047 encoded word, which ntfy decodes back to UTF-8.
    """
    if value.isascii():
        return value
    return "=?UTF-8?B?" + base64.b64encode(value.encode()).decode("ascii") + "?="


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
            control_topic=config.get("controlTopic") or config.get("control_topic"),
        )
    raise ValueError(f"unknown notifier type: {kind!r}")
