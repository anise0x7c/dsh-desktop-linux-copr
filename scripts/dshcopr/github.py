"""Minimal GitHub REST client used by the release update tool.

Only the endpoints needed to discover upstream releases are implemented.  The
client is deliberately boring: ``urllib`` from the standard library, explicit
timeouts, and no retries on writes (all calls are reads).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["GitHubError", "GitHubClient", "API_ROOT"]

API_ROOT = "https://api.github.com"
USER_AGENT = "dsh-desktop-linux-copr (+https://github.com/anise0x7c/dsh-desktop-linux-copr)"


class GitHubError(RuntimeError):
    """A GitHub API call failed or returned unexpected data."""


class GitHubClient:
    def __init__(self, token: str | None = None, timeout: int = 30):
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        self._timeout = timeout

    def _request(self, url: str) -> urllib.request.Request:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return urllib.request.Request(url, headers=headers)

    def get_json(self, path: str) -> object:
        """GET *path* (relative to the API root or absolute) and decode JSON."""

        url = path if path.startswith("https://") else API_ROOT + path
        try:
            with urllib.request.urlopen(self._request(url), timeout=self._timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            if exc.code == 403 and "rate limit" in detail.lower():
                raise GitHubError(
                    f"GitHub API rate limit exceeded for {url}; provide GITHUB_TOKEN"
                ) from exc
            raise GitHubError(f"GitHub API {url} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"cannot reach GitHub API {url}: {exc.reason}") from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise GitHubError(f"GitHub API {url} returned invalid JSON: {exc}") from exc

    def release_pages(self, repository: str, per_page: int = 100, max_pages: int = 50):
        """Yield every release of *repository*, newest first."""

        page = 1
        while page <= max_pages:
            query = urllib.parse.urlencode({"per_page": per_page, "page": page})
            data = self.get_json(f"/repos/{repository}/releases?{query}")
            if not isinstance(data, list):
                raise GitHubError(f"/repos/{repository}/releases returned {type(data).__name__}, not a list")
            yield from data
            if len(data) < per_page:
                return
            page += 1
        raise GitHubError(f"{repository} has more than {max_pages * per_page} releases; refusing to paginate further")

    def releases(self, repository: str) -> list[dict]:
        return [release for release in self.release_pages(repository) if isinstance(release, dict)]

    def resolve_tag_commit(self, repository: str, tag: str) -> str:
        """Return the commit a tag ultimately points at (following annotated tags)."""

        ref = self.get_json(f"/repos/{repository}/git/ref/tags/{urllib.parse.quote(tag, safe='')}")
        if not isinstance(ref, dict) or "object" not in ref:
            raise GitHubError(f"cannot resolve tag {tag}: unexpected response")
        target = ref["object"]
        for _ in range(5):
            kind = target.get("type")
            sha = target.get("sha")
            if kind == "commit" and isinstance(sha, str):
                return sha
            if kind != "tag" or not isinstance(sha, str):
                raise GitHubError(f"tag {tag} points at unexpected object type {kind!r}")
            tag_object = self.get_json(f"/repos/{repository}/git/tags/{sha}")
            if not isinstance(tag_object, dict) or "object" not in tag_object:
                raise GitHubError(f"cannot dereference tag object {sha}")
            target = tag_object["object"]
        raise GitHubError(f"tag {tag} has more than five levels of tag objects")

    def read_range(self, url: str, length: int) -> bytes:
        """Read the first *length* bytes of *url* without downloading it all."""

        request = self._request(url)
        request.add_header("Range", f"bytes=0-{length - 1}")
        try:
            with urllib.request.urlopen(request, timeout=max(self._timeout, 60)) as response:
                return response.read(length)
        except urllib.error.HTTPError as exc:
            raise GitHubError(f"cannot read the first {length} bytes of {url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise GitHubError(f"cannot read {url}: {exc.reason}") from exc
