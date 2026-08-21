#!/usr/bin/env python3
"""Verify a published release tarball matches the tagged tree, by git blob hash.

The one thing a deploy rehearsal would catch is a release that ships the wrong
tree, so wayfinder #31 established this pre-flight and #41's cutover repeats it.

Compared by *git blob hash* rather than by file hash on disk: a working-tree
export renders line endings per .gitattributes, so comparing rendered files
reports every text file as different and the check fails for a reason that has
nothing to do with the release.

Usage
-----
    python3 tools/verify_release_tarball.py --tag v0.6.0-oaa8-2 --sha <commit>
"""

from __future__ import annotations

import argparse
import hashlib
import io
import subprocess
import sys
import tarfile
import urllib.request

REPO = "oaa8/homeassistant_alpha"
SUBTREE = "custom_components/deako"


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def tarball_blobs(tag: str) -> dict[str, str]:
    url = f"https://api.github.com/repos/{REPO}/tarball/{tag}"
    with urllib.request.urlopen(url) as response:
        payload = response.read()
    found: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            # <owner>-<repo>-<sha>/custom_components/deako/...
            parts = member.name.split("/", 1)
            if len(parts) != 2 or not parts[1].startswith(SUBTREE + "/"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            found[parts[1][len(SUBTREE) + 1:]] = blob_hash(handle.read())
    return found


def tagged_blobs(sha: str) -> dict[str, str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", sha, SUBTREE],
        capture_output=True, text=True, check=True,
    ).stdout
    found: dict[str, str] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        meta, path = line.split("\t", 1)
        found[path[len(SUBTREE) + 1:]] = meta.split()[2]
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--sha", required=True, help="the commit the tag pins")
    args = parser.parse_args()

    released = tarball_blobs(args.tag)
    tagged = tagged_blobs(args.sha)

    missing = sorted(set(tagged) - set(released))
    extra = sorted(set(released) - set(tagged))
    differing = sorted(
        p for p in set(tagged) & set(released) if tagged[p] != released[p]
    )

    print(f"tag:            {args.tag}")
    print(f"pinned commit:  {args.sha}")
    print(f"files in tag:   {len(tagged)}")
    print(f"files in .tgz:  {len(released)}")
    print(f"missing:        {len(missing)} {missing if missing else ''}")
    print(f"extra:          {len(extra)} {extra if extra else ''}")
    print(f"differing:      {len(differing)} {differing if differing else ''}")
    ok = not (missing or extra or differing)
    print()
    print("MATCHES the tagged tree exactly" if ok
          else "DOES NOT MATCH -- do not deploy this release")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
