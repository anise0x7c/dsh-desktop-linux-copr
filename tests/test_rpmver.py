import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr.rpmver import label_compare, rpmvercmp  # noqa: E402


class RpmverTest(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(rpmvercmp("1.0", "1.0"), 0)
        self.assertEqual(rpmvercmp("0.2.2~rc.1", "0.2.2~rc.1"), 0)

    def test_prerelease_sorts_before_release(self):
        self.assertLess(rpmvercmp("0.2.2~rc.1", "0.2.2"), 0)
        self.assertLess(rpmvercmp("0.2.2~alpha.1", "0.2.2~beta.1"), 0)
        self.assertLess(rpmvercmp("0.2.2~beta.1", "0.2.2~rc.1"), 0)

    def test_numeric_and_alpha_segments(self):
        self.assertLess(rpmvercmp("1.9", "1.10"), 0)
        self.assertLess(rpmvercmp("1.0", "1.0.1"), 0)
        self.assertGreater(rpmvercmp("1.0a", "1.0"), 0)

    def test_label_compare_uses_epoch(self):
        self.assertLess(label_compare(0, "1.0", "1", 1, "0.1", "1"), 0)
        self.assertGreater(label_compare(2, "0.1", "1", 1, "9.9", "9"), 0)


if __name__ == "__main__":
    unittest.main()
