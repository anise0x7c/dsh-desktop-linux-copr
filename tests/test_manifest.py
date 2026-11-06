import copy
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr import manifest  # noqa: E402

MANIFEST = ROOT / "packaging" / "release.json"


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.data = manifest.load(MANIFEST)

    def test_repository_manifest_is_valid(self):
        self.assertEqual(self.data["package"]["name"], "deepseek-harness")
        self.assertEqual(self.data["upstream"]["tag"], "v0.2.2rc1")

    def test_version_must_match_tag(self):
        data = copy.deepcopy(self.data)
        data["package"]["version"] = "9.9.9"
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(data)

    def test_both_architectures_are_required(self):
        data = copy.deepcopy(self.data)
        del data["assets"]["aarch64"]
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(data)

    def test_sha256_must_be_lowercase(self):
        data = copy.deepcopy(self.data)
        data["assets"]["x86_64"]["sha256"] = "A" * 64
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(data)

    def test_commit_must_be_full_length(self):
        data = copy.deepcopy(self.data)
        data["upstream"]["commit"] = "deadbeef"
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(data)

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "release.json"
            manifest.dump(self.data, path)
            self.assertEqual(manifest.load(path), self.data)

    def test_version_newer(self):
        self.assertTrue(manifest.version_newer("0.3.0", "0.2.2~rc.1"))
        self.assertFalse(manifest.version_newer("0.2.2~rc.1", "0.2.2"))


if __name__ == "__main__":
    unittest.main()
