import copy
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from dshcopr import manifest, update  # noqa: E402
from support import FakeClient, asset, make_rpm, manifest_data, release  # noqa: E402



def complete_release(tag, *, version="0.3.0", published_at="2026-11-05T10:00:00Z", id_=2):
    assets = [
        asset("x86_64", tag=tag, version=version),
        asset("aarch64", tag=tag, version=version),
    ]
    return release(tag, assets, published_at=published_at, release_id=id_)


class FindCandidateTest(unittest.TestCase):
    def setUp(self):
        # Fixed fixture, independent of the repository manifest: the automated
        # update PR is expected to change that manifest's version.
        self.current = manifest_data()["package"]["version"]

    def test_picks_the_newest_complete_release(self):
        releases = [
            release(
                "v0.2.2rc1",
                [
                    asset("x86_64", tag="v0.2.2rc1", version="0.2.2-rc.1"),
                    asset("aarch64", tag="v0.2.2rc1", version="0.2.2-rc.1"),
                ],
            ),
            complete_release("v0.3.0"),
        ]
        candidate = update.find_candidate(releases, self.current)
        self.assertEqual(candidate.tag, "v0.3.0")
        self.assertEqual(candidate.version, "0.3.0")

    def test_drafts_are_ignored(self):
        draft = complete_release("v9.9.9")
        draft["draft"] = True
        candidate = update.find_candidate([draft, complete_release("v0.3.0")], self.current)
        self.assertEqual(candidate.tag, "v0.3.0")

    def test_older_release_means_no_update(self):
        releases = [complete_release("v0.1.0", version="0.1.0")]
        self.assertIsNone(update.find_candidate(releases, self.current))

    def test_missing_arch_is_an_error_when_newest(self):
        incomplete = release("v0.4.0", [asset("x86_64", tag="v0.4.0")], published_at="2026-11-06T00:00:00Z")
        releases = [complete_release("v0.3.0"), incomplete]
        with self.assertRaises(update.UpdateError):
            update.find_candidate(releases, self.current)

    def test_unknown_tag_is_an_error_when_newest(self):
        weird = release("nightly-2026-11-06", [], published_at="2026-11-06T00:00:00Z")
        with self.assertRaises(update.UpdateError):
            update.find_candidate([complete_release("v0.3.0"), weird], self.current)

    def test_missing_digest_is_rejected(self):
        assets = [asset("x86_64", digest=None), asset("aarch64")]
        with self.assertRaises(update.UpdateError):
            update.find_candidate([release("v0.3.0", assets)], self.current)

    def test_candidate_newer_than_a_future_manifest_is_found(self):
        current = manifest_data(tag="v0.3.0", version="0.3.0", release=3)[
            "package"
        ]["version"]
        candidate = update.find_candidate(
            [complete_release("v1.0.0", version="1.0.0")], current
        )
        self.assertEqual(candidate.tag, "v1.0.0")
        self.assertEqual(candidate.version, "1.0.0")

class BuildManifestTest(unittest.TestCase):
    def setUp(self):
        self.current = manifest_data()
        self.candidate = update.find_candidate(
            [complete_release("v0.3.0")], self.current["package"]["version"]
        )
        self.client = self.client_for(self.candidate, version="0.3.0")

    def client_for(self, candidate, *, version="0.3.0", release="1"):
        headers = {}
        for arch in ("x86_64", "aarch64"):
            headers[candidate.assets[arch]["browser_download_url"]] = make_rpm(
                {1001: version, 1002: release, 1022: arch}
            )
        return FakeClient(headers)

    def test_builds_a_consistent_manifest(self):
        updated = update.build_manifest(self.client, self.current, self.candidate, today="2026-11-07")
        self.assertEqual(updated["package"]["version"], "0.3.0")
        self.assertEqual(updated["package"]["release"], 2)
        self.assertEqual(updated["upstream"]["tag"], "v0.3.0")
        self.assertEqual(updated["upstream"]["commit"], "c" * 40)
        self.assertEqual(updated["assets"]["aarch64"]["sha256"], "a" * 64)
        self.assertEqual(updated["assets"]["x86_64"]["rpm_release"], "1")
        self.assertIn("carried over", " ".join(updated["audit"]["notes"]).lower())
        manifest.validate(updated)

    def test_header_version_must_match_tag(self):
        for arch in ("x86_64", "aarch64"):
            self.client.headers[self.candidate.assets[arch]["browser_download_url"]] = make_rpm(
                {1001: "0.9.9", 1022: arch}
            )
        with self.assertRaises(update.UpdateError):
            update.build_manifest(self.client, self.current, self.candidate)

    def test_architectures_must_agree_on_release(self):
        self.client.headers[self.candidate.assets["aarch64"]["browser_download_url"]] = make_rpm(
            {1001: "0.3.0", 1002: "2", 1022: "aarch64"}
        )
        with self.assertRaises(update.UpdateError):
            update.build_manifest(self.client, self.current, self.candidate)

    def test_existing_carry_over_note_is_replaced_not_duplicated(self):
        first = update.build_manifest(self.client, self.current, self.candidate, today="2026-11-07")
        second = update.build_manifest(self.client, first, self.candidate, today="2026-11-08")
        notes = [note for note in second["audit"]["notes"] if note.startswith("License and Requires")]
        self.assertEqual(len(notes), 1)

    def test_downstream_release_tracks_the_upstream_rpm(self):
        current = manifest_data(release=7)
        client = self.client_for(self.candidate, release="2")
        updated = update.build_manifest(client, current, self.candidate, today="2026-11-07")
        self.assertEqual(updated["package"]["release"], 3)
        self.assertNotEqual(updated["package"]["release"], current["package"]["release"])

    def test_builds_a_manifest_for_a_future_version(self):
        candidate = update.find_candidate(
            [complete_release("v1.0.0", version="1.0.0")],
            self.current["package"]["version"],
        )
        client = self.client_for(candidate, version="1.0.0")
        updated = update.build_manifest(client, self.current, candidate, today="2026-11-07")
        self.assertEqual(updated["package"]["version"], "1.0.0")
        self.assertEqual(updated["upstream"]["tag"], "v1.0.0")
        manifest.validate(updated)


if __name__ == "__main__":
    unittest.main()
