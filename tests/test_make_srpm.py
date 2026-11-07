"""Offline SRPM builds must verify bytes as well as RPM header identity."""

import contextlib
import hashlib
import importlib.util
import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from dshcopr import fetch, manifest, rpmheader, specgen  # noqa: E402
from support import make_rpm, manifest_data  # noqa: E402

MODULE_SPEC = importlib.util.spec_from_file_location("make_srpm", ROOT / "scripts" / "make-srpm.py")
make_srpm = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(make_srpm)


class OfflineSrpmTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh offline srpm ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.manifest_path = self.root / "release.json"
        self.spec_path = self.root / "deepseek-harness.spec"
        self.data = manifest_data(tag="v0.3.0", version="0.3.0")
        self.blobs = {}
        for arch in manifest.ARCHES:
            blob = make_rpm({1001: "0.3.0", 1022: arch}) + b"verified payload bytes\n"
            self.blobs[arch] = blob
            self.cache_path(arch).write_bytes(blob)
            self.record_bytes(arch, blob)
        self.save_manifest_and_spec()

    def cache_path(self, arch):
        return self.cache / self.data["assets"][arch]["name"]

    def record_bytes(self, arch, blob):
        self.data["assets"][arch]["size"] = len(blob)
        self.data["assets"][arch]["sha256"] = hashlib.sha256(blob).hexdigest()

    def save_manifest_and_spec(self):
        manifest.dump(self.data, self.manifest_path)
        specgen.write(self.data, self.spec_path)

    def run_offline(self, *, error=None):
        # Even invalid cached files must remain untouched in offline mode.
        before = {path.name: path.read_bytes() for path in self.cache.iterdir()}
        stderr = io.StringIO()
        with (
            patch.object(make_srpm, "_build_srpm") as build,
            patch.object(fetch, "download") as download,
            patch.object(fetch.urllib.request, "urlopen") as network,
            patch.object(make_srpm, "_verify_metadata", wraps=make_srpm._verify_metadata) as metadata,
            contextlib.redirect_stderr(stderr),
        ):
            args = [
                "--skip-download",
                "--manifest", str(self.manifest_path),
                "--spec", str(self.spec_path),
                "--cache", str(self.cache),
                "--outdir", str(self.root / "output"),
            ]
            if error is None:
                self.assertEqual(make_srpm.main(args), 0)
                build.assert_called_once_with(
                    self.spec_path.resolve(), self.cache.resolve(), (self.root / "output").resolve()
                )
                self.assertEqual(metadata.call_count, len(manifest.ARCHES))
            else:
                with self.assertRaises(SystemExit) as raised:
                    make_srpm.main(args)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(error, stderr.getvalue())
                build.assert_not_called()
            download.assert_not_called()
            network.assert_not_called()
        after = {path.name: path.read_bytes() for path in self.cache.iterdir()}
        self.assertEqual(after, before)

    def test_verified_cache_builds_after_both_headers_are_checked(self):
        self.run_offline()

    def test_missing_architecture_fails_without_downloading(self):
        path = self.cache_path("aarch64")
        self.assertEqual(path.resolve().parent, self.cache.resolve())
        path.rename(path.with_suffix(".missing"))
        self.run_offline(error="cache is missing")

    def test_wrong_size_fails_before_build(self):
        self.cache_path("x86_64").write_bytes(self.blobs["x86_64"] + b"unexpected bytes")
        self.run_offline(error="size mismatch")

    def test_same_size_payload_corruption_fails_even_with_matching_header(self):
        arch = "aarch64"
        blob = self.blobs[arch]
        corrupted = blob[:-1] + b"X"
        self.assertEqual(len(corrupted), len(blob))
        self.cache_path(arch).write_bytes(corrupted)
        header = rpmheader.read_metadata(self.cache_path(arch))
        self.assertEqual((header.name, header.version, header.release, header.arch, header.epoch),
                         ("deepseek-harness", "0.3.0", "1", arch, 0))
        self.run_offline(error="SHA-256 mismatch")

    def test_header_only_cache_is_not_an_acceptable_asset(self):
        self.cache_path("x86_64").write_bytes(make_rpm({1001: "0.3.0"}))
        self.run_offline(error="size mismatch")

    def test_matching_checksum_does_not_bypass_header_identity(self):
        for field, value, message in (
            (1000, "different-package", "RPM header is"),
            (1001, "9.9.9", "RPM header is"),
            (1022, "aarch64", "RPM header is"),
            (1003, 1, "unexpected epoch"),
        ):
            with self.subTest(field=field):
                blob = make_rpm({1001: "0.3.0", field: value}) + b"verified payload bytes\n"
                self.cache_path("x86_64").write_bytes(blob)
                self.record_bytes("x86_64", blob)
                self.save_manifest_and_spec()
                self.run_offline(error=message)


if __name__ == "__main__":
    unittest.main()
