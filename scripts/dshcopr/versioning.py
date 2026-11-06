"""Map upstream Git tags to RPM versions.

Upstream tags look like ``v0.2.2rc1`` while the RPMs they publish carry
``Version: 0.2.2~rc.1``.  Pre-release suffixes use RPM's tilde notation so
that ``0.2.2~rc.1 < 0.2.2``.  Anything this module does not recognise is an
error: the update tooling must never guess.
"""

from __future__ import annotations

import re

from .rpmver import rpmvercmp

__all__ = ["VersionError", "parse_tag", "compare_versions", "is_prerelease"]

# core: 1 / 0.2 / 0.2.2 ; optional pre-release: rc1, -alpha.2, _beta3, ...
TAG_RE = re.compile(
    r"^v?"
    r"(?P<core>[0-9]+(?:\.[0-9]+)*)"
    r"(?:[-._]?(?P<label>alpha|beta|rc)[.-]?(?P<number>[0-9]+))?"
    r"$",
    re.IGNORECASE,
)


class VersionError(ValueError):
    """The upstream tag does not follow a pattern this repository understands."""


def parse_tag(tag: str) -> str:
    """Return the RPM version corresponding to an upstream *tag*.

    Raises :class:`VersionError` for tags that are not a plain version or a
    numbered alpha/beta/rc pre-release.
    """

    if not isinstance(tag, str) or not tag:
        raise VersionError(f"empty or invalid tag: {tag!r}")

    match = TAG_RE.match(tag)
    if not match:
        raise VersionError(
            f"unsupported upstream tag {tag!r}; expected e.g. v0.2.3, "
            "v0.2.3rc1, v0.2.3-beta.2"
        )

    core = match.group("core")
    label = match.group("label")
    number = match.group("number")

    if label is None:
        return core

    label = label.lower()
    if number is None:
        raise VersionError(
            f"pre-release tag {tag!r} has no number; refusing to guess "
            f"(expected e.g. {tag}1)"
        )

    return f"{core}~{label}.{int(number)}"


def compare_versions(one: str, two: str) -> int:
    """Compare two RPM version strings using RPM rules."""

    return rpmvercmp(one, two)


def is_prerelease(version: str) -> bool:
    """Return True when an RPM version string encodes a pre-release."""

    return "~" in version
