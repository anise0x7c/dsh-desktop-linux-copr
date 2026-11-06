import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr.versioning import (  # noqa: E402
    VersionError,
    compare_versions,
    is_prerelease,
    parse_tag,
)


class ParseTagTest(unittest.TestCase):
    def test_plain_versions(self):
        self.assertEqual(parse_tag("v0.2.2"), "0.2.2")
        self.assertEqual(parse_tag("1.0.0"), "1.0.0")
        self.assertEqual(parse_tag("v2"), "2")

    def test_prereleases(self):
        self.assertEqual(parse_tag("v0.2.2rc1"), "0.2.2~rc.1")
        self.assertEqual(parse_tag("v0.2.2-rc.1"), "0.2.2~rc.1")
        self.assertEqual(parse_tag("v1.0.0-beta3"), "1.0.0~beta.3")
        self.assertEqual(parse_tag("v1.0.0_alpha.2"), "1.0.0~alpha.2")

    def test_unknown_formats_are_rejected(self):
        for tag in ("nightly", "v0.2.2-rc", "release-1.0", "v0.2.2rc1-hotfix", ""):
            with self.subTest(tag=tag):
                with self.assertRaises(VersionError):
                    parse_tag(tag)

    def test_prerelease_detection(self):
        self.assertTrue(is_prerelease("0.2.2~rc.1"))
        self.assertFalse(is_prerelease("0.2.2"))

    def test_compare_versions(self):
        self.assertLess(compare_versions("0.2.2~rc.1", "0.2.2"), 0)
        self.assertGreater(compare_versions("0.3.0", "0.2.2"), 0)


if __name__ == "__main__":
    unittest.main()
