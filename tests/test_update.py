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

    def test_incomplete_current_and_new_release_cannot_mean_no_update(self):
        releases = [
            complete_release("v0.1.0", version="0.1.0"),
            release("v0.2.2rc1", [asset("x86_64", tag="v0.2.2rc1")]),
            release("v0.3.0", [asset("x86_64")]),
        ]
        with self.assertRaises(update.UpdateError):
            update.find_candidate(releases, self.current)

    def test_rejected_current_release_is_checked_without_new_candidate(self):
        for defect in ("missing-arch", "missing-digest"):
            with self.subTest(defect=defect):
                assets = [asset("x86_64", tag="v0.2.2rc1")]
                if defect == "missing-digest":
                    assets.append(asset("aarch64", tag="v0.2.2rc1", digest=None))
                current = release("v0.2.2rc1", assets, published_at=None)
                with self.assertRaises(update.UpdateError):
                    update.find_candidate(
                        [complete_release("v0.1.0", version="0.1.0"), current],
                        self.current,
                    )

    def test_higher_rejected_version_blocks_later_published_candidate(self):
        incomplete = release(
            "v0.4.0", [asset("x86_64", tag="v0.4.0")],
            published_at="2026-11-05T00:00:00Z",
        )
        complete = complete_release("v0.3.0", published_at="2026-11-06T00:00:00Z")
        with self.assertRaisesRegex(update.UpdateError, "v0.4.0"):
            update.find_candidate([incomplete, complete], "0.2.0")

    def test_known_older_rejected_version_is_not_blocking_even_if_published_later(self):
        incomplete = release(
            "v0.2.0", [asset("x86_64", tag="v0.2.0")],
            published_at="2026-11-07T00:00:00Z",
        )
        for tag, version in (("v0.1.0", "0.1.0"), ("v0.3.0", "0.3.0")):
            with self.subTest(complete=tag):
                candidate = update.find_candidate(
                    [incomplete, complete_release(tag, version=version)], self.current
                )
                if version == "0.1.0":
                    self.assertIsNone(candidate)
                else:
                    self.assertEqual(candidate.tag, tag)

    def test_rejected_version_below_best_candidate_can_be_skipped(self):
        incomplete = release(
            "v0.3.0", [asset("x86_64")], published_at="2026-11-07T00:00:00Z"
        )
        candidate = update.find_candidate(
            [incomplete, complete_release("v0.4.0", version="0.4.0")], self.current
        )
        self.assertEqual(candidate.tag, "v0.4.0")

    def test_higher_rejected_version_without_timestamp_is_blocking(self):
        incomplete = release("v0.4.0", [asset("x86_64")], published_at=None)
        with self.assertRaises(update.UpdateError):
            update.find_candidate([complete_release("v0.3.0"), incomplete], self.current)

    def test_unknown_new_tag_is_checked_without_new_candidate(self):
        unknown = release("nightly-2026-11-06", [], published_at="2026-11-06T00:00:00Z")
        with self.assertRaises(update.UpdateError):
            update.find_candidate(
                [complete_release("v0.1.0", version="0.1.0"), unknown], self.current
            )

    def test_unknown_old_tag_can_be_skipped_with_and_without_new_candidate(self):
        for unknown_tag in ("legacy-release", None):
            for tag, version in (("v0.1.0", "0.1.0"), ("v0.3.0", "0.3.0")):
                with self.subTest(unknown_tag=unknown_tag, complete=tag):
                    unknown = release(unknown_tag, [], published_at="2026-11-01T00:00:00Z")
                    candidate = update.find_candidate(
                        [unknown, complete_release(tag, version=version)], self.current
                    )
                    if version == "0.1.0":
                        self.assertIsNone(candidate)
                    else:
                        self.assertEqual(candidate.tag, tag)

    def test_unknown_tag_with_unusable_timestamp_fails_closed(self):
        for timestamp in (None, "", "not-a-date", "2026-11-01"):
            for tag, version in (("v0.1.0", "0.1.0"), ("v0.3.0", "0.3.0")):
                with self.subTest(timestamp=timestamp, complete=tag):
                    unknown = release("nightly", [], published_at=timestamp)
                    with self.assertRaises(update.UpdateError):
                        update.find_candidate(
                            [unknown, complete_release(tag, version=version)], self.current
                        )

    def test_unknown_tag_without_trustworthy_reference_timestamp_fails_closed(self):
        for tag, version in (("v0.1.0", "0.1.0"), ("v0.3.0", "0.3.0")):
            with self.subTest(complete=tag):
                complete = complete_release(tag, version=version, published_at=None)
                unknown = release("legacy-release", [], published_at="2026-11-01T00:00:00Z")
                with self.assertRaises(update.UpdateError):
                    update.find_candidate([complete, unknown], self.current)

    def test_unknown_tag_uses_created_at_when_publication_time_is_missing(self):
        unknown = release("nightly", [], published_at=None)
        unknown["created_at"] = "2026-11-06T00:00:00Z"
        with self.assertRaises(update.UpdateError):
            update.find_candidate(
                [complete_release("v0.1.0", version="0.1.0"), unknown], self.current
            )

    def test_unknown_tag_timestamp_comparison_uses_actual_instants(self):
        # This is 05:00 UTC, older than the complete release at 10:00 UTC.
        unknown = release("legacy-release", [], published_at="2026-11-05T13:00:00+08:00")
        candidate = update.find_candidate([complete_release("v0.3.0"), unknown], self.current)
        self.assertEqual(candidate.tag, "v0.3.0")

    def test_rejected_drafts_are_ignored_in_both_candidate_paths(self):
        for tag, version in (("v0.1.0", "0.1.0"), ("v0.3.0", "0.3.0")):
            with self.subTest(complete=tag):
                drafts = [
                    release("v9.9.9", [], draft=True, published_at=None),
                    release("nightly", [], draft=True, published_at=None),
                ]
                candidate = update.find_candidate(
                    drafts + [complete_release(tag, version=version)], self.current
                )
                if version == "0.1.0":
                    self.assertIsNone(candidate)
                else:
                    self.assertEqual(candidate.tag, tag)


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
