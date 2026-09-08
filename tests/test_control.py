import json

from vinted_watch.control import Blocklist


def test_starts_empty(tmp_path):
    blocklist = Blocklist(tmp_path)
    assert blocklist.ids == set()
    assert blocklist.sellers == set()
    assert blocklist.since == "all"


def test_applies_and_persists_commands(tmp_path):
    blocklist = Blocklist(tmp_path)
    assert blocklist.apply("ignore-id 123")
    assert blocklist.apply("ignore-seller bulkshop")
    blocklist.save()

    reloaded = Blocklist(tmp_path)
    assert reloaded.ids == {123}
    assert reloaded.sellers == {"bulkshop"}


def test_repeated_commands_are_idempotent(tmp_path):
    """Control messages are replayed if the cursor does not advance."""
    blocklist = Blocklist(tmp_path)
    assert blocklist.apply("ignore-id 123")
    assert not blocklist.apply("ignore-id 123")
    assert blocklist.ids == {123}


def test_malformed_commands_are_ignored(tmp_path):
    blocklist = Blocklist(tmp_path)
    for command in ("", "ignore-id", "ignore-id abc", "rm -rf /", "ignore-seller"):
        assert not blocklist.apply(command)
    assert blocklist.ids == set()
    assert blocklist.sellers == set()


def test_percent_encoded_arguments_are_decoded(tmp_path):
    """Action buttons percent-encode so the ntfy header stays ASCII."""
    blocklist = Blocklist(tmp_path)
    assert blocklist.apply("ignore-seller caf%C3%A9%20shop")
    assert blocklist.sellers == {"café shop"}


def test_corrupt_blocklist_does_not_crash(tmp_path):
    (tmp_path / "blocklist.json").write_text("{not json")
    assert Blocklist(tmp_path).ids == set()


def test_save_records_the_cursor(tmp_path):
    blocklist = Blocklist(tmp_path)
    blocklist.since = "1788861538"
    blocklist.save()
    assert json.loads((tmp_path / "blocklist.json").read_text())["since"] == "1788861538"
