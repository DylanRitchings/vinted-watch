# vinted-watch

Polls Vinted searches and pushes new listings to [ntfy](https://ntfy.sh). Ships
as a Nix flake with a NixOS module, so every search is declared in your system
config instead of clicked into a web UI.

- **Stdlib-only Python.** No `requests`, no headless browser, no Docker.
- **Systemd oneshot + timer.** Nothing is running between polls.
- **Quiet by default.** A new watch seeds silently on its first poll, so
  enabling one does not dump 96 notifications on your phone — and Vinted's
  churning result pool is filtered out rather than notified about (see below).
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
| `perPage` | `96` | Vinted's maximum. A bigger sample means new listings are caught sooner. |
| `maxNotificationsPerRun` | `10` | Excess listings are recorded as seen, so no backlog builds up. |
| `priceIncludesFees` | `true` | Compare bounds against the fee-inclusive checkout total. |
| `requireQueryInTitle` | `true` | Every word of the query must appear in the title or brand. |
| `digest` | `false` | Bundle a poll's new listings into one notification. |
| `ntfy.tokenFile` | `null` | Passed via systemd credentials; never enters the Nix store. |
| `extraParams` | `{}` | Raw catalog query params — copy numeric IDs out of a filtered search URL. |

`brands`, `sizes` and `conditions` are exact-match allowlists against Vinted's
own labels; `titleInclude` / `titleExclude` are case-insensitive substring
matches against the title and brand.

### Vinted's search is an OR, so this ANDs it back

Vinted treats "herringbone navy blanket" as *any* of those words, so most of
what comes back is plain blankets — measured at about one result in ten
actually containing all three. `requireQueryInTitle` (**on by default**)
requires every word of the query to appear in the title or brand, which on a
real query cut 96 results down to 4 genuine matches. Turn it off to see
everything Vinted considers related, or add `titleAll` for extra required
words.

### Not hearing about the same thing twice

Overlapping watches ("herringbone navy throw" and "herringbone blue throw")
routinely return the same listing. Within a single poll, a listing notifies
once no matter how many watches match it.

### Ignoring things

`ignoreIds` and `ignoreSellers` exist both globally and per-watch, and merge:

```nix
services.vinted-watch = {
  ignoreSellers = [ "bulkshop123" ];      # applies to every watch
  watches."carhartt jacket".ignoreIds = [ 9929551660 ];
};
```

Every notification carries the seller's username, so blocklisting a shop that
floods your results is a copy-paste. The listing id is the number in its URL.

### Digest notifications

With `digest = true`, a poll that turns up several new matches sends one
notification listing them all rather than one each. A lone listing still gets
the per-listing format, which carries the photo and opens the listing when
tapped — ntfy allows only one click target per message, so a digest puts the
URLs inline instead.

## How new listings are identified

Vinted's catalog endpoint ignores the `order` parameter. Every request answers
with a *different sample* of the fuzzily-matched result pool: two polls seconds
apart typically share only about half their ids, and paging through does not
converge on a stable set either. Measured on a real query, a plain seen-set
treats 14–24 listings per poll as "new", most of them months old.

So a listing counts as new only when its id is **above the highest id ever
observed** for that watch, matching or not. Vinted allocates ids in ascending
order, so anything genuinely new clears the mark and the churn below it stays
quiet. On the same query that produced 14–24 false positives per poll, this
leaves 0–1.

The mark only advances when a larger id is actually observed, so a new listing
that one poll's sample happens to miss stays notifiable on later polls.

Two consequences worth knowing:

- A **price drop on an existing listing does not notify** — its id is below the
  mark. This tool watches for new listings, not for repricing.
- Widening a query (raising `maxPrice`, dropping a filter) will **not** surface
  matching listings that already existed. Run `--reseed` if you want the new
  baseline recorded silently, or delete that watch's state file to start over.

## Tuning a query

The package is installed system-wide when the module is enabled:

```console
$ vinted-watch --config /nix/store/…-vinted-watch.json --dry-run -v
```

`--dry-run` prints matches to stdout and touches no state, so you can iterate on
filters without burning through notifications. `--watch NAME` restricts the run
to one search, and `--reseed` re-records the current results silently (use it
after widening a query that would otherwise fire a burst).

## Checking notifications actually arrive

A watch that is working correctly is silent, which is indistinguishable from a
watch that is broken. `--send-test` notifies about the newest current matches
through the real notifier, ignoring and preserving state:

```console
$ vinted-watch --config "$CFG" --watch "carhartt jacket" --send-test
```

One notification, straight to your phone. `--send-test N` sends the newest N.
If nothing arrives, check the topic your client is subscribed to matches
`ntfy.topic` before looking anywhere else.

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
