import copy
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr import manifest  # noqa: E402
from dshcopr.versioning import parse_tag  # noqa: E402
from support import manifest_data  # noqa: E402

MANIFEST = ROOT / "packaging" / "release.json"


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.data = manifest.load(MANIFEST)

    def test_repository_manifest_is_valid(self):
        self.assertEqual(self.data["package"]["name"], "deepseek-harness")
        self.assertEqual(self.data["upstream"]["repository"], "ffyfox/dsh-desktop-linux")
        # The manifest may legitimately move to a newer upstream release.  Only
        # these relationships are invariant, so derive the expected values from
        # the manifest instead of pinning today's tag.
        self.assertTrue(self.data["upstream"]["tag"].startswith("v"))
        self.assertEqual(
            parse_tag(self.data["upstream"]["tag"]),
            self.data["package"]["version"],
        )
        self.assertGreaterEqual(self.data["package"]["release"], 1)

    def test_version_must_match_tag(self):
        data = copy.deepcopy(self.data)
        data["package"]["version"] += ".mismatch"
        with self.assertRaises(manifest.ManifestError):
            manifest.validate(data)

    def test_future_manifest_versions_are_valid(self):
        for tag, version, release in (
            ("v0.3.0", "0.3.0", 3),
            ("v1.0.0", "1.0.0", 5),
        ):
            with self.subTest(tag=tag):
                data = manifest_data(tag=tag, version=version, release=release)
                self.assertEqual(manifest.validate(data)["package"]["version"], version)
                self.assertEqual(data["package"]["release"], release)

    def test_future_manifest_loads_from_a_temporary_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "release.json"
            manifest.dump(
                manifest_data(tag="v1.0.0", version="1.0.0", release=5), path
            )
            loaded = manifest.load(path)
        self.assertEqual(loaded["upstream"]["tag"], "v1.0.0")
        self.assertEqual(loaded["package"]["version"], "1.0.0")
        self.assertEqual(loaded["package"]["release"], 5)

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
