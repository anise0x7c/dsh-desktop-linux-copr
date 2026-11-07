"""Download release assets with size and SHA-256 verification.

Downloads are only ever used from the local cache when their checksum matches
the manifest.  A partially written or mismatching file is removed, never
silently reused.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import time
import urllib.error
import urllib.request

__all__ = ["FetchError", "sha256_file", "verify_file", "download"]

CHUNK = 1024 * 1024
USER_AGENT = "dsh-desktop-linux-copr (+https://github.com/anise0x7c/dsh-desktop-linux-copr)"


class FetchError(RuntimeError):
    """A download did not produce the expected bytes."""


def sha256_file(path: str | pathlib.Path, chunk: int = CHUNK) -> str:
    """Return the SHA-256 hex digest of *path*."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def verify_file(
    path: str | pathlib.Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> pathlib.Path:
    """Verify an existing file without downloading, changing or removing it."""

    path = pathlib.Path(path)
    try:
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            raise FetchError(
                f"{path.name}: size mismatch (got {actual_size} bytes, expected {expected_size})"
            )
        actual_sha256 = sha256_file(path)
    except OSError as exc:
        raise FetchError(f"{path}: cannot verify file: {exc}") from exc

    if actual_sha256 != expected_sha256:
        raise FetchError(
            f"{path.name}: SHA-256 mismatch (got {actual_sha256}, expected {expected_sha256}); "
            "the cached asset does not match the manifest"
        )
    return path


def download(
    url: str,
    destination: str | pathlib.Path,
    *,
    expected_size: int,
    expected_sha256: str,
    retries: int = 3,
    timeout: int = 300,
    log=print,
) -> pathlib.Path:
    """Download *url* to *destination*, verifying size and checksum.

    The file is written to a ``.part`` sibling and renamed only after both
    checks pass, so an interrupted run can never leave a "valid" cache entry.
    """

    destination = pathlib.Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists():
        try:
            verify_file(
                destination, expected_size=expected_size, expected_sha256=expected_sha256
            )
        except FetchError:
            log(f"cache entry does not match the manifest, refetching: {destination.name}")
            destination.unlink()
        else:
            log(f"cache hit: {destination.name}")
            return destination

    part = destination.with_name(destination.name + ".part")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        part.unlink(missing_ok=True)
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/octet-stream",
                },
            )
            digest = hashlib.sha256()
            written = 0
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) != expected_size:
                    raise FetchError(
                        f"{url}: server reports {content_length} bytes, manifest says {expected_size}"
                    )
                with open(part, "wb") as handle:
                    while True:
                        block = response.read(CHUNK)
                        if not block:
                            break
                        written += len(block)
                        if written > expected_size:
                            raise FetchError(f"{url}: server sent more than {expected_size} bytes")
                        digest.update(block)
                        handle.write(block)

            if written != expected_size:
                raise FetchError(f"{url}: received {written} bytes, expected {expected_size}")
            actual = digest.hexdigest()
            if actual != expected_sha256:
                raise FetchError(
                    f"{url}: SHA-256 mismatch (got {actual}, expected {expected_sha256}); "
                    "the published asset may have been replaced"
                )

            os.replace(part, destination)
            log(f"downloaded: {destination.name}")
            return destination
        except (FetchError, urllib.error.URLError, OSError) as exc:
            last_error = exc
            part.unlink(missing_ok=True)
            if attempt == retries:
                break
            delay = min(2 ** attempt, 10)
            log(f"download attempt {attempt}/{retries} failed ({exc}); retrying in {delay}s")
            time.sleep(delay)

    raise FetchError(f"failed to download {url}: {last_error}")
