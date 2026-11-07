"""The update CLI must report rejected releases even in quiet check mode."""

import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from dshcopr import manifest, specgen  # noqa: E402
from support import asset, manifest_data, release  # noqa: E402

MODULE_SPEC = importlib.util.spec_from_file_location("update_release", ROOT / "scripts" / "update-release.py")
update_release = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(update_release)


class UpdateReleaseCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh update release ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.manifest_path = self.root / "release.json"
        self.spec_path = self.root / "deepseek-harness.spec"
        self.data = manifest_data()
        manifest.dump(self.data, self.manifest_path)
        specgen.write(self.data, self.spec_path)
        self.before = (self.manifest_path.read_bytes(), self.spec_path.read_bytes())

    def complete_current_release(self):
        assets = []
        for arch in manifest.ARCHES:
            recorded = self.data["assets"][arch]
            assets.append({
                "id": recorded["id"],
                "name": recorded["name"],
                "size": recorded["size"],
                "digest": "sha256:" + recorded["sha256"],
                "state": "uploaded",
                "browser_download_url": recorded["url"],
            })
        return release(self.data["upstream"]["tag"], assets)

    def complete_old_release(self):
        return release(
            "v0.1.0",
            [asset(arch, tag="v0.1.0", version="0.1.0") for arch in manifest.ARCHES],
            published_at="2026-11-01T00:00:00Z",
        )

    def run_check(self, releases, *, error=False):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(update_release.github.GitHubClient, "releases", return_value=releases) as api,
            patch.object(update_release.github.urllib.request, "urlopen") as network,
            patch.object(update_release.update, "apply") as apply,
            patch.object(update_release, "_verify_published_assets", wraps=update_release._verify_published_assets) as verify,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            args = ["--check", "--manifest", str(self.manifest_path), "--spec", str(self.spec_path)]
            if error:
                with self.assertRaises(SystemExit) as raised:
                    update_release.main(args)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("update-release: error:", stderr.getvalue())
            else:
                self.assertEqual(update_release.main(args), 0)
                self.assertEqual(stderr.getvalue(), "")
            api.assert_called_once_with(self.data["upstream"]["repository"])
            network.assert_not_called()
            apply.assert_not_called()
        self.assertEqual((self.manifest_path.read_bytes(), self.spec_path.read_bytes()), self.before)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["status"], "error" if error else "up-to-date")
        return result, verify.call_count

    def test_incomplete_current_and_new_releases_are_errors_in_quiet_mode(self):
        current = release("v0.2.2rc1", [asset("x86_64", tag="v0.2.2rc1")])
        newer = release("v0.3.0", [asset("x86_64")], published_at="2026-11-06T00:00:00Z")
        result, calls = self.run_check([self.complete_old_release(), current, newer], error=True)
        self.assertIn("cannot be packaged", result["message"])
        self.assertEqual(calls, 0)

    def test_current_release_missing_arch_or_digest_is_an_error(self):
        for defect in ("missing-arch", "missing-digest"):
            with self.subTest(defect=defect):
                current = self.complete_current_release()
                if defect == "missing-arch":
                    current["assets"].pop()
                else:
                    current["assets"][0]["digest"] = None
                self.run_check([self.complete_old_release(), current], error=True)

    def test_higher_incomplete_version_blocks_later_published_complete_release(self):
        complete = release(
            "v0.3.0", [asset(arch) for arch in manifest.ARCHES],
            published_at="2026-11-06T00:00:00Z",
        )
        incomplete = release(
            "v0.4.0", [asset("x86_64", tag="v0.4.0")],
            published_at="2026-11-05T00:00:00Z",
        )
        self.run_check([complete, incomplete], error=True)

    def test_unknown_new_or_undated_tag_is_an_error_without_new_candidate(self):
        for timestamp in ("2026-11-06T00:00:00Z", None):
            with self.subTest(timestamp=timestamp):
                unknown = release("nightly", [], published_at=timestamp)
                self.run_check([self.complete_old_release(), unknown], error=True)

    def test_only_complete_old_release_is_up_to_date(self):
        result, calls = self.run_check([self.complete_old_release()])
        self.assertEqual(result["tag"], self.data["upstream"]["tag"])
        self.assertEqual(calls, 0)

    def test_complete_current_release_still_verifies_published_assets(self):
        result, calls = self.run_check([self.complete_old_release(), self.complete_current_release()])
        self.assertEqual(result["tag"], self.data["upstream"]["tag"])
        self.assertEqual(calls, 1)

    def test_replaced_current_release_asset_is_still_rejected(self):
        for field, value in (("digest", "sha256:" + "f" * 64), ("size", 4321), ("name", "changed-linux-x86_64-unsigned.rpm")):
            with self.subTest(field=field):
                current = copy.deepcopy(self.complete_current_release())
                current["assets"][0][field] = value
                result, calls = self.run_check([current], error=True)
                self.assertIn("no longer matches the manifest", result["message"])
                self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
