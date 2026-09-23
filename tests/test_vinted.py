import json

import pytest

from vinted_watch.vinted import VintedClient, VintedError, _extract_items, _web_params

PAYLOAD = (
    '{"catalogs":[],"items":{"items":['
    '{"productItem":{"id":1,"url":"/items/1-navy-throw"}},'
    '{"productItem":{"id":2,"url":"/items/2-blue-throw"}},'
    '{"promotion":{"id":3}}'
    ']},"pagination":{"total_entries":960}}'
)


def page(payload):
    """A page carrying the payload the way the real one does: split mid-token."""
    half = len(payload) // 2
    return "".join(
        f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>"
        for part in (payload[:half], payload[half:])
    )


def test_extract_items_reads_listings_split_across_chunks():
    assert [item["id"] for item in _extract_items(page(PAYLOAD))] == [1, 2]


def test_extract_items_rejects_a_page_with_no_listings():
    """A bot challenge answers 200 with a page that has no payload in it."""
    with pytest.raises(VintedError):
        _extract_items(page('{"catalogs":[]}'))


def test_web_params_renames_list_filters_and_drops_per_page():
    assert _web_params(
        {
            "search_text": "navy throw",
            "per_page": 96,
            "price_to": 40,
            "currency": None,
            "catalog_ids": [1806],
            "status_ids": [6, 2],
        }
    ) == {
        "search_text": "navy throw",
        "price_to": 40,
        "catalog[]": [1806],
        "status_ids[]": [6, 2],
    }


def test_search_absolutises_listing_urls(monkeypatch):
    client = VintedClient(domain="www.vinted.co.uk")
    monkeypatch.setattr(client, "_get_items", lambda url: _extract_items(page(PAYLOAD)))
    assert [item["url"] for item in client.search({"search_text": "throw"})] == [
        "https://www.vinted.co.uk/items/1-navy-throw",
        "https://www.vinted.co.uk/items/2-blue-throw",
    ]
