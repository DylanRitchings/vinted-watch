# vinted-watch

Polls Vinted searches and pushes new listings to [ntfy](https://ntfy.sh). Ships
as a Nix flake with a NixOS module, so every search is declared in your system
config instead of clicked into a web UI.

- **Stdlib-only Python.** No `requests`, no headless browser, no Docker.
- **Systemd oneshot + timer.** Nothing is running between polls.
- **Quiet by default.** A new watch seeds silently on its first poll, so
  enabling one does not dump 40 notifications on your phone.
- **Fee-aware price filters.** Price bounds compare against the total the buyer
  actually pays, not the headline item price.

## Why not changedetection.io

Generic page-diff tools have to render Vinted's client-side search grid and get
past its bot protection, and even then they can only watch a fixed URL for "the
page changed". `vinted-watch` talks to the same JSON endpoint the web app uses,
so it gets structured listings — id, price, brand, size, condition, photo — and
can dedupe per listing rather than per page.

Vinted has no public API and does not document this endpoint. It can change
without notice; this is a homelab tool, not a supported integration. Keep the
poll interval sane (minutes, not seconds).

## NixOS usage

```nix
{
  inputs.vinted-watch.url = "github:DylanRitchings/vinted-watch";

  # in your host config
  imports = [ inputs.vinted-watch.nixosModules.default ];

  services.vinted-watch = {
    enable = true;
    domain = "www.vinted.co.uk";
    interval = "5m";

    ntfy = {
      url = "http://ntfy.example.com";
      topic = "vinted";
      priority = "default";
    };

    watches = {
      # The attribute name is the search text unless `query` overrides it.
      "carhartt detroit jacket" = {
        maxPrice = 80;
        sizes = [ "M" "L" ];
        titleExclude = [ "kids" "replica" "bundle" ];
      };

      cameras = {
        query = "olympus mju ii";
        maxPrice = 120;
        conditions = [ "New with tags" "Very good" ];
      };
    };
  };
}
```

### Options worth knowing

| Option | Default | Notes |
| --- | --- | --- |
| `interval` | `5m` | systemd time span. Below a couple of minutes invites 429s. |
| `perPage` | `40` | Only the first page is read — must exceed the new listings per interval. |
| `maxNotificationsPerRun` | `10` | Excess listings are recorded as seen, so no backlog builds up. |
| `priceIncludesFees` | `true` | Compare bounds against the fee-inclusive checkout total. |
| `ntfy.tokenFile` | `null` | Passed via systemd credentials; never enters the Nix store. |
| `extraParams` | `{}` | Raw catalog query params — copy numeric IDs out of a filtered search URL. |

`brands`, `sizes` and `conditions` are exact-match allowlists against Vinted's
own labels; `titleInclude` / `titleExclude` are case-insensitive substring
matches against the title and brand.

Listings that fail a filter are deliberately **not** recorded as seen, so an
item that later drops under `maxPrice` still notifies.

## Tuning a query

The package is installed system-wide when the module is enabled:

```console
$ vinted-watch --config /nix/store/…-vinted-watch.json --dry-run -v
```

`--dry-run` prints matches to stdout and touches no state, so you can iterate on
filters without burning through notifications. `--watch NAME` restricts the run
to one search, and `--reseed` re-records the current results silently (use it
after widening a query that would otherwise fire a burst).

## Standalone usage

```console
$ nix run github:DylanRitchings/vinted-watch -- --config ./config.json --dry-run
```

The config file is plain JSON — the NixOS module just generates it:

```json
{
  "domain": "www.vinted.co.uk",
  "stateDir": "./state",
  "maxNotificationsPerRun": 10,
  "notifier": { "type": "ntfy", "url": "https://ntfy.sh", "topic": "vinted" },
  "watches": {
    "carhartt jacket": { "maxPrice": 60, "titleExclude": ["kids"] }
  }
}
```

Set `"notifier": { "type": "stdout" }` to print instead of pushing.

## Development

```console
$ nix develop
$ pytest
```

## Releases

Every merge to `main` cuts a release. The bump level is read from the commit
messages since the last tag, Conventional Commits style:

| Commit | Bump |
| --- | --- |
| `feat!:` or `BREAKING CHANGE:` | major |
| `feat:` | minor |
| anything else | patch |

CI then rewrites the version in `pyproject.toml`, `flake.nix` and
`vinted_watch/__init__.py`, commits it as `chore(release): X.Y.Z`, tags `vX.Y.Z`
and publishes a GitHub release with generated notes. `.github/scripts/bump_version.py --dry-run`
reports what the next release would be without touching anything.

## License

MIT
