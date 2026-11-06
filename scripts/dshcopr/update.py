"""Discover the newest upstream release and refresh the release manifest.

The update tool only *proposes* changes: it writes ``packaging/release.json``
and regenerates the spec, but never commits, pushes or triggers a build.  A
human merges the resulting pull request, which is what makes COPR rebuild.
"""

from __future__ import annotations

import copy
import datetime
import pathlib
import re

from . import github, manifest as manifest_mod, rpmheader, specgen
from .versioning import VersionError, compare_versions, is_prerelease, parse_tag

__all__ = ["UpdateError", "find_candidate", "build_manifest", "apply", "UpstreamRelease"]

_ASSET_RE = {
    "x86_64": re.compile(r"-linux-x86_64-unsigned\.rpm$"),
    "aarch64": re.compile(r"-linux-aarch64-unsigned\.rpm$"),
}
_RANGE_CHUNK = 8 * 1024 * 1024
_MAX_RANGE_CHUNK = 64 * 1024 * 1024
_CARRY_OVER_PREFIX = "License and Requires were carried over from"
_SHA256_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


class UpdateError(RuntimeError):
    """The upstream release cannot be packaged without human review."""


class UpstreamRelease:
    """A release that has complete, correctly named RPM assets for both arches."""

    def __init__(self, release: dict, version: str):
        self.release = release
        self.version = version
        self.tag = release["tag_name"]
        self.published_at = release.get("published_at") or release.get("created_at") or ""
        self.assets = {}
        for arch in manifest_mod.ARCHES:
            self.assets[arch] = _asset_for(release, arch)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"UpstreamRelease({self.tag!r}, {self.version!r})"


def _asset_for(release: dict, arch: str) -> dict:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError(f"{release.get('tag_name')}: release has no asset list")
    matches = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and isinstance(asset.get("name"), str)
        and _ASSET_RE[arch].search(asset["name"])
    ]
    if len(matches) != 1:
        raise UpdateError(
            f"{release.get('tag_name')}: expected exactly one {arch} RPM, found {len(matches)}"
        )
    asset = matches[0]
    if asset.get("state") not in (None, "uploaded"):
        raise UpdateError(f"{asset.get('name')}: asset state is {asset.get('state')!r}")
    if not isinstance(asset.get("size"), int) or asset["size"] <= 0:
        raise UpdateError(f"{asset.get('name')}: missing size")
    digest = asset.get("digest")
    match = _SHA256_RE.match(digest) if isinstance(digest, str) else None
    if match is None:
        raise UpdateError(
            f"{asset.get('name')}: GitHub does not report a sha256 digest for this asset; "
            "refusing to record an unverified checksum"
        )
    if not isinstance(asset.get("browser_download_url"), str):
        raise UpdateError(f"{asset.get('name')}: missing browser_download_url")
    asset["_sha256"] = match.group(1)
    return asset


def _published_key(release: dict) -> str:
    return release.get("published_at") or release.get("created_at") or ""


def find_candidate(releases: list[dict], current_version: str, log=print) -> UpstreamRelease | None:
    """Return the newest complete release, or ``None`` when nothing is newer.

    Raises :class:`UpdateError` when a release newer than the best complete
    candidate cannot be interpreted, so that a format change is noticed
    instead of silently skipping an update.
    """

    parsed: list[UpstreamRelease] = []
    rejected: list[tuple[str, dict, str]] = []

    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = release.get("tag_name")
        if not isinstance(tag, str) or not tag:
            rejected.append((str(tag), release, "release has no tag_name"))
            continue
        try:
            version = parse_tag(tag)
        except VersionError as exc:
            rejected.append((tag, release, str(exc)))
            continue
        try:
            parsed.append(UpstreamRelease(release, version))
        except UpdateError as exc:
            rejected.append((tag, release, str(exc)))

    for tag, _release, reason in rejected:
        log(f"warning: ignoring release {tag}: {reason}")

    if not parsed:
        raise UpdateError("no upstream release with complete x86_64 and aarch64 RPM assets was found")

    # Only compare versions among releases that are at least as new as the
    # manifest; older releases may legitimately use a different scheme.
    newer = [item for item in parsed if compare_versions(item.version, current_version) >= 0]
    if not newer:
        log(f"no upstream release is newer than {current_version}")
        return None
    best = newer[0]
    for item in newer[1:]:
        comparison = compare_versions(item.version, best.version)
        if comparison > 0 or (comparison == 0 and item.published_at > best.published_at):
            best = item

    best_published = best.published_at
    for tag, release, reason in rejected:
        published = _published_key(release)
        if published and published >= best_published:
            raise UpdateError(
                f"release {tag} is at least as new as {best.tag} but cannot be packaged: {reason}; "
                "review the upstream release manually"
            )

    return best


