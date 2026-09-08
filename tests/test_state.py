import json

from vinted_watch.state import SeenStore, slugify


def test_slugify_makes_safe_filenames():
    assert slugify("Carhartt Detroit Jacket") == "carhartt-detroit-jacket"
    assert slugify("  ../etc/passwd ") == "etc-passwd"
    assert slugify("!!!") == "watch"


def test_first_run_reports_no_history(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    assert not store.existed
    assert store.is_new(1)


def test_records_persist_across_instances(tmp_path):
    store = SeenStore(tmp_path, "jackets")
    store.record([1, 2])
    store.save()

    reloaded = SeenStore(tmp_path, "jackets")
    assert reloaded.existed
    assert not reloaded.is_new(1)
    assert reloaded.is_new(3)


def test_corrupt_state_reseeds_instead_of_crashing(tmp_path):
    path = tmp_path / "jackets.json"
    path.write_text("{not json")

    store = SeenStore(tmp_path, "jackets")
    assert not store.existed
    assert store.is_new(1)


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
