import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from dshcopr.rpmheader import RpmHeaderError, read_metadata_bytes  # noqa: E402
from support import make_rpm  # noqa: E402


class RpmHeaderTest(unittest.TestCase):
    def test_reads_main_header(self):
        metadata = read_metadata_bytes(make_rpm())
        self.assertEqual(metadata.name, "deepseek-harness")
        self.assertEqual(metadata.version, "0.3.0")
        self.assertEqual(metadata.release, "1")
        self.assertEqual(metadata.arch, "x86_64")
        self.assertEqual(metadata.license, "MIT")
        self.assertEqual(metadata.epoch, 0)
        self.assertEqual(metadata.os, "linux")

    def test_arch_override(self):
        metadata = read_metadata_bytes(make_rpm({1022: "aarch64"}))
        self.assertEqual(metadata.arch, "aarch64")

    def test_truncated_header_is_rejected(self):
        with self.assertRaises(RpmHeaderError):
            read_metadata_bytes(make_rpm()[:40])

    def test_non_rpm_is_rejected(self):
        with self.assertRaises(RpmHeaderError):
            read_metadata_bytes(b"not an rpm" * 10)


if __name__ == "__main__":
    unittest.main()
