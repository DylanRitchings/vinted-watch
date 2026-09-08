import json

from vinted_watch.state import SeenStore, slugify


def test_slugify_makes_safe_filenames():
    assert slugify("Carhartt Detroit Jacket") == "carhartt-detroit-jacket"
    assert slugify("  ../etc/passwd ") == "etc-passwd"
    assert slugify("!!!") == "watch"


def test_first_run_reports_no_history(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    assert not store.usable
    assert store.high_water == 0
    assert store.is_new(1)


def test_records_persist_across_instances(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    store.observe([1, 2])
    store.record([1, 2])
    store.save()

    reloaded = SeenStore(tmp_path, "jackets")
    assert reloaded.usable
    assert reloaded.high_water == 2
    assert not reloaded.is_new(1)
    assert reloaded.is_new(3)


def test_corrupt_state_reseeds_instead_of_crashing(tmp_path):
    path = tmp_path / "jackets.json"
    path.write_text("{not json")

    store = SeenStore(tmp_path, "jackets")
    assert not store.usable
    assert store.is_new(1)


def test_ids_below_the_high_water_mark_are_never_new(tmp_path):
    """The churn case: Vinted resurfacing an old listing we never sampled."""
    store = SeenStore(tmp_path, "jackets")
    store.observe([100])
    store.save()

    reloaded = SeenStore(tmp_path, "jackets")
    assert not reloaded.is_new(99)  # older listing, never notified about
    assert not reloaded.is_new(100)
    assert reloaded.is_new(101)


def test_high_water_only_advances(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    store.observe([100, 50, 70])
    assert store.high_water == 100
    store.observe([60])
    assert store.high_water == 100


def test_observing_does_not_mark_as_notified(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    store.observe([100])
    store.save()
    # 100 is below the mark so it is not new, but it was never recorded as
    # notified either -- observe() and record() are separate facts.
    assert "100" not in json.loads((tmp_path / "jackets.json").read_text())["seen"]


def test_v1_state_without_a_mark_forces_a_reseed(tmp_path):
    """Upgrading must not fire the whole churn backlog at the user."""
    path = tmp_path / "jackets.json"
    path.write_text(json.dumps({"version": 1, "seen": {"1": 0.0}}))

    store = SeenStore(tmp_path, "jackets")
    assert not store.usable


def test_save_prunes_to_the_newest_entries(tmp_path):
    store = SeenStore(tmp_path, "jackets", max_entries=3)
    for item_id in range(10):
        store.record([item_id])
    store.save()

    seen = json.loads((tmp_path / "jackets.json").read_text())["seen"]
    assert len(seen) == 3


def test_save_leaves_no_temp_file(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    store.record([1])
    store.save()
    assert [p.name for p in tmp_path.iterdir()] == ["jackets.json"]
