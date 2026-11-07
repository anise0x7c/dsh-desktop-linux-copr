import copy
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from dshcopr import manifest, specgen  # noqa: E402
from support import manifest_data  # noqa: E402

MANIFEST = ROOT / "packaging" / "release.json"


class SpecgenTest(unittest.TestCase):
    def setUp(self):
        self.data = manifest.load(MANIFEST)

    def test_committed_spec_is_current(self):
        diff = specgen.check(self.data, specgen.SPEC)
        self.assertIsNone(diff, diff)

    def test_render_contains_version_requires_and_sources(self):
        text = specgen.render(self.data)
        package = self.data["package"]
        # Derive the expected values from the manifest so an automated update
        # to a newer upstream release does not fail this test.
        self.assertIn(f"Version:        {package['version']}", text)
        self.assertIn(f"Release:        {package['release']}%{{?dist}}", text)
        for requirement in package["requires"]:
            self.assertIn(f"Requires:       {requirement}", text)
        self.assertIn(self.data["assets"]["x86_64"]["url"], text)
        self.assertIn(self.data["assets"]["aarch64"]["url"], text)
        self.assertNotIn("@@", text)
        self.assertIn('"%{appdir}"', text)

    def test_stale_spec_produces_diff(self):
        data = copy.deepcopy(self.data)
        committed_release = data["package"]["release"]
        data["package"]["release"] = committed_release + 1
        diff = specgen.check(data, specgen.SPEC)
        self.assertIsNotNone(diff)
        self.assertIn(f"-Release:        {committed_release}%{{?dist}}", diff)
        self.assertIn(f"+Release:        {committed_release + 1}%{{?dist}}", diff)

    def test_future_manifest_is_not_reported_stale(self):
        for tag, version, release in (
            ("v0.3.0", "0.3.0", 3),
            ("v1.0.0", "1.0.0", 5),
        ):
            with self.subTest(tag=tag):
                data = manifest_data(tag=tag, version=version, release=release)
                text = specgen.render(data)
                self.assertIn(f"Version:        {version}", text)
                self.assertIn(f"Release:        {release}%{{?dist}}", text)
                with tempfile.TemporaryDirectory() as tmp:
                    path = pathlib.Path(tmp) / "deepseek-harness.spec"
                    path.write_text(text, encoding="utf-8")
                    self.assertIsNone(specgen.check(data, path))

    def test_unresolved_placeholder_is_an_error(self):
        with self.assertRaises(specgen.SpecgenError):
            specgen.render(self.data, "Name: x\n@@NOT_A_PLACEHOLDER@@\n")

    def test_changelog_date(self):
        self.assertEqual(specgen._changelog_date("2026-11-04T17:05:02Z"), "Wed Nov 04 2026")


if __name__ == "__main__":
    unittest.main()
