"""Config file parsing.

The NixOS module writes this file into the store from the module options, so
keys are camelCase. snake_case is accepted too for hand-written configs.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

from .listing import Filters
from .vinted import DEFAULT_USER_AGENT

_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _get(source: dict[str, Any], key: str, default: Any = None) -> Any:
    """Look up a camelCase key, falling back to its snake_case spelling."""
    if key in source:
        return source[key]
    return source.get(_CAMEL.sub("_", key).lower(), default)


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


@dataclasses.dataclass(frozen=True)
class Watch:
    name: str
    params: dict[str, Any]
    filters: Filters
    enabled: bool = True


@dataclasses.dataclass(frozen=True)
class Config:
    domain: str
    user_agent: str
    state_dir: Path
    max_notifications: int
    notifier: dict[str, Any]
    watches: tuple[Watch, ...]

    @classmethod
    def load(cls, path: Path) -> "Config":
        raw = json.loads(path.read_text())
        watches = _get(raw, "watches", {}) or {}
        if isinstance(watches, list):
            watches = {entry["name"]: entry for entry in watches}

        return cls(
            domain=_get(raw, "domain", "www.vinted.co.uk"),
            user_agent=_get(raw, "userAgent") or DEFAULT_USER_AGENT,
            state_dir=Path(_get(raw, "stateDir", "/var/lib/vinted-watch")),
            max_notifications=int(_get(raw, "maxNotificationsPerRun", 10)),
            notifier=_get(raw, "notifier", {"type": "stdout"}),
            watches=tuple(
                _parse_watch(name, spec) for name, spec in sorted(watches.items())
            ),
        )


def _parse_watch(name: str, spec: dict[str, Any]) -> Watch:
    # Price bounds are sent to Vinted *and* re-checked locally: the API filters
    # on item price, but we usually care about the fee-inclusive total.
    params: dict[str, Any] = {
        "search_text": _get(spec, "query") or name,
        "order": _get(spec, "order", "newest_first"),
        "per_page": _get(spec, "perPage", 96),
        "price_from": _get(spec, "minPrice"),
        "price_to": _get(spec, "maxPrice"),
        "currency": _get(spec, "currency"),
        "catalog_ids": _get(spec, "catalogIds"),
        "brand_ids": _get(spec, "brandIds"),
        "size_ids": _get(spec, "sizeIds"),
        "status_ids": _get(spec, "statusIds"),
    }
    params.update(_get(spec, "extraParams", {}) or {})

    filters = Filters(
        min_price=_maybe_float(_get(spec, "minPrice")),
        max_price=_maybe_float(_get(spec, "maxPrice")),
        price_includes_fees=bool(_get(spec, "priceIncludesFees", True)),
        title_include=_strings(_get(spec, "titleInclude")),
        title_exclude=_strings(_get(spec, "titleExclude")),
        brands=_strings(_get(spec, "brands")),
        sizes=_strings(_get(spec, "sizes")),
        conditions=_strings(_get(spec, "conditions")),
    )
    return Watch(
        name=name,
        params=params,
        filters=filters,
        enabled=bool(_get(spec, "enable", True)),
    )


def _maybe_float(value: Any) -> float | None:
    return None if value is None else float(value)
