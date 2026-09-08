{
  description = "Poll Vinted searches and push new listings to ntfy";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;
      in {
        packages.default = python.pkgs.buildPythonApplication {
          pname = "vinted-watch";
          # Bumped by .github/scripts/bump_version.py on merge to main.
          version = "0.3.0";
          pyproject = true;
          src = ./.;

          build-system = [ python.pkgs.setuptools ];
          dependencies = [ ];
          nativeCheckInputs = [ python.pkgs.pytestCheckHook ];

          meta = {
            description = "Poll Vinted searches and push new listings to ntfy";
            homepage = "https://github.com/DylanRitchings/vinted-watch";
            license = pkgs.lib.licenses.mit;
            mainProgram = "vinted-watch";
          };
        };

        packages.vinted-watch = self.packages.${system}.default;

        checks.vinted-watch = self.packages.${system}.default;

        devShells.default = pkgs.mkShell {
          packages = [ python python.pkgs.pytest pkgs.ruff ];
        };
      }
    ) // {
      overlays.default = final: prev: {
        vinted-watch = self.packages.${final.stdenv.hostPlatform.system}.default;
      };

      nixosModules.default = { config, lib, pkgs, ... }:
        let
          cfg = config.services.vinted-watch;

          defaultStateDir = "/var/lib/vinted-watch";
          # systemd exposes LoadCredential= files here; the path is stable, so
          # the generated config can point at it directly.
          credentialDir = "/run/credentials/vinted-watch.service";

          watchOptions = { name, ... }: {
            options = {
              enable = lib.mkOption {
                type = lib.types.bool;
                default = true;
                description = "Whether to poll this watch.";
              };

              query = lib.mkOption {
                type = lib.types.str;
                default = name;
                example = "carhartt detroit jacket";
                description = "Search text, exactly as typed into Vinted's search box.";
              };

              order = lib.mkOption {
                type = lib.types.enum [
                  "newest_first"
                  "relevance"
                  "price_low_to_high"
                  "price_high_to_low"
                ];
                default = "newest_first";
                description = "Result ordering requested from Vinted.";
              };

              perPage = lib.mkOption {
                type = lib.types.ints.between 1 96;
                default = 96;
                description = ''
                  Results fetched per poll, capped at Vinted's maximum. Vinted
                  answers each request with a different sample of the matching
                  pool rather than a stable newest-first page, so a larger
                  sample is a straight improvement: it raises the chance that a
                  genuinely new listing is caught on any given poll.
                '';
              };

              minPrice = lib.mkOption {
                type = lib.types.nullOr lib.types.numbers.nonnegative;
                default = null;
                description = "Lower price bound, in the search's currency.";
              };

              maxPrice = lib.mkOption {
                type = lib.types.nullOr lib.types.numbers.nonnegative;
                default = null;
                example = 45;
                description = "Upper price bound, in the search's currency.";
              };

              priceIncludesFees = lib.mkOption {
                type = lib.types.bool;
                default = true;
                description = ''
                  Compare price bounds against the fee-inclusive total the buyer
                  actually pays, rather than the headline item price.
                '';
              };

              currency = lib.mkOption {
                type = lib.types.nullOr lib.types.str;
                default = null;
                example = "GBP";
                description = "Currency code sent with the search.";
              };

              titleInclude = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "detroit" "chore" ];
                description = ''
                  Keep only listings whose title or brand contains at least one
                  of these (case-insensitive). Empty means no constraint.
                '';
              };

              titleExclude = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "kids" "replica" "bundle" ];
                description = "Drop listings whose title or brand contains any of these.";
              };

              requireQueryInTitle = lib.mkOption {
                type = lib.types.bool;
                default = true;
                description = ''
                  Require every word of {option}`query` to appear in the
                  listing's title or brand.

                  Vinted treats a multi-word search as "any of these words", so
                  a search for "herringbone navy blanket" comes back mostly
                  plain blankets — measured at roughly one result in ten
                  actually containing all three words. Turn this off to see
                  everything Vinted considers related.
                '';
              };

              titleAll = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "wool" ];
                description = ''
                  Extra words that must *all* appear in the title or brand, on
                  top of whatever {option}`requireQueryInTitle` requires.
                '';
              };

              digest = lib.mkOption {
                type = lib.types.bool;
                default = false;
                description = ''
                  Send one notification listing every new match from a poll,
                  instead of one notification each. A poll that finds a single
                  listing still uses the per-listing format, which carries the
                  photo and opens the listing when tapped.
                '';
              };

              ignoreIds = lib.mkOption {
                type = lib.types.listOf lib.types.int;
                default = [ ];
                example = [ 9929551660 ];
                description = ''
                  Listing IDs never to notify about, on top of the global
                  {option}`services.vinted-watch.ignoreIds`. The id is the
                  number in the listing's URL.
                '';
              };

              ignoreSellers = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                description = ''
                  Seller usernames never to notify about, on top of the global
                  {option}`services.vinted-watch.ignoreSellers`. The username
                  appears in every notification.
                '';
              };

              brands = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "Carhartt" "Carhartt WIP" ];
                description = "Exact brand allowlist. Empty means any brand.";
              };

              sizes = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "M" "L" ];
                description = "Exact size allowlist, matched against Vinted's size label.";
              };

              conditions = lib.mkOption {
                type = lib.types.listOf lib.types.str;
                default = [ ];
                example = [ "New with tags" "Very good" ];
                description = "Exact condition allowlist, matched against Vinted's status label.";
              };

              extraParams = lib.mkOption {
                type = lib.types.attrsOf (lib.types.oneOf [
                  lib.types.str
                  lib.types.int
                  lib.types.bool
                ]);
                default = { };
                example = { catalog_ids = "1206"; };
                description = ''
                  Extra query parameters passed straight to Vinted's catalog
                  endpoint. Use this for numeric catalog/brand/size IDs, which
                  you can read off the URL of a filtered search in the browser.
                '';
              };
            };
          };

          settings = {
            inherit (cfg) domain maxNotificationsPerRun ignoreIds ignoreSellers;
            userAgent = cfg.userAgent;
            stateDir = cfg.stateDir;
            notifier = {
              type = "ntfy";
              inherit (cfg.ntfy) url topic priority tags controlTopic;
              tokenFile =
                if cfg.ntfy.tokenFile == null then null else "${credentialDir}/ntfy-token";
            };
            watches = lib.mapAttrs (_: watch: {
              inherit (watch)
                enable query order perPage minPrice maxPrice priceIncludesFees
                currency titleInclude titleExclude titleAll requireQueryInTitle
                digest ignoreIds ignoreSellers brands sizes conditions
                extraParams;
            }) cfg.watches;
          };

          configFile = (pkgs.formats.json { }).generate "vinted-watch.json" settings;
        in {
          options.services.vinted-watch = {
            enable = lib.mkEnableOption "the Vinted listing watcher";

            package = lib.mkOption {
              type = lib.types.package;
              default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
              defaultText = lib.literalExpression "vinted-watch";
              description = "The vinted-watch package to run.";
            };

            domain = lib.mkOption {
              type = lib.types.str;
              default = "www.vinted.co.uk";
              example = "www.vinted.fr";
              description = "Vinted domain to search. Determines locale and currency.";
            };

            interval = lib.mkOption {
              type = lib.types.str;
              default = "5m";
              description = ''
                How often to poll, as a systemd time span. Vinted rate limits
                anonymous sessions, so going below a minute or two is asking
                for 429s.
              '';
            };

            randomizedDelaySec = lib.mkOption {
              type = lib.types.str;
              default = "45s";
              description = "Jitter added to each poll, so requests are not perfectly periodic.";
            };

            userAgent = lib.mkOption {
              type = lib.types.nullOr lib.types.str;
              default = null;
              description = ''
                Override the browser User-Agent sent to Vinted. The built-in
                default is a current desktop Chrome string; Vinted rejects
                obvious bot agents.
              '';
            };

            stateDir = lib.mkOption {
              type = lib.types.path;
              default = defaultStateDir;
              description = "Where the per-watch record of already-notified listings lives.";
            };

            maxNotificationsPerRun = lib.mkOption {
              type = lib.types.ints.positive;
              default = 10;
              description = ''
                Cap on notifications per watch per poll. Excess listings are
                still recorded as seen, so a busy search cannot flood the phone.
              '';
            };

            ignoreIds = lib.mkOption {
              type = lib.types.listOf lib.types.int;
              default = [ ];
              example = [ 9929551660 ];
              description = ''
                Listing IDs never to notify about, across every watch. The id
                is the number in the listing's URL.
              '';
            };

            ignoreSellers = lib.mkOption {
              type = lib.types.listOf lib.types.str;
              default = [ ];
              example = [ "bulkshop123" ];
              description = ''
                Seller usernames never to notify about, across every watch.
                The username appears in every notification, so blocklisting a
                shop that floods your results is a copy-paste.
              '';
            };

            ntfy = {
              url = lib.mkOption {
                type = lib.types.str;
                example = "https://ntfy.sh";
                description = "Base URL of the ntfy server.";
              };

              topic = lib.mkOption {
                type = lib.types.str;
                default = "vinted";
                description = "ntfy topic to publish to.";
              };

              priority = lib.mkOption {
                type = lib.types.enum [ "min" "low" "default" "high" "urgent" ];
                default = "default";
                description = "ntfy priority for new-listing notifications.";
              };

              tags = lib.mkOption {
                type = lib.types.str;
                default = "shopping_cart";
                description = "Comma-separated ntfy tags (emoji shortcodes).";
              };

              controlTopic = lib.mkOption {
                type = lib.types.nullOr lib.types.str;
                default = null;
                example = "vinted-control";
                description = ''
                  Topic used as a back-channel from the notifications. Setting
                  it puts "Ignore" and "Block seller" buttons on every
                  notification; tapping one publishes a short command here, and
                  the next poll folds it into the blocklist.

                  Must not be the same topic as {option}`topic`, or your phone
                  will show the control commands as alerts. Subscribe to it
                  only if you want to watch the back-channel.

                  Anyone able to publish to this topic can add blocklist
                  entries, so use an access token if the ntfy server is not
                  LAN-only.
                '';
              };

              tokenFile = lib.mkOption {
                type = lib.types.nullOr lib.types.path;
                default = null;
                example = "/run/secrets/ntfy-token";
                description = ''
                  File holding an ntfy access token. Passed to the unit via
                  systemd credentials, so it never enters the Nix store.
                '';
              };
            };

            watches = lib.mkOption {
              type = lib.types.attrsOf (lib.types.submodule watchOptions);
              default = { };
              example = lib.literalExpression ''
                {
                  "carhartt jacket" = {
                    maxPrice = 60;
                    sizes = [ "M" "L" ];
                    titleExclude = [ "kids" "replica" ];
                  };
                }
              '';
              description = ''
                Searches to poll, keyed by name. The attribute name is used as
                the search text unless {option}`query` overrides it, and names
                the state file and notification prefix.
              '';
            };
          };

          config = lib.mkIf cfg.enable {
            assertions = [
              {
                assertion = cfg.watches != { };
                message = "services.vinted-watch.watches is empty — nothing to poll.";
              }
              {
                assertion = cfg.ntfy.controlTopic != cfg.ntfy.topic;
                message = ''
                  services.vinted-watch.ntfy.controlTopic must differ from
                  ntfy.topic, or the Ignore/Block buttons will publish their
                  commands into your notification feed.
                '';
              }
            ];

            systemd.services.vinted-watch = {
              description = "Poll Vinted searches for new listings";
              after = [ "network-online.target" ];
              wants = [ "network-online.target" ];

              serviceConfig = {
                Type = "oneshot";
                ExecStart = "${lib.getExe cfg.package} --config ${configFile}";

                DynamicUser = true;
                UMask = "0077";
              } // (
                # StateDirectory handles creation and ownership under
                # DynamicUser, but only for paths beneath /var/lib.
                if cfg.stateDir == defaultStateDir then {
                  StateDirectory = "vinted-watch";
                  StateDirectoryMode = "0700";
                } else {
                  ReadWritePaths = [ cfg.stateDir ];
                }
              ) // lib.optionalAttrs (cfg.ntfy.tokenFile != null) {
                LoadCredential = [ "ntfy-token:${cfg.ntfy.tokenFile}" ];
              } // {
                CapabilityBoundingSet = [ "" ];
                LockPersonality = true;
                MemoryDenyWriteExecute = true;
                NoNewPrivileges = true;
                PrivateDevices = true;
                PrivateTmp = true;
                ProtectClock = true;
                ProtectControlGroups = true;
                ProtectHome = true;
                ProtectHostname = true;
                ProtectKernelLogs = true;
                ProtectKernelModules = true;
                ProtectKernelTunables = true;
                ProtectProc = "invisible";
                ProtectSystem = "strict";
                RestrictAddressFamilies = [ "AF_INET" "AF_INET6" "AF_UNIX" ];
                RestrictNamespaces = true;
                RestrictRealtime = true;
                RestrictSUIDSGID = true;
                SystemCallArchitectures = "native";
                SystemCallFilter = [ "@system-service" "~@privileged" "~@resources" ];
              };
            };

            systemd.timers.vinted-watch = {
              description = "Poll Vinted searches for new listings";
              wantedBy = [ "timers.target" ];
              timerConfig = {
                OnBootSec = "2m";
                OnUnitActiveSec = cfg.interval;
                RandomizedDelaySec = cfg.randomizedDelaySec;
                Persistent = true;
                Unit = "vinted-watch.service";
              };
            };

            environment.systemPackages = [ cfg.package ];
          };
        };
    };
}
