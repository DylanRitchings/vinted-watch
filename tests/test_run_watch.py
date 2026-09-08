import pytest

from vinted_watch.config import Watch
from vinted_watch.listing import Filters
from vinted_watch.main import run_watch


class FakeClient:
    def __init__(self, items):
        self.items = items

    def search(self, params):
        return self.items


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, watch, item):
        self.sent.append(item)


def item(item_id, title="Jacket", amount="20.00"):
    return {
        "id": item_id,
        "title": title,
        "url": f"https://www.vinted.co.uk/items/{item_id}",
        "brand_title": "Carhartt",
        "size_title": "M",
        "status": "Very good",
        "price": {"amount": amount, "currency_code": "GBP"},
        "total_item_price": {"amount": amount, "currency_code": "GBP"},
    }


def watch(**filters):
    return Watch(name="jackets", params={}, filters=Filters(**filters))


def run(items, tmp_path, notifier, *, filters=None, cap=10, dry_run=False, reseed=False):
    return run_watch(
        watch(**(filters or {})),
        FakeClient(items),
        notifier,
        tmp_path,
        cap,
        dry_run,
        reseed,
    )


def test_first_run_seeds_without_notifying(tmp_path):
    notifier = FakeNotifier()
    assert run([item(1), item(2)], tmp_path, notifier) == 0
    assert notifier.sent == []


def test_second_run_notifies_only_about_new_listings(tmp_path):
    notifier = FakeNotifier()
    run([item(1), item(2)], tmp_path, notifier)

    assert run([item(3), item(2), item(1)], tmp_path, notifier) == 1
    assert [i.id for i in notifier.sent] == [3]


def test_nothing_is_notified_twice(tmp_path):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier)
    run([item(2), item(1)], tmp_path, notifier)
    run([item(2), item(1)], tmp_path, notifier)
    assert [i.id for i in notifier.sent] == [2]


def test_notifications_are_sent_oldest_first(tmp_path):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier)
    # The API returns newest first, so 3 is newer than 2.
    run([item(3), item(2), item(1)], tmp_path, notifier)
    assert [i.id for i in notifier.sent] == [2, 3]


def test_cap_limits_notifications_but_still_records_them(tmp_path):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier)

    assert run([item(4), item(3), item(2), item(1)], tmp_path, notifier, cap=2) == 2
    assert [i.id for i in notifier.sent] == [3, 4]

    # The suppressed listing must not resurface on the next poll.
    notifier.sent.clear()
    run([item(4), item(3), item(2), item(1)], tmp_path, notifier)
    assert notifier.sent == []


def test_churned_in_old_listings_are_not_notified(tmp_path):
    """Vinted resamples its result pool every request, surfacing old listings.

    Those must stay quiet: they are below the high water mark even though this
    watch has never notified about them.
    """
    notifier = FakeNotifier()
    run([item(500), item(400)], tmp_path, notifier)

    assert run([item(300), item(200), item(100)], tmp_path, notifier) == 0
    assert notifier.sent == []


def test_a_missed_new_listing_stays_notifiable(tmp_path):
    """The mark only advances on ids actually observed, so nothing is lost
    just because one poll's sample happened to omit it."""
    notifier = FakeNotifier()
    run([item(100)], tmp_path, notifier)

    run([item(50)], tmp_path, notifier)  # sample missed 200 entirely
    assert notifier.sent == []

    run([item(200), item(50)], tmp_path, notifier)
    assert [i.id for i in notifier.sent] == [200]


def test_price_drops_below_the_mark_do_not_alert(tmp_path):
    """Deliberate trade-off: suppressing the churn also suppresses price drops
    on listings older than the high water mark."""
    notifier = FakeNotifier()
    filters = {"max_price": 30}
    run([item(100, amount="10.00")], tmp_path, notifier, filters=filters)

    run([item(50, amount="99.00")], tmp_path, notifier, filters=filters)
    run([item(50, amount="25.00")], tmp_path, notifier, filters=filters)
    assert notifier.sent == []


def test_high_water_covers_listings_that_failed_the_filters(tmp_path):
    """A non-matching listing still proves ids up to its own existed."""
    notifier = FakeNotifier()
    filters = {"max_price": 30}
    run([item(100, amount="10.00")], tmp_path, notifier, filters=filters)

    # 200 is too expensive to notify about, but it moves the mark.
    run([item(200, amount="99.00")], tmp_path, notifier, filters=filters)
    assert notifier.sent == []

    run([item(150, amount="10.00")], tmp_path, notifier, filters=filters)
    assert notifier.sent == []


def test_reseed_records_without_notifying(tmp_path):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier)

    assert run([item(2), item(1)], tmp_path, notifier, reseed=True) == 0
    assert notifier.sent == []

    run([item(2), item(1)], tmp_path, notifier)
    assert notifier.sent == []


def test_dry_run_leaves_no_state_behind(tmp_path):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier, dry_run=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("amount", ["31.00", "0.00"])
def test_filters_are_applied_before_notifying(tmp_path, amount):
    notifier = FakeNotifier()
    run([item(1)], tmp_path, notifier, filters={"max_price": 30, "min_price": 1})
    run([item(2, amount=amount)], tmp_path, notifier, filters={"max_price": 30, "min_price": 1})
    assert notifier.sent == []
