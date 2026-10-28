#!/usr/bin/env python3
"""Keep the Perl catalogue in versions.json current.

Policy, applied against the releases published at https://www.cpan.org/src/5.0/:

  * Only stable series count: even minor versions (5.44.x). Odd minors are
    development releases.
  * A series already in the catalogue is bumped in place to its newest point
    release (5.44.0 -> 5.44.1). `default` follows if it pointed at the old one.
  * A stable series newer than everything in the catalogue is added and
    becomes `default`.
  * Nothing is ever removed; retiring a series is a deliberate edit.

Each new entry's sha256 is the one cpan.org publishes beside the tarball,
cross-checked against the downloaded tarball itself.

    build/bump-perl.py            # report what would change
    build/bump-perl.py --write    # apply it to versions.json

With GITHUB_OUTPUT set, writes `changed=true|false` and a `slug` naming the
versions involved, for the workflow that opens the pull request.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request

SOURCE = "https://www.cpan.org/src/5.0/"


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def parse(version):
    return tuple(int(part) for part in version.split("."))


def stable_releases():
    """All stable release versions on cpan.org, as (major, minor, patch)."""
    listing = fetch(SOURCE).decode("utf-8", "replace")
    found = {parse(v) for v in re.findall(r"perl-(5\.\d+\.\d+)\.tar\.gz", listing)}
    return sorted(v for v in found if v[1] % 2 == 0)


def entry_for(version):
    """The catalogue entry for a release, with its checksum verified."""
    url = SOURCE + f"perl-{version}.tar.gz"
    published = fetch(url + ".sha256").decode().split()[0].lower()
    computed = hashlib.sha256(fetch(url)).hexdigest()
    if computed != published:
        sys.exit(
            f"checksum mismatch for {version}: "
            f"cpan.org publishes {published}, tarball hashes to {computed}"
        )
    return {"url": url, "sha256": computed}


def plan(catalogue, releases):
    """Return {old_version_or_None: new_version} for the changes the policy wants."""
    latest_by_series = {}
    for release in releases:
        latest_by_series[release[:2]] = max(latest_by_series.get(release[:2], release), release)

    changes = {}
    present = {parse(v): v for v in catalogue}
    for version in present.values():
        latest = latest_by_series.get(parse(version)[:2])
        if latest and latest > parse(version):
            changes[version] = ".".join(map(str, latest))

    newest_series = max(latest_by_series)
    if newest_series > max(present)[:2]:
        changes[None] = ".".join(map(str, latest_by_series[newest_series]))
    return changes


def main():
    args = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    args.add_argument("--versions-file", default="versions.json")
    args.add_argument("--write", action="store_true", help="apply the changes")
    args = args.parse_args()

    with open(args.versions_file) as fh:
        data = json.load(fh)
    catalogue = data["perl"]

    changes = plan(catalogue, stable_releases())
    if not changes:
        print("catalogue is current: {}".format(", ".join(sorted(catalogue, key=parse))))
        emit(changed=False, slug="")
        return

    summary = []
    for old, new in sorted(changes.items(), key=lambda kv: parse(kv[1])):
        if old is None:
            summary.append(f"add {new} as the new default")
        else:
            summary.append(f"bump {old} -> {new}")
    print("\n".join(summary))

    if args.write:
        for old, new in changes.items():
            catalogue[new] = entry_for(new)
            if old is not None:
                del catalogue[old]
                if data["default"] == old:
                    data["default"] = new
            else:
                data["default"] = new
        data["perl"] = {v: catalogue[v] for v in sorted(catalogue, key=parse)}
        with open(args.versions_file, "w") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        print(f"wrote {args.versions_file}")

    emit(
        changed=True,
        slug="-".join(new for _, new in sorted(changes.items(), key=lambda kv: parse(kv[1]))),
    )


def emit(changed, slug):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"changed={str(changed).lower()}\nslug={slug}\n")


if __name__ == "__main__":
    main()
