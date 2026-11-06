"""Generate the RPM spec file from the release manifest.

The spec is a build artefact of this repository: ``packaging/release.json`` is
the input, ``packaging/deepseek-harness.spec.tmpl`` holds everything that is
not version specific, and ``deepseek-harness.spec`` at the repository root is
the generated result checked by CI.
"""

from __future__ import annotations

import datetime
import difflib
import pathlib

__all__ = ["REPO_ROOT", "TEMPLATE", "SPEC", "SpecgenError", "render", "check", "write"]

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "packaging" / "deepseek-harness.spec.tmpl"
SPEC = REPO_ROOT / "deepseek-harness.spec"

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class SpecgenError(RuntimeError):
    """The template or the manifest cannot produce a consistent spec."""


def _changelog_date(published_at: str) -> str:
    """Return an rpm changelog date (``Tue Nov 04 2026``) for an ISO timestamp."""

    text = published_at.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise SpecgenError(f"invalid upstream.published_at {published_at!r}: {exc}") from exc
    return f"{_DAYS[moment.weekday()]} {_MONTHS[moment.month - 1]} {moment.day:02d} {moment.year}"


def _replacements(manifest: dict) -> dict[str, str]:
    package = manifest["package"]
    upstream = manifest["upstream"]
    assets = manifest["assets"]
    requires = package.get("requires") or []
    if not isinstance(requires, list) or not all(isinstance(item, str) and item for item in requires):
        raise SpecgenError("package.requires must be a list of package names")

    return {
        "@@UPSTREAM_REPO@@": upstream["repository"],
        "@@UPSTREAM_TAG@@": upstream["tag"],
        "@@UPSTREAM_COMMIT@@": upstream["commit"],
        "@@VERSION@@": package["version"],
        "@@RELEASE@@": str(package["release"]),
        "@@SUMMARY@@": package["summary"],
        "@@LICENSE@@": package["license"],
        "@@SOURCE_X86_64@@": assets["x86_64"]["url"],
        "@@SOURCE_AARCH64@@": assets["aarch64"]["url"],
        "@@REQUIRES@@": "\n".join(f"Requires:       {name}" for name in requires),
        "@@CHANGELOG_DATE@@": _changelog_date(upstream["published_at"]),
    }


def render(manifest: dict, template_text: str | None = None) -> str:
    """Render the spec for *manifest*."""

    if template_text is None:
        template_text = TEMPLATE.read_text(encoding="utf-8")

    result = template_text
    for placeholder, value in _replacements(manifest).items():
        if placeholder not in result:
            raise SpecgenError(f"template does not contain {placeholder}")
        result = result.replace(placeholder, value)

    leftovers = sorted({line.strip() for line in result.splitlines() if "@@" in line})
    if leftovers:
        raise SpecgenError("template has unresolved placeholders: " + ", ".join(leftovers))

    if not result.endswith("\n"):
        result += "\n"
    return result


def write(manifest: dict, path: str | pathlib.Path | None = None) -> pathlib.Path:
    """Render and write the spec, returning the path written."""

    path = pathlib.Path(path) if path is not None else SPEC
    path.write_text(render(manifest), encoding="utf-8")
    return path


def check(manifest: dict, path: str | pathlib.Path | None = None) -> str | None:
    """Return a unified diff when the committed spec is stale, else ``None``."""

    path = pathlib.Path(path) if path is not None else SPEC
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"missing generated spec: {path}\n"
    expected = render(manifest)
    if current == expected:
        return None
    return "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            expected.splitlines(keepends=True),
            fromfile=f"{path} (committed)",
            tofile=f"{path} (regenerated)",
        )
    )
