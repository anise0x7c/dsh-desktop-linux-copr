#!/usr/bin/env python3
"""Download the manifest assets and build a source RPM for COPR.

COPR runs this through ``.copr/Makefile`` inside a mock chroot with network
access.  The resulting SRPM carries both architecture payloads, so a single
SRPM builds on all enabled chroots.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
from typing import NoReturn

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from dshcopr import fetch, manifest as manifest_mod, rpmheader, specgen  # noqa: E402

DEFAULT_MANIFEST = specgen.REPO_ROOT / "packaging" / "release.json"
DEFAULT_CACHE = specgen.REPO_ROOT / ".work" / "cache"
DEFAULT_OUTDIR = specgen.REPO_ROOT / "dist"


def _fail(message: str) -> NoReturn:
    print(f"make-srpm: error: {message}", file=sys.stderr)
    raise SystemExit(2)


def _verify_metadata(path: pathlib.Path, arch: str, manifest: dict) -> None:
    metadata = rpmheader.read_metadata(path)
    package = manifest["package"]
    expected = (
        package["name"],
        package["version"],
        manifest["assets"][arch]["rpm_release"],
        arch,
    )
    actual = (metadata.name, metadata.version, metadata.release, metadata.arch)
    if actual != expected:
        _fail(
            f"{path.name}: RPM header is {actual}, manifest says {expected}; "
            "the published asset does not match the release manifest"
        )
    if metadata.epoch != 0:
        _fail(f"{path.name}: unexpected epoch {metadata.epoch}")


def _download(manifest: dict, cache: pathlib.Path) -> dict[str, pathlib.Path]:
    cache.mkdir(parents=True, exist_ok=True)
    paths: dict[str, pathlib.Path] = {}
    for arch in manifest_mod.ARCHES:
        asset = manifest["assets"][arch]
        destination = cache / asset["name"]
        print(f"fetching {arch}: {asset['name']} ({asset['size']} bytes)")
        fetch.download(
            asset["url"],
            destination,
            expected_size=asset["size"],
            expected_sha256=asset["sha256"],
        )
        _verify_metadata(destination, arch, manifest)
        paths[arch] = destination
    return paths


def _build_srpm(spec: pathlib.Path, cache: pathlib.Path, outdir: pathlib.Path) -> pathlib.Path:
    rpmbuild = shutil.which("rpmbuild")
    if rpmbuild is None:
        _fail("rpmbuild not found; install the 'rpm-build' package")

    topdir = specgen.REPO_ROOT / ".work" / "rpmbuild"
    for sub in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS", "tmp"):
        (topdir / sub).mkdir(parents=True, exist_ok=True)

    outdir.mkdir(parents=True, exist_ok=True)
    command = [
        rpmbuild,
        "-bs",
        "--define", f"_topdir {topdir}",
        "--define", f"_sourcedir {cache}",
        "--define", f"_specdir {spec.parent}",
        "--define", f"_srcrpmdir {outdir}",
        "--define", f"_tmppath {topdir / 'tmp'}",
        str(spec),
    ]
    print("+ " + " ".join(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        _fail(f"rpmbuild -bs failed with exit code {result.returncode}")

    candidates = sorted(outdir.glob("*.src.rpm"), key=lambda item: item.stat().st_mtime)
    if not candidates:
        _fail(f"rpmbuild did not produce a source RPM in {outdir}")
    srpm = candidates[-1]
    print(f"source RPM: {srpm}")
    return srpm


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="verified upstream RPM cache")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="directory for the SRPM")
    parser.add_argument(
        "--spec",
        default=str(specgen.SPEC),
        help="spec file to build (must match the manifest)",
    )
    parser.add_argument("--skip-download", action="store_true", help="use cached RPMs only")
    args = parser.parse_args(argv)

    try:
        manifest = manifest_mod.load(args.manifest)
    except manifest_mod.ManifestError as exc:
        _fail(str(exc))

    spec = pathlib.Path(args.spec).resolve()
    diff = specgen.check(manifest, spec)
    if diff is not None:
        sys.stdout.write(diff)
        _fail(f"{spec} is out of date; run scripts/make-spec.py and commit the result")

    cache = pathlib.Path(args.cache).resolve()
    if args.skip_download:
        missing = [
            manifest["assets"][arch]["name"]
            for arch in manifest_mod.ARCHES
            if not (cache / manifest["assets"][arch]["name"]).is_file()
        ]
        if missing:
            _fail("--skip-download was given but the cache is missing: " + ", ".join(missing))
        for arch in manifest_mod.ARCHES:
            _verify_metadata(cache / manifest["assets"][arch]["name"], arch, manifest)
    else:
        _download(manifest, cache)

    _build_srpm(spec, cache, pathlib.Path(args.outdir).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
