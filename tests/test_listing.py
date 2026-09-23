from vinted_watch.listing import Filters, Listing


def label(title="Carhartt Detroit Jacket", brand="Carhartt", size="M"):
    return {
        "accessibilityLabel": (
            f"{title}, Brand: {brand}, Condition: Very good, Size: {size}, "
            "29.94 £, 32.64 £"
        )
    }


RAW = {
    "id": 9900047846,
    "title": "Carhartt Detroit Jacket",
    "url": "https://www.vinted.co.uk/items/9900047846-carhartt",
    "itemBox": label(),
    "price": {"amount": "29.94", "currencyCode": "GBP"},
    "totalItemPrice": {"amount": "32.64", "currencyCode": "GBP"},
    "photos": [{"url": "https://images1.vinted.net/a.jpeg"}],
    "user": {"id": 83654511},
}


def make(**overrides):
    return Listing.from_api({**RAW, **overrides})


def test_from_api_normalises_fields():
    item = make()
    assert item.id == 9900047846
    assert item.brand == "Carhartt"
    assert item.size == "M"
    assert item.condition == "Very good"
    assert item.seller == "83654511"
    assert item.price == 29.94
    assert item.total_price == 32.64
    assert item.buyer_price == 32.64
    assert item.photo == "https://images1.vinted.net/a.jpeg"


def test_from_api_reads_an_unbranded_listing():
    """Only branded listings carry a "Brand:" part, and the label is positional."""
    item = make(itemBox={"accessibilityLabel": "Crochet blanket, Condition: Good, Size: Other, 10.00 £, 11.20 £"})
    assert item.brand == ""
    assert item.condition == "Good"
    assert item.size == "Other"


def test_from_api_tolerates_missing_fields():
    item = Listing.from_api({"id": 1})
    assert item.title == ""
    assert item.price is None
    assert item.buyer_price is None
    assert item.photo is None


def test_from_api_prefers_the_thumbnail_over_the_photo_list():
    item = make(thumbnailUrl="https://images1.vinted.net/thumb.jpeg")
    assert item.photo == "https://images1.vinted.net/thumb.jpeg"


def test_max_price_uses_fee_inclusive_total_by_default():
    item = make()
    assert not Filters(max_price=30).matches(item)
    assert Filters(max_price=30, price_includes_fees=False).matches(item)


def test_min_price_rejects_unpriced_listings():
    assert not Filters(min_price=1).matches(make(price={}, totalItemPrice={}))


def test_title_include_matches_brand_too():
    assert Filters(title_include=["carhartt"]).matches(make(title="Vintage jacket"))
    assert not Filters(title_include=["nike"]).matches(make())


def test_title_exclude_is_case_insensitive():
    assert not Filters(title_exclude=["DETROIT"]).matches(make())


def test_title_all_requires_every_term():
    assert Filters(title_all=("carhartt", "detroit")).matches(make())
    assert not Filters(title_all=("carhartt", "navy")).matches(make())


def test_title_all_matches_across_title_and_brand():
    item = make(title="Detroit Jacket", itemBox=label(title="Detroit Jacket"))
    assert Filters(title_all=("carhartt", "detroit")).matches(item)


def test_ignored_ids_never_match():
    assert not Filters(ignore_ids=frozenset({RAW["id"]})).matches(make())
    assert Filters(ignore_ids=frozenset({1})).matches(make())


def test_ignored_sellers_never_match():
    item = make(user={"id": 12345})
    assert not Filters(ignore_sellers=("12345",)).matches(item)
    assert Filters(ignore_sellers=("99999",)).matches(item)


def test_a_blank_seller_is_not_blocked_by_a_blank_entry():
    """A listing with no seller must not be caught by an empty blocklist entry."""
    assert Filters(ignore_sellers=()).matches(make())


def test_empty_allowlists_do_not_constrain():
    assert Filters().matches(make())


def test_allowlists_require_exact_match():
    assert Filters(sizes=("M", "L")).matches(make())
    assert not Filters(sizes=("XL",)).matches(make())
    assert Filters(brands=("carhartt",)).matches(make())
    assert not Filters(conditions=("New with tags",)).matches(make())
