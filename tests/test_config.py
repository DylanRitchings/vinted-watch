import json

from vinted_watch.config import Config

SETTINGS = {
    "domain": "www.vinted.fr",
    "stateDir": "/var/lib/vinted-watch",
    "maxNotificationsPerRun": 5,
    "notifier": {"type": "ntfy", "url": "https://ntfy.example", "topic": "vinted"},
    "watches": {
        "jackets": {
            "query": "carhartt jacket",
            "maxPrice": 60,
            "perPage": 20,
            "titleExclude": ["kids"],
            "extraParams": {"catalog_ids": "1206"},
        },
        "boots": {"query": "solovair", "enable": False},
    },
}


def load(tmp_path, settings=SETTINGS):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(settings))
    return Config.load(path)


def test_loads_top_level_settings(tmp_path):
    config = load(tmp_path)
    assert config.domain == "www.vinted.fr"
    assert config.max_notifications == 5
    assert config.user_agent  # falls back to the built-in browser string


def test_watches_are_sorted_by_name(tmp_path):
    assert [w.name for w in load(tmp_path).watches] == ["boots", "jackets"]


def test_watch_params_map_onto_the_api(tmp_path):
    jackets = next(w for w in load(tmp_path).watches if w.name == "jackets")
    assert jackets.params["search_text"] == "carhartt jacket"
    assert jackets.params["price_to"] == 60
    assert jackets.params["per_page"] == 20
    assert jackets.params["order"] == "newest_first"
    assert jackets.params["catalog_ids"] == "1206"


def test_price_bounds_are_also_kept_as_local_filters(tmp_path):
    jackets = next(w for w in load(tmp_path).watches if w.name == "jackets")
    assert jackets.filters.max_price == 60.0
    assert jackets.filters.price_includes_fees is True
    assert jackets.filters.title_exclude == ("kids",)


def test_disabled_watch_is_parsed_but_flagged(tmp_path):
    boots = next(w for w in load(tmp_path).watches if w.name == "boots")
    assert boots.enabled is False


def test_snake_case_keys_are_accepted(tmp_path):
    config = load(
        tmp_path,
        {
            "domain": "www.vinted.co.uk",
            "state_dir": "/tmp/state",
            "watches": {"x": {"query": "q", "max_price": 10, "title_exclude": ["no"]}},
        },
    )
    watch = config.watches[0]
    assert str(config.state_dir) == "/tmp/state"
    assert watch.filters.max_price == 10.0
    assert watch.filters.title_exclude == ("no",)


def test_nixos_module_output_shape_is_understood(tmp_path):
    """The NixOS module emits every option, unset ones as null. Nothing may choke."""
    config = load(
        tmp_path,
        {
            "domain": "www.vinted.co.uk",
            "maxNotificationsPerRun": 10,
            "stateDir": "/var/lib/vinted-watch",
            "userAgent": None,
            "notifier": {
                "type": "ntfy",
                "url": "http://ntfy.example",
                "topic": "vinted",
                "priority": "default",
                "tags": "shopping_cart",
                "tokenFile": None,
            },
            "watches": {
                "carhartt jacket": {
                    "enable": True,
                    "query": "carhartt jacket",
                    "order": "newest_first",
                    "perPage": 40,
                    "minPrice": None,
                    "maxPrice": 60,
                    "priceIncludesFees": True,
                    "currency": None,
                    "titleInclude": [],
                    "titleExclude": ["kids"],
                    "brands": [],
                    "sizes": ["M"],
                    "conditions": [],
                    "extraParams": {},
                }
            },
        },
    )
    watch = config.watches[0]
    assert config.user_agent  # null userAgent falls back to the built-in string
    assert watch.params["search_text"] == "carhartt jacket"
    assert watch.params["price_from"] is None  # dropped before the request
    assert watch.filters.sizes == ("M",)


def test_watch_name_is_the_default_search_text(tmp_path):
    config = load(tmp_path, {"watches": {"olympus mju ii": {"maxPrice": 120}}})
    assert config.watches[0].params["search_text"] == "olympus mju ii"


def test_watches_may_be_a_list(tmp_path):
    config = load(tmp_path, {"watches": [{"name": "x", "query": "q"}]})
    assert config.watches[0].name == "x"
