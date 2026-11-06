"""Test helpers: build synthetic RPM headers and GitHub responses."""

from __future__ import annotations

import struct


def make_header(fields: dict[int, str | int]) -> bytes:
    """Build one RPM header section (magic, index, data)."""

    data = bytearray()
    entries = []
    for tag, value in fields.items():
        if isinstance(value, int):
            while len(data) % 4:
                data.append(0)
            entries.append((tag, 4, len(data), 1))
            data.extend(struct.pack(">i", value))
        else:
            entries.append((tag, 6, len(data), 1))
            data.extend(value.encode("utf-8") + b"\0")

    index = b"".join(struct.pack(">IIII", *entry) for entry in entries)
    return b"\x8e\xad\xe8\x01" + struct.pack(">III", 0, len(entries), len(data)) + index + bytes(data)


def make_rpm(overrides: dict | None = None) -> bytes:
    fields = {
        1000: "deepseek-harness",
        1001: "0.3.0",
        1002: "1",
        1003: 0,
        1004: "DeepSeek Harness desktop application",
        1014: "MIT",
        1021: "linux",
        1022: "x86_64",
    }
    fields.update(overrides or {})
    lead = b"\xed\xab\xee\xdb" + b"\0" * 92
    signature = make_header({})
    body = lead + signature
    body += b"\0" * ((-len(body)) % 8)
    return body + make_header(fields)


class FakeClient:
    """Stand-in for github.GitHubClient used by update.build_manifest."""

    def __init__(self, headers: dict[str, bytes], commit: str = "c" * 40):
        self.headers = headers
        self.commit = commit
        self.range_calls = []

    def read_range(self, url: str, length: int) -> bytes:
        self.range_calls.append((url, length))
        return self.headers[url][:length]

    def resolve_tag_commit(self, repository: str, tag: str) -> str:
        return self.commit


def release(tag, assets, *, draft=False, published_at="2026-11-04T17:05:02Z", release_id=1):
    return {
        "id": release_id,
        "tag_name": tag,
        "draft": draft,
        "published_at": published_at,
        "html_url": f"https://github.com/ffyfox/dsh-desktop-linux/releases/tag/{tag}",
        "assets": assets,
    }


def asset(arch, *, tag="v0.3.0", size=1234, digest="sha256:" + "a" * 64, state="uploaded", asset_id=7):
    name = f"deepseek-harness-0.3.0-rc.1-linux-{arch}-unsigned.rpm"
    return {
        "id": asset_id,
        "name": name,
        "size": size,
        "digest": digest,
        "state": state,
        "browser_download_url": (
            "https://github.com/ffyfox/dsh-desktop-linux/releases/download/"
            f"{tag}/{name}"
        ),
    }
