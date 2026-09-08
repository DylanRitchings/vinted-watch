"""Normalised listing + the client-side filters applied on top of the search."""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass(frozen=True)
class Listing:
    id: int
    title: str
    url: str
    brand: str
    seller: str
    size: str
    condition: str
    price: float | None
    total_price: float | None
    currency: str
    photo: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Listing":
        price = raw.get("price") or {}
        total = raw.get("total_item_price") or {}
        photo = (raw.get("photo") or {}).get("url")
        if not photo:
            photos = raw.get("photos") or []
            photo = photos[0].get("url") if photos else None
        return cls(
            id=int(raw["id"]),
            title=str(raw.get("title") or "").strip(),
            url=str(raw.get("url") or ""),
            brand=str(raw.get("brand_title") or ""),
            seller=str((raw.get("user") or {}).get("login") or ""),
            size=str(raw.get("size_title") or ""),
            condition=str(raw.get("status") or ""),
            price=_as_float(price.get("amount")),
            total_price=_as_float(total.get("amount")),
            currency=str(price.get("currency_code") or total.get("currency_code") or ""),
            photo=photo,
        )

    @property
    def buyer_price(self) -> float | None:
        """Price the buyer actually pays -- item price plus Vinted's fee.

        Filtering on the bare item price is misleading: a "£20" listing costs
        more at checkout, so max_price compares against this by default.
        """
        return self.total_price if self.total_price is not None else self.price


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclasses.dataclass(frozen=True)
class Filters:
    """Post-fetch filters. Vinted's own params are coarse, so we re-check here."""

    min_price: float | None = None
    max_price: float | None = None
    price_includes_fees: bool = True
    title_all: tuple[str, ...] = ()
    title_include: tuple[str, ...] = ()
    title_exclude: tuple[str, ...] = ()
    brands: tuple[str, ...] = ()
    sizes: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    ignore_ids: frozenset[int] = frozenset()
    ignore_sellers: tuple[str, ...] = ()

    def matches(self, item: Listing) -> bool:
        if item.id in self.ignore_ids:
            return False
        if any(seller.casefold() == item.seller.casefold() for seller in self.ignore_sellers):
            return False

        price = item.buyer_price if self.price_includes_fees else item.price
        if self.min_price is not None and (price is None or price < self.min_price):
            return False
        if self.max_price is not None and (price is None or price > self.max_price):
            return False

        haystack = f"{item.title} {item.brand}".casefold()
        if not all(term.casefold() in haystack for term in self.title_all):
            return False
        if self.title_include and not any(
            term.casefold() in haystack for term in self.title_include
        ):
            return False
        if any(term.casefold() in haystack for term in self.title_exclude):
            return False

        if not _matches_any(self.brands, item.brand):
            return False
        if not _matches_any(self.sizes, item.size):
            return False
        if not _matches_any(self.conditions, item.condition):
            return False
        return True


def _matches_any(allowed: tuple[str, ...], value: str) -> bool:
    """Empty allowlist means "no constraint"."""
    if not allowed:
        return True
    folded = value.casefold()
    return any(entry.casefold() == folded for entry in allowed)
