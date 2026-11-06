#!/usr/bin/env python3
"""Regenerate (or verify) the spec file from packaging/release.json."""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dshcopr import manifest as manifest_mod  # noqa: E402
from dshcopr import specgen  # noqa: E402

DEFAULT_MANIFEST = specgen.REPO_ROOT / "packaging" / "release.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="release manifest (default: packaging/release.json)",
    )
    parser.add_argument(
        "--output",
        default=str(specgen.SPEC),
        help="spec file to write (default: deepseek-harness.spec)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 when the committed spec is stale",
    )
    args = parser.parse_args(argv)

    try:
        data = manifest_mod.load(args.manifest)
        if args.check:
            diff = specgen.check(data, args.output)
            if diff is not None:
                sys.stdout.write(diff)
                print(f"{args.output}: stale, run scripts/make-spec.py", file=sys.stderr)
                return 1
            print(f"{args.output}: up to date")
            return 0
        written = specgen.write(data, args.output)
    except (manifest_mod.ManifestError, specgen.SpecgenError) as exc:
        print(f"make-spec: error: {exc}", file=sys.stderr)
        return 2

    print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
