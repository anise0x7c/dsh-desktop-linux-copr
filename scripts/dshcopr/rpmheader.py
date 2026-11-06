"""Minimal pure-Python RPM header reader.

Only the few tags needed to validate upstream assets are implemented.  Using
this instead of the ``rpm`` Python bindings keeps the update workflow runnable
on GitHub's Ubuntu runners, where those bindings are not installed.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

__all__ = ["RpmHeaderError", "RpmMetadata", "read_metadata", "read_metadata_bytes"]

LEAD_MAGIC = b"\xed\xab\xee\xdb"
HEADER_MAGIC = b"\x8e\xad\xe8\x01"

TAG_NAME = 1000
TAG_VERSION = 1001
TAG_RELEASE = 1002
TAG_EPOCH = 1003
TAG_SUMMARY = 1004
TAG_LICENSE = 1014
TAG_ARCH = 1022
TAG_OS = 1021

TYPE_INT32 = 4
TYPE_STRING = 6
TYPE_STRING_ARRAY = 8
TYPE_I18NSTRING = 9

LEAD_SIZE = 96


class RpmHeaderError(ValueError):
    """The file is not an RPM or its header could not be parsed."""


@dataclass(frozen=True)
class RpmMetadata:
    name: str
    version: str
    release: str
    arch: str
    license: str
    epoch: int
    summary: str
    os: str


class _Header:
    def __init__(self, entries: dict[int, tuple[int, int, int]], data: bytes):
        self._entries = entries
        self._data = data

    def _entry(self, tag: int):
        return self._entries.get(tag)

    def string(self, tag: int) -> str | None:
        entry = self._entry(tag)
        if entry is None:
            return None
        typ, offset, _count = entry
        if typ == TYPE_STRING:
            end = self._data.find(b"\0", offset)
            if end < 0:
                raise RpmHeaderError(f"unterminated string for tag {tag}")
            return self._data[offset:end].decode("utf-8", "replace")
        if typ == TYPE_STRING_ARRAY:
            end = self._data.find(b"\0", offset)
            if end < 0:
                raise RpmHeaderError(f"unterminated string array for tag {tag}")
            return self._data[offset:end].decode("utf-8", "replace")
        if typ == TYPE_I18NSTRING:
            end = self._data.find(b"\0", offset)
            if end < 0:
                raise RpmHeaderError(f"unterminated i18n string for tag {tag}")
            return self._data[offset:end].decode("utf-8", "replace")
        return None

    def integer(self, tag: int) -> int | None:
        entry = self._entry(tag)
        if entry is None:
            return None
        typ, offset, count = entry
        if typ != TYPE_INT32 or count < 1:
            return None
        if offset + 4 > len(self._data):
            raise RpmHeaderError(f"integer tag {tag} points outside the header")
        return struct.unpack_from(">i", self._data, offset)[0]

    def tags(self) -> set[int]:
        return set(self._entries)


def _parse_header(blob: bytes) -> _Header:
    if blob[:4] != HEADER_MAGIC:
        raise RpmHeaderError("missing RPM header magic")
    if len(blob) < 16:
        raise RpmHeaderError("truncated RPM header")
    _reserved, count, size = struct.unpack(">III", blob[4:16])
    index_size = 16 * count
    if 16 + index_size + size > len(blob):
        raise RpmHeaderError("RPM header index or data is truncated")

    entries: dict[int, tuple[int, int, int]] = {}
    for item in range(count):
        start = 16 + item * 16
        tag, typ, offset, nitems = struct.unpack(">IIII", blob[start : start + 16])
        if offset > size:
            raise RpmHeaderError(f"tag {tag} points outside the header data")
        entries[tag] = (typ, offset, nitems)
    return _Header(entries, blob[16 + index_size : 16 + index_size + size])


def _headers_in_file(path: str) -> list[_Header]:
    with open(path, "rb") as handle:
        data = handle.read()
    return _headers_in_bytes(data)


def _headers_in_bytes(data: bytes) -> list[_Header]:
    if len(data) < 16:
        raise RpmHeaderError("file is too small to be an RPM")

    offset = 0
    if data[:4] == LEAD_MAGIC:
        offset = LEAD_SIZE
    elif data[:4] != HEADER_MAGIC:
        raise RpmHeaderError("not an RPM file (bad lead magic)")

    headers: list[_Header] = []
    while offset + 16 <= len(data) and data[offset : offset + 4] == HEADER_MAGIC:
        _reserved, count, size = struct.unpack(">III", data[offset + 4 : offset + 16])
        length = 16 + 16 * count + size
        if offset + length > len(data):
            raise RpmHeaderError("RPM header is truncated")
        headers.append(_parse_header(data[offset : offset + length]))
        offset += length
        # Header sections are padded to an 8 byte boundary.
        offset += (-offset) % 8

    if not headers:
        raise RpmHeaderError("no RPM header found")
    return headers


def read_metadata(path: str) -> RpmMetadata:
    """Read the main RPM header and return the fields used for validation."""

    return _metadata_from_header(_headers_in_file(path)[-1])


def read_metadata_bytes(data: bytes) -> RpmMetadata:
    """Read the main RPM header from the first bytes of an RPM file.

    The caller is responsible for fetching enough of the file; a truncated
    header raises :class:`RpmHeaderError`.
    """

    return _metadata_from_header(_headers_in_bytes(data)[-1])


def _metadata_from_header(main: _Header) -> RpmMetadata:
    if main.string(TAG_NAME) is None:
        raise RpmHeaderError("header has no NAME tag; not a binary RPM header")
    return RpmMetadata(
        name=main.string(TAG_NAME) or "",
        version=main.string(TAG_VERSION) or "",
        release=main.string(TAG_RELEASE) or "",
        arch=main.string(TAG_ARCH) or "",
        license=main.string(TAG_LICENSE) or "",
        epoch=main.integer(TAG_EPOCH) or 0,
        summary=main.string(TAG_SUMMARY) or "",
        os=main.string(TAG_OS) or "",
    )
