#!/usr/bin/env python3
"""Work out the next version from the commits since the last tag, and apply it.

Bump level follows Conventional Commits:
  BREAKING CHANGE / `type!:`  -> major
  feat:                       -> minor
  anything else               -> patch

Writes the new version into every file that hardcodes it, then reports the
result on stdout as GitHub Actions output lines. Makes no commits or tags --
the workflow does that, so a dry run stays harmless.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# file -> regex with a single group around the version literal
VERSION_SITES = {
    Path("pyproject.toml"): re.compile(r'(?m)^version = "([^"]+)"$'),
    Path("flake.nix"): re.compile(r'(?m)^\s*version = "([^"]+)";'),
    Path("vinted_watch/__init__.py"): re.compile(r'(?m)^__version__ = "([^"]+)"$'),
}

BREAKING = re.compile(r"^[a-z]+(\([^)]*\))?!:|^BREAKING[ -]CHANGE:", re.MULTILINE)
FEATURE = re.compile(r"^feat(\([^)]*\))?!?:", re.MULTILINE)
# Commits the release job itself pushes -- never a reason to cut a release.
RELEASE_COMMIT = re.compile(r"^chore\(release\):", re.MULTILINE)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def latest_tag() -> str | None:
    tags = git("tag", "--list", "v*", "--sort=-v:refname").splitlines()
    return tags[0] if tags else None


def commits_since(tag: str | None) -> list[str]:
    span = f"{tag}..HEAD" if tag else "HEAD"
    log = git("log", span, "--format=%B%x00")
    return [c.strip() for c in log.split("\0") if c.strip()]


def bump_for(commits: list[str]) -> str:
    joined = "\n".join(commits)
    if BREAKING.search(joined):
        return "major"
    if FEATURE.search(joined):
        return "minor"
    return "patch"


def current_version() -> str:
    path, pattern = next(iter(VERSION_SITES.items()))
    match = pattern.search((ROOT / path).read_text())
    if not match:
        raise SystemExit(f"no version found in {path}")
    return match.group(1)


def next_version(version: str, bump: str) -> str:
    try:
        major, minor, patch = (int(part) for part in version.split("."))
    except ValueError:
        raise SystemExit(f"version {version!r} is not major.minor.patch")
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def apply_version(version: str) -> None:
    for path, pattern in VERSION_SITES.items():
        target = ROOT / path
        text = target.read_text()
        updated, count = pattern.subn(
            lambda m: m.group(0).replace(m.group(1), version), text, count=1
        )
        if count != 1:
            raise SystemExit(f"could not rewrite the version in {path}")
        target.write_text(updated)


def emit(**values: str) -> None:
    lines = []
    for key, value in values.items():
        if "\n" in value:
            lines.append(f"{key}<<__EOF__\n{value}\n__EOF__")
        else:
            lines.append(f"{key}={value}")
    output = "\n".join(lines)
    print(output)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a") as handle:
            handle.write(output + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="report the next version, change nothing"
    )
    args = parser.parse_args()

    tag = latest_tag()
    commits = [c for c in commits_since(tag) if not RELEASE_COMMIT.match(c)]

    if tag is None:
        # First run: publish whatever version the files already declare.
        version = current_version()
        emit(released="true", version=version, tag=f"v{version}", bump="initial")
        return 0

    if not commits:
        print(f"no releasable commits since {tag}", file=sys.stderr)
        emit(released="false")
        return 0

    bump = bump_for(commits)
    version = next_version(current_version(), bump)
    if not args.dry_run:
        apply_version(version)
    emit(released="true", version=version, tag=f"v{version}", bump=bump)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
