import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr import manifest, specgen  # noqa: E402

MANIFEST = ROOT / "packaging" / "release.json"


class SpecgenTest(unittest.TestCase):
    def setUp(self):
        self.data = manifest.load(MANIFEST)

    def test_committed_spec_is_current(self):
        diff = specgen.check(self.data, specgen.SPEC)
        self.assertIsNone(diff, diff)

    def test_render_contains_version_requires_and_sources(self):
        text = specgen.render(self.data)
        self.assertIn("Version:        0.2.2~rc.1", text)
        self.assertIn("Requires:       gtk3", text)
        self.assertIn(self.data["assets"]["x86_64"]["url"], text)
        self.assertIn(self.data["assets"]["aarch64"]["url"], text)
        self.assertNotIn("@@", text)
        self.assertIn('"%{appdir}"', text)

    def test_stale_spec_produces_diff(self):
        data = copy.deepcopy(self.data)
        data["package"]["release"] = 99
        diff = specgen.check(data, specgen.SPEC)
        self.assertIsNotNone(diff)
        self.assertIn("-Release:        2%{?dist}", diff)
        self.assertIn("+Release:        99%{?dist}", diff)

    def test_unresolved_placeholder_is_an_error(self):
        with self.assertRaises(specgen.SpecgenError):
            specgen.render(self.data, "Name: x\n@@NOT_A_PLACEHOLDER@@\n")

    def test_changelog_date(self):
        self.assertEqual(specgen._changelog_date("2026-11-04T17:05:02Z"), "Wed Nov 04 2026")


if __name__ == "__main__":
    unittest.main()
