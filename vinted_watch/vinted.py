"""Minimal Vinted catalog client.

Vinted has no public API. /api/v2/catalog/items -- what the web app used to
call, and what this read until it started 404ing on every query -- is gone;
the rest of /api/v2 still answers, that one route does not. Search results are
now server-rendered into the /catalog page, so we fetch the page a browser
would and read the listings out of the React payload embedded in it.

Stdlib only, deliberately -- this runs as a short-lived systemd oneshot and a
zero-dependency closure keeps the NixOS module cheap to build.
"""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger(__name__)

# Vinted 403s obvious bot agents. A stock desktop Chrome string is what the
# real web app sends, and it is what the cookie handshake is validated against.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# The session cookie expires; on a 401/403 we re-handshake once rather than
# failing the whole run.
_AUTH_FAILURES = (401, 403)

# The page ships its data as React flight chunks: a run of
# self.__next_f.push([1,"<json string>"]) calls whose decoded strings
# concatenate into one payload. A listing's JSON straddles chunk boundaries,
# so the whole thing has to be reassembled before anything can be read out.
_FLIGHT_CHUNK = re.compile(
    r'self\.__next_f\.push\(\[1,(".*?")\]\)</script>', re.DOTALL
)
_ITEMS_KEY = '"items":{"items":'


class VintedError(RuntimeError):
    pass


class VintedClient:
    def __init__(
        self,
        domain: str = "www.vinted.co.uk",
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        self.domain = domain
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self._opener: urllib.request.OpenerDirector | None = None

    def _new_opener(self) -> urllib.request.OpenerDirector:
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        opener.addheaders = []
        self._opener = opener
        self._get(f"https://{self.domain}/")
        if not len(jar):
            raise VintedError(f"no session cookie returned by https://{self.domain}/")
        log.debug("session established, %d cookies", len(jar))
        return opener

    def _ensure_session(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            return self._new_opener()
        return self._opener

    def _get(self, url: str) -> bytes:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip",
            "Accept": "text/html,application/xhtml+xml",
        }

        assert self._opener is not None
        request = urllib.request.Request(url, headers=headers)
        with self._opener.open(request, timeout=self.timeout) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body

    def _get_items(self, url: str) -> list[dict[str, Any]]:
        """GET with retry/backoff and one session refresh on an auth failure.

        Parsing happens inside the retry loop: a bot-challenge page comes back
        as a perfectly good HTTP 200 with no listings in it, and that is worth
        another go.
        """
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                self._ensure_session()
                return _extract_items(self._get(url).decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in _AUTH_FAILURES:
                    log.warning("HTTP %s from Vinted, refreshing session", exc.code)
                    self._opener = None
                elif exc.code == 429:
                    log.warning("rate limited by Vinted (attempt %d)", attempt)
                elif 400 <= exc.code < 500:
                    # A genuine client error will not fix itself on retry.
                    raise VintedError(f"HTTP {exc.code} for {url}") from exc
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                VintedError,
            ) as exc:
                last = exc
                log.warning("request failed (attempt %d): %s", attempt, exc)

            if attempt < self.retries:
                time.sleep(2**attempt)

        raise VintedError(f"giving up on {url} after {self.retries} attempts: {last}")

    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return raw catalog items for a search, newest first."""
        query = urllib.parse.urlencode(_web_params(params), doseq=True)
        url = f"https://{self.domain}/catalog?{query}"
        log.debug("GET %s", url)
        items = self._get_items(url)
        for item in items:
            # The page links listings relative to the site root; everything
            # downstream (notification click targets, --dry-run output) wants
            # something openable.
            path = str(item.get("url") or "")
            if path.startswith("/"):
                item["url"] = f"https://{self.domain}{path}"
        return items


def _web_params(params: dict[str, Any]) -> dict[str, Any]:
    """Translate API-style search params into the ones the web catalog takes.

    Most names survived the move; the list filters grew a [] suffix, and the
    page always returns Vinted's maximum 96 results, so per_page is dropped.
    """
    web: dict[str, Any] = {}
    for key, value in params.items():
        if value in (None, "", []) or key == "per_page":
            continue
        if isinstance(value, (list, tuple)):
            web["catalog[]" if key == "catalog_ids" else f"{key}[]"] = list(value)
        else:
            web[key] = value
    return web


def _extract_items(html: str) -> list[dict[str, Any]]:
    """Pull the catalog's listing objects out of an embedded flight payload."""
    try:
        flight = "".join(json.loads(chunk) for chunk in _FLIGHT_CHUNK.findall(html))
    except json.JSONDecodeError as exc:
        raise VintedError(f"unreadable page payload: {exc}") from exc

    start = flight.find(_ITEMS_KEY)
    if start < 0:
        raise VintedError("no catalog items in page payload")
    entries, _ = json.JSONDecoder().raw_decode(flight, start + len(_ITEMS_KEY))
    return [entry["productItem"] for entry in entries if "productItem" in entry]
