"""Minimal Vinted catalog API client.

Vinted has no public API. The web app talks to /api/v2/catalog/items with the
anonymous session cookie the front page hands out, so we do the same: fetch the
front page once to collect cookies, then reuse that opener for search calls.

Stdlib only, deliberately -- this runs as a short-lived systemd oneshot and a
zero-dependency closure keeps the NixOS module cheap to build.
"""

from __future__ import annotations

import gzip
import http.cookiejar
import json
import logging
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
        self._get(f"https://{self.domain}/", accept_json=False)
        if not len(jar):
            raise VintedError(f"no session cookie returned by https://{self.domain}/")
        log.debug("session established, %d cookies", len(jar))
        return opener

    def _ensure_session(self) -> urllib.request.OpenerDirector:
        if self._opener is None:
            return self._new_opener()
        return self._opener

    def _get(self, url: str, accept_json: bool = True) -> bytes:
        headers = {
            "User-Agent": self.user_agent,
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept-Encoding": "gzip",
            "Accept": (
                "application/json, text/plain, */*"
                if accept_json
                else "text/html,application/xhtml+xml"
            ),
        }
        if accept_json:
            headers["Referer"] = f"https://{self.domain}/"
            headers["X-Requested-With"] = "XMLHttpRequest"

        assert self._opener is not None
        request = urllib.request.Request(url, headers=headers)
        with self._opener.open(request, timeout=self.timeout) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return body

    def _get_json(self, url: str) -> dict[str, Any]:
        """GET with retry/backoff and one session refresh on an auth failure."""
        last: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                self._ensure_session()
                return json.loads(self._get(url))
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
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                log.warning("request failed (attempt %d): %s", attempt, exc)

            if attempt < self.retries:
                time.sleep(2**attempt)

        raise VintedError(f"giving up on {url} after {self.retries} attempts: {last}")

    def search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Return raw catalog items for a search, newest first."""
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v not in (None, "", [])}, doseq=True
        )
        url = f"https://{self.domain}/api/v2/catalog/items?{query}"
        log.debug("GET %s", url)
        payload = self._get_json(url)
        items = payload.get("items")
        if not isinstance(items, list):
            raise VintedError(f"unexpected response shape for {url}")
        return items
