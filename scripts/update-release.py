#!/usr/bin/env python3
"""Check GitHub for a newer upstream release and refresh the manifest.

Exit status is 0 for "up to date", "update prepared" and "update available"
(``--check``), and 2 for anything that needs a human decision.  The machine
readable result is printed to stdout as one JSON object; progress goes to
stderr.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import NoReturn

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dshcopr import github, manifest as manifest_mod, specgen, update  # noqa: E402
from dshcopr.versioning import compare_versions  # noqa: E402

DEFAULT_MANIFEST = specgen.REPO_ROOT / "packaging" / "release.json"


def _fail(message: str) -> NoReturn:
    print(f"update-release: error: {message}", file=sys.stderr)
    print(json.dumps({"status": "error", "message": message}))
    raise SystemExit(2)


def _verify_published_assets(candidate: update.UpstreamRelease, current: dict) -> None:
    """Catch a silently replaced asset for the version we already package."""

    for arch in manifest_mod.ARCHES:
        expected = current["assets"][arch]
        asset = candidate.assets[arch]
        actual = (asset["name"], asset["size"], asset["_sha256"])
        wanted = (expected["name"], expected["size"], expected["sha256"])
        if actual != wanted:
            raise update.UpdateError(
                f"{candidate.tag}: the published {arch} asset no longer matches the manifest "
                f"(expected {wanted}, got {actual}); the asset may have been replaced"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--spec", default=str(specgen.SPEC))
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether an update exists without writing files",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="write progress to stderr (default: quiet unless something happens)",
    )
    args = parser.parse_args(argv)

    log = (lambda message: print(message, file=sys.stderr)) if args.log else (lambda message: None)

    try:
        current = manifest_mod.load(args.manifest)
        repository = current["upstream"]["repository"]
        client = github.GitHubClient()
        releases = client.releases(repository)
        candidate = update.find_candidate(releases, current["package"]["version"], log=log)
    except (manifest_mod.ManifestError, github.GitHubError, update.UpdateError) as exc:
        _fail(str(exc))

    if candidate is None:
        print(json.dumps({"status": "up-to-date", "tag": current["upstream"]["tag"]}))
        return 0

    if compare_versions(candidate.version, current["package"]["version"]) == 0:
        if candidate.tag != current["upstream"]["tag"]:
            _fail(
                f"{candidate.tag} maps to the already packaged version "
                f"{candidate.version}, but the manifest tracks {current['upstream']['tag']}; "
                "review this release manually"
            )
        try:
            _verify_published_assets(candidate, current)
        except update.UpdateError as exc:
            _fail(str(exc))
        print(json.dumps({"status": "up-to-date", "tag": candidate.tag}))
        return 0

    try:
        updated = update.build_manifest(client, current, candidate)
    except (github.GitHubError, update.UpdateError) as exc:
        _fail(str(exc))

    difference = specgen.check(updated, args.spec)
    result = {
        "status": "available" if args.check else "updated",
        "tag": candidate.tag,
        "version": candidate.version,
        "release": updated["package"]["release"],
        "previous_tag": current["upstream"]["tag"],
        "commit": updated["upstream"]["commit"],
        "url": candidate.release.get("html_url"),
        "spec_regenerated": difference is not None,
    }

    if args.check:
        print(json.dumps(result))
        return 0

    try:
        update.apply(updated, args.manifest, args.spec)
    except (OSError, specgen.SpecgenError) as exc:
        _fail(f"cannot write the update: {exc}")

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
