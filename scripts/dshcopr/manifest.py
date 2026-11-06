"""Load, validate and write the release manifest.

``packaging/release.json`` is the single source of truth for the version that
gets packaged.  The spec file is generated from it, never edited by hand.
"""

from __future__ import annotations

import json
import pathlib
import re

from .versioning import VersionError, compare_versions, parse_tag

__all__ = ["ManifestError", "SCHEMA", "ARCHES", "load", "validate", "dump", "assets_for"]

SCHEMA = 1
ARCHES = ("x86_64", "aarch64")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest is malformed or internally inconsistent."""


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ManifestError(f"{where}: missing required key {key!r}")
    return mapping[key]


def validate(manifest: dict) -> dict:
    """Validate *manifest* and return it unchanged.

    The checks are deliberately strict: a malformed manifest must fail before
    anything is downloaded or built.
    """

    if not isinstance(manifest, dict):
        raise ManifestError("manifest must be a JSON object")
    if manifest.get("schema") != SCHEMA:
        raise ManifestError(f"unsupported manifest schema {manifest.get('schema')!r} (expected {SCHEMA})")

    upstream = _require(manifest, "upstream", "manifest")
    package = _require(manifest, "package", "manifest")
    assets = _require(manifest, "assets", "manifest")
    if not isinstance(upstream, dict) or not isinstance(package, dict) or not isinstance(assets, dict):
        raise ManifestError("manifest sections 'upstream', 'package' and 'assets' must be objects")

    for key in ("repository", "tag", "commit"):
        _require(upstream, key, "upstream")
    if not isinstance(upstream["repository"], str) or "/" not in upstream["repository"]:
        raise ManifestError("upstream.repository must be 'owner/name'")
    if not isinstance(upstream["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", upstream["commit"]):
        raise ManifestError("upstream.commit must be a 40 character lowercase commit id")

    name = _require(package, "name", "package")
    version = _require(package, "version", "package")
    release = _require(package, "release", "package")
    license_expression = _require(package, "license", "package")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9+._-]*", name):
        raise ManifestError(f"package.name {name!r} is not a valid RPM name")
    if not isinstance(version, str) or not version:
        raise ManifestError("package.version must be a non-empty string")
    try:
        tag_version = parse_tag(upstream["tag"])
    except VersionError as exc:
        raise ManifestError(str(exc)) from exc
    if tag_version != version:
        raise ManifestError(
            f"package.version {version!r} does not match the RPM version derived "
            f"from upstream.tag {upstream['tag']!r} ({tag_version!r})"
        )
    if not isinstance(release, int) or release < 1:
        raise ManifestError("package.release must be a positive integer")
    if not isinstance(license_expression, str) or not license_expression.strip():
        raise ManifestError("package.license must be a non-empty SPDX expression")

    if set(assets) != set(ARCHES):
        raise ManifestError(f"assets must contain exactly {sorted(ARCHES)}, got {sorted(assets)}")

    for arch in ARCHES:
        asset = assets[arch]
        if not isinstance(asset, dict):
            raise ManifestError(f"assets.{arch} must be an object")
        for key in ("id", "name", "url", "size", "sha256", "rpm_release"):
            _require(asset, key, f"assets.{arch}")
        if not isinstance(asset["id"], int) or asset["id"] <= 0:
            raise ManifestError(f"assets.{arch}.id must be a positive integer")
        if not isinstance(asset["name"], str) or not asset["name"].endswith(".rpm"):
            raise ManifestError(f"assets.{arch}.name must end with '.rpm'")
        if not isinstance(asset["url"], str) or not asset["url"].startswith("https://github.com/"):
            raise ManifestError(f"assets.{arch}.url must be an https://github.com/ URL")
        if not isinstance(asset["size"], int) or asset["size"] <= 0:
            raise ManifestError(f"assets.{arch}.size must be a positive integer")
        if not isinstance(asset["sha256"], str) or not _SHA256_RE.match(asset["sha256"]):
            raise ManifestError(f"assets.{arch}.sha256 must be 64 lowercase hex characters")
        if not isinstance(asset["rpm_release"], str) or not asset["rpm_release"].isdigit():
            raise ManifestError(f"assets.{arch}.rpm_release must be a numeric string")

    return manifest


def load(path: str | pathlib.Path) -> dict:
    """Read a manifest from *path* and validate it."""

    path = pathlib.Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"manifest {path} does not exist") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest {path} is not valid JSON: {exc}") from exc
    return validate(data)


def dump(manifest: dict, path: str | pathlib.Path) -> None:
    """Write *manifest* to *path* in a stable, reviewable format."""

    validate(manifest)
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    path.write_text(text, encoding="utf-8")


def assets_for(manifest: dict, arch: str) -> dict:
    """Return the asset entry for *arch*."""

    return manifest["assets"][arch]


def version_newer(candidate: str, current: str) -> bool:
    """True when the RPM *candidate* version is newer than *current*."""

    return compare_versions(candidate, current) > 0