def _remote_metadata(client: github.GitHubClient, asset: dict, arch: str) -> rpmheader.RpmMetadata:
    url = asset["browser_download_url"]
    size = asset["size"]
    length = min(_RANGE_CHUNK, size)
    last_error: Exception | None = None
    while True:
        data = client.read_range(url, length)
        try:
            metadata = rpmheader.read_metadata_bytes(data)
            break
        except rpmheader.RpmHeaderError as exc:
            last_error = exc
            if length >= size or length >= _MAX_RANGE_CHUNK:
                raise UpdateError(
                    f"{asset['name']}: cannot read the RPM header within {length} bytes: {exc}"
                ) from exc
            length = min(length * 2, size, _MAX_RANGE_CHUNK)

    expected = ("deepseek-harness", arch, "linux")
    actual = (metadata.name, metadata.arch, metadata.os)
    if actual != expected:
        raise UpdateError(f"{asset['name']}: unexpected RPM identity {actual}, expected {expected}")
    if metadata.epoch != 0:
        raise UpdateError(f"{asset['name']}: unexpected epoch {metadata.epoch}")
    return metadata


def build_manifest(
    client: github.GitHubClient,
    current: dict,
    candidate: UpstreamRelease,
    *,
    today: str | None = None,
) -> dict:
    """Return a validated manifest for *candidate*, based on *current*."""

    repository = current["upstream"]["repository"]
    metadata = {}
    for arch in manifest_mod.ARCHES:
        metadata[arch] = _remote_metadata(client, candidate.assets[arch], arch)

    versions = {item.version for item in metadata.values()}
    releases = {item.release for item in metadata.values()}
    if versions != {candidate.version}:
        raise UpdateError(
            f"{candidate.tag}: RPM headers report version(s) {sorted(versions)}, "
            f"tag means {candidate.version!r}"
        )
    if len(releases) != 1:
        raise UpdateError(f"{candidate.tag}: architectures disagree on the RPM release: {sorted(releases)}")

    upstream_release = next(iter(releases))
    if not upstream_release.isdigit():
        raise UpdateError(f"{candidate.tag}: RPM release {upstream_release!r} is not numeric")
    downstream_release = int(upstream_release) + 1

    commit = client.resolve_tag_commit(repository, candidate.tag)

    updated = copy.deepcopy(current)
    updated["upstream"] = {
        "repository": repository,
        "tag": candidate.tag,
        "commit": commit,
        "release_id": candidate.release.get("id"),
        "published_at": candidate.published_at,
        "header_license": metadata["x86_64"].license,
    }
    updated["package"]["version"] = candidate.version
    updated["package"]["release"] = downstream_release
    if metadata["x86_64"].summary:
        updated["package"]["summary"] = metadata["x86_64"].summary

    assets = {}
    for arch in manifest_mod.ARCHES:
        asset = candidate.assets[arch]
        item = metadata[arch]
        assets[arch] = {
            "id": asset.get("id"),
            "name": asset["name"],
            "url": asset["browser_download_url"],
            "size": asset["size"],
            "sha256": asset["_sha256"],
            "rpm_release": item.release,
        }
    updated["assets"] = assets

    audit = updated.setdefault("audit", {})
    audit["audited_at"] = today or datetime.date.today().isoformat()
    notes = [
        note
        for note in audit.get("notes", [])
        if not (isinstance(note, str) and note.startswith(_CARRY_OVER_PREFIX))
    ]
    notes.insert(
        0,
        f"{_CARRY_OVER_PREFIX} {current['upstream']['tag']}; re-audit the license expression "
        "and runtime dependencies before merging this automated update.",
    )
    audit["notes"] = notes

    manifest_mod.validate(updated)
    return updated


def apply(manifest: dict, manifest_path: str | pathlib.Path, spec_path: str | pathlib.Path) -> None:
    """Write the manifest and regenerate the spec."""

    manifest_mod.dump(manifest, manifest_path)
    specgen.write(manifest, spec_path)


def describe(candidate: UpstreamRelease) -> str:
    kind = "pre-release" if is_prerelease(candidate.version) else "release"
    return f"{candidate.tag} ({candidate.version}, {kind})"
