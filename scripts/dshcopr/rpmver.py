"""RPM version comparison.

This is a pure-Python implementation of rpmvercmp(3) so that the update
tooling can order upstream tags on machines that do not have RPM Python
bindings (for example ubuntu-latest GitHub runners).  The algorithm follows
rpmio/rpmvercmp.c::

    ~ sorts before everything else
    ^ sorts after the empty string but before any other character
    digit segments compare numerically, alpha segments lexically
    a digit segment sorts higher than an alpha segment

The test suite cross-checks this implementation against ``rpm.labelCompare``
when the bindings are available.
"""

from __future__ import annotations

__all__ = ["rpmvercmp", "label_compare", "version_key"]


def _isdigit(char: str) -> bool:
    return "0" <= char <= "9"


def _isalpha(char: str) -> bool:
    return ("a" <= char <= "z") or ("A" <= char <= "Z")


def rpmvercmp(one: str, two: str) -> int:
    """Compare two version strings the way RPM does.

    Returns -1, 0 or 1 when *one* is older than, equal to or newer than *two*.
    """

    if one == two:
        return 0

    i = 0
    j = 0
    len_one = len(one)
    len_two = len(two)

    while i < len_one or j < len_two:
        # Skip separators (anything that is not alphanumeric, ~ or ^).
        while i < len_one and not _isdigit(one[i]) and not _isalpha(one[i]) and one[i] not in "~^":
            i += 1
        while j < len_two and not _isdigit(two[j]) and not _isalpha(two[j]) and two[j] not in "~^":
            j += 1

        # Tilde sorts before everything, including the end of the string.
        one_tilde = i < len_one and one[i] == "~"
        two_tilde = j < len_two and two[j] == "~"
        if one_tilde or two_tilde:
            if not one_tilde:
                return 1
            if not two_tilde:
                return -1
            i += 1
            j += 1
            continue

        # Caret sorts after the empty string but before anything else.
        one_caret = i < len_one and one[i] == "^"
        two_caret = j < len_two and two[j] == "^"
        if one_caret or two_caret:
            if one_caret and two_caret:
                i += 1
                j += 1
                continue
            if one_caret:
                return 1 if j >= len_two else -1
            return -1 if i >= len_one else 1

        if i >= len_one or j >= len_two:
            break

        # Compare one segment: a run of digits or a run of letters.
        numeric = _isdigit(one[i])
        start_one = i
        if numeric:
            while i < len_one and _isdigit(one[i]):
                i += 1
        else:
            while i < len_one and _isalpha(one[i]):
                i += 1

        start_two = j
        if numeric:
            if not _isdigit(two[j]):
                return 1  # numeric segments are newer than alpha segments
            while j < len_two and _isdigit(two[j]):
                j += 1
        else:
            if not _isalpha(two[j]):
                return -1
            while j < len_two and _isalpha(two[j]):
                j += 1

        segment_one = one[start_one:i]
        segment_two = two[start_two:j]

        if numeric:
            segment_one = segment_one.lstrip("0") or "0"
            segment_two = segment_two.lstrip("0") or "0"
            if len(segment_one) != len(segment_two):
                return 1 if len(segment_one) > len(segment_two) else -1

        if segment_one != segment_two:
            return 1 if segment_one > segment_two else -1

    if i >= len_one and j >= len_two:
        return 0
    return -1 if i >= len_one else 1


def label_compare(
    epoch_one: int,
    version_one: str,
    release_one: str,
    epoch_two: int,
    version_two: str,
    release_two: str,
) -> int:
    """Compare two (epoch, version, release) labels like ``rpm.labelCompare``."""

    if epoch_one != epoch_two:
        return 1 if epoch_one > epoch_two else -1
    result = rpmvercmp(version_one, version_two)
    if result:
        return result
    return rpmvercmp(release_one, release_two)


def version_key(version: str) -> tuple:
    """Return a sort key that orders versions using RPM rules.

    ``functools.cmp_to_key`` is easier to use, but tuples keep call sites
    simple.  The key is only meaningful for comparison, not inspection.
    """

    import functools

    return functools.cmp_to_key(rpmvercmp)(version)
