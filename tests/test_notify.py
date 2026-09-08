import base64

from vinted_watch.listing import Listing
from vinted_watch.notify import NtfyNotifier, _header_safe, describe, describe_digest

RAW = {
    "id": 42,
    "title": "Navy Herringbone Throw",
    "url": "https://www.vinted.co.uk/items/42-navy",
    "brand_title": "TBCo",
    "size_title": "One size",
    "status": "Very good",
    "price": {"amount": "20.00", "currency_code": "GBP"},
    "total_item_price": {"amount": "22.20", "currency_code": "GBP"},
    "user": {"login": "bulkshop"},
}


def make(**overrides):
    return Listing.from_api({**RAW, **overrides})


def test_describe_leads_with_the_price_the_buyer_pays():
    title, body = describe(make())
    assert title.startswith("22.20 GBP — Navy Herringbone Throw")
    assert "item 20.00 + fees" in body


def test_describe_names_the_seller_so_it_can_be_blocked():
    _, body = describe(make())
    assert "by bulkshop" in body


def test_digest_lists_every_listing_with_its_url():
    title, body = describe_digest("throws", [make(), make(id=43)])
    assert title == "throws: 2 new listings"
    assert body.count("https://www.vinted.co.uk/items/") == 2


def test_no_action_buttons_without_a_control_topic():
    notifier = NtfyNotifier(url="http://ntfy.example", topic="price")
    assert notifier._actions(make()) == ""


def test_action_buttons_target_the_control_topic():
    notifier = NtfyNotifier(
        url="http://ntfy.example", topic="price", control_topic="price-control"
    )
    actions = notifier._actions(make())

    assert actions.count("http://ntfy.example/price-control") == 2
    assert "body='ignore-id 42'" in actions
    assert "body='ignore-seller bulkshop'" in actions
    assert "clear=true" in actions


def test_block_seller_button_is_dropped_when_there_is_no_seller():
    notifier = NtfyNotifier(
        url="http://ntfy.example", topic="price", control_topic="price-control"
    )
    actions = notifier._actions(make(user={}))

    assert "ignore-id 42" in actions
    assert "ignore-seller" not in actions


def test_action_arguments_are_percent_encoded_to_stay_ascii():
    notifier = NtfyNotifier(
        url="http://ntfy.example", topic="price", control_topic="price-control"
    )
    actions = notifier._actions(make(user={"login": "café shop"}))

    assert actions.isascii()  # ntfy reads headers as latin-1
    assert "body='ignore-seller caf%C3%A9%20shop'" in actions


def test_non_ascii_titles_are_rfc2047_encoded():
    """A raw em dash used to reach the phone as a literal \\u2014."""
    title = _header_safe("22.20 GBP — Navy Throw")
    assert title.startswith("=?UTF-8?B?")
    assert title.isascii()

    encoded = title.removeprefix("=?UTF-8?B?").removesuffix("?=")
    assert base64.b64decode(encoded).decode() == "22.20 GBP — Navy Throw"


def test_ascii_titles_are_left_alone():
    assert _header_safe("22.20 GBP - Navy Throw") == "22.20 GBP - Navy Throw"
