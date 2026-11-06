#!/usr/bin/env python3
"""Fail on rpmlint findings that are not explicitly allowed for this package.

The package is a repack of a signed, prebuilt Electron application, so a
number of rpmlint checks are expected to fire (unstripped bundled binaries,
rpath, no man page for the launcher, ...).  Every allowed check must be listed
with a reason in ``packaging/rpmlint-exceptions.txt``; anything else fails CI.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
EXCEPTIONS = ROOT / "packaging" / "rpmlint-exceptions.txt"

_LINE_RE = re.compile(r"^(?P<pkg>\S+): (?P<severity>[EWC]): (?P<check>[\w.%+-]+)(?:\s+(?P<detail>.*))?$")


def load_exceptions(path: pathlib.Path) -> set[str]:
    allowed = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if " " in line:
            raise SystemExit(f"{path}:{number}: expected one check name per line, got {raw!r}")
        allowed.add(line)
    return allowed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", help="rpmlint output captured from the built RPM")
    parser.add_argument("--exceptions", default=str(EXCEPTIONS))
    args = parser.parse_args(argv)

    allowed = load_exceptions(pathlib.Path(args.exceptions))
    text = pathlib.Path(args.report).read_text(encoding="utf-8", errors="replace")

    unlisted: list[str] = []
    malformed: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("=====") or line.startswith("("):
            continue
        if line.startswith(("rpmlint:", "configuration:", "checks:")):
            continue
        if line.startswith("/") and line.endswith(".toml"):
            continue
        if re.match(r"^\d+ packages? and \d+ specfiles? checked", line):
            continue
        match = _LINE_RE.match(line)
        if match is None:
            malformed.append(line)
            continue
        check = match.group("check")
        seen.add(check)
        if check not in allowed:
            unlisted.append(line)

    unused = sorted(allowed - seen)
    for check in unused:
        print(f"note: allowed check {check!r} did not fire", file=sys.stderr)

    if malformed:
        print("error: rpmlint produced output this script does not understand:", file=sys.stderr)
        for line in malformed:
            print(f"  {line}", file=sys.stderr)
        return 2

    if unlisted:
        print("error: rpmlint findings that are not in packaging/rpmlint-exceptions.txt:", file=sys.stderr)
        for line in unlisted:
            print(f"  {line}", file=sys.stderr)
        print(
            "Add the check name with a justification if the finding is expected for this repack.",
            file=sys.stderr,
        )
        return 1

    print(f"rpmlint: {len(seen)} allowed check(s), no unlisted findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
