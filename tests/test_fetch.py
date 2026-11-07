"""Local verification and mocked cache/download behavior; never use network."""

import hashlib
import io
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dshcopr import fetch  # noqa: E402


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh fetch ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.path = self.root / "asset.rpm"
        self.blob = b"verified upstream asset bytes\n"
        self.expected = {
            "expected_size": len(self.blob),
            "expected_sha256": hashlib.sha256(self.blob).hexdigest(),
        }

    def verify(self):
        return fetch.verify_file(self.path, **self.expected)

    def download(self):
        return fetch.download(
            "https://github.com/example/repo/releases/download/v1/asset.rpm",
            self.path,
            **self.expected,
            retries=1,
            log=lambda message: None,
        )

    def response(self):
        response = io.BytesIO(self.blob)
        response.headers = {"Content-Length": str(len(self.blob))}
        return response

    def test_verify_accepts_expected_bytes_without_network(self):
        self.path.write_bytes(self.blob)
        with patch.object(fetch.urllib.request, "urlopen") as network:
            self.assertEqual(self.verify(), self.path)
            network.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.blob)

    def test_verify_wrong_size_fails_without_hashing_or_changing_file(self):
        self.path.write_bytes(b"truncated")
        with patch.object(fetch, "sha256_file") as digest:
            with self.assertRaisesRegex(fetch.FetchError, "size mismatch"):
                self.verify()
            digest.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"truncated")

    def test_verify_wrong_digest_preserves_file(self):
        corrupted = b"X" + self.blob[1:]
        self.path.write_bytes(corrupted)
        with self.assertRaisesRegex(fetch.FetchError, "SHA-256 mismatch"):
            self.verify()
        self.assertEqual(self.path.read_bytes(), corrupted)

    def test_verify_missing_file_reports_error_without_creating_file(self):
        with self.assertRaisesRegex(fetch.FetchError, "cannot verify file"):
            self.verify()
        self.assertFalse(self.path.exists())

    def test_verify_read_error_is_a_fetch_error(self):
        self.path.write_bytes(self.blob)
        with patch.object(fetch, "sha256_file", side_effect=PermissionError("not readable")):
            with self.assertRaisesRegex(fetch.FetchError, "cannot verify file.*not readable"):
                self.verify()
        self.assertEqual(self.path.read_bytes(), self.blob)

    def test_verified_cache_uses_common_verifier_without_network(self):
        self.path.write_bytes(self.blob)
        with (
            patch.object(fetch, "verify_file", wraps=fetch.verify_file) as verify,
            patch.object(fetch, "sha256_file", wraps=fetch.sha256_file) as digest,
            patch.object(fetch.urllib.request, "urlopen") as network,
        ):
            self.assertEqual(self.download(), self.path)
            verify.assert_called_once_with(self.path, **self.expected)
            digest.assert_called_once_with(self.path)
            network.assert_not_called()
        self.assertEqual(self.path.read_bytes(), self.blob)

    def test_invalid_cached_size_or_digest_is_refetched(self):
        for corrupted in (b"short", b"X" + self.blob[1:]):
            with self.subTest(size=len(corrupted)):
                self.path.write_bytes(corrupted)
                with (
                    patch.object(fetch, "verify_file", wraps=fetch.verify_file) as verify,
                    patch.object(fetch.urllib.request, "urlopen", return_value=self.response()) as network,
                ):
                    self.assertEqual(self.download(), self.path)
                    verify.assert_called_once_with(self.path, **self.expected)
                    network.assert_called_once()
                self.assertEqual(self.path.read_bytes(), self.blob)
                self.assertFalse(self.path.with_name(self.path.name + ".part").exists())

    def test_new_download_uses_stream_digest_without_second_file_hash(self):
        with (
            patch.object(fetch, "verify_file") as verify,
            patch.object(fetch, "sha256_file") as digest,
            patch.object(fetch.urllib.request, "urlopen", return_value=self.response()) as network,
        ):
            self.assertEqual(self.download(), self.path)
            verify.assert_not_called()
            digest.assert_not_called()
            network.assert_called_once()
        self.assertEqual(self.path.read_bytes(), self.blob)


if __name__ == "__main__":
    unittest.main()
