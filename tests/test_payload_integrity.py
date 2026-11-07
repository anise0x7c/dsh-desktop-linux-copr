"""Execute the spec's real checksum commands against isolated staging trees."""

import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packaging" / "deepseek-harness.spec.tmpl"


class PayloadIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dsh payload integrity ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.workdir = self.root / "extracted"
        self.buildroot = self.root / "buildroot"
        self.builddir = self.root / "build directory"
        for directory in (self.workdir, self.buildroot, self.builddir):
            directory.mkdir()
        # An absolute application path with a real, unrelated host installation.
        # Both staged copies mirror this path without requiring access to /opt.
        self.appdir = self.root / "host" / "DeepSeek Harness"
        self.relative_appdir = self.appdir.relative_to(self.appdir.anchor)
        self.source = self.workdir / self.relative_appdir
        self.destination = self.buildroot / self.relative_appdir
        self.appdir.mkdir(parents=True)
        self.source.mkdir(parents=True)
        for name in ("application binary", "a file\nwith a newline"):
            (self.appdir / name).write_bytes(b"unrelated host contents\n")
            (self.source / name).write_bytes(b"verified upstream contents\n")
        shutil.copytree(self.source, self.destination)

        template = TEMPLATE.read_text(encoding="utf-8")
        start = template.index("# The installed payload must be byte-for-byte identical")
        end = template.index("list_symlinks() {", start)
        self.commands = template[start:end].replace(
            "%{_builddir}", str(self.builddir)
        ).replace("%{buildroot}", str(self.buildroot))

    def run_verification(self, *, failing_tool=None):
        env = dict(os.environ, workdir=str(self.workdir), appdir_path=str(self.appdir))
        if failing_tool is not None:
            tools = self.root / "tools"
            tools.mkdir(exist_ok=True)
            tool = tools / failing_tool
            tool.write_text("#!/bin/sh\nexit 73\n", encoding="utf-8")
            tool.chmod(0o755)
            env["PATH"] = str(tools) + os.pathsep + env["PATH"]
        # Fedora's RPM /bin/sh -e is Bash.  Select Bash explicitly so these
        # tests also run on Ubuntu CI, where /bin/sh is Dash instead.
        # The checksum fragment itself must propagate pipeline failures.
        return subprocess.run(
            ["bash", "-e", "-c", self.commands],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_identical_staged_payload_passes_with_relative_names(self):
        result = self.run_verification()
        self.assertEqual(result.returncode, 0, result.stderr)
        checksums = (self.builddir / "payload.sha256").read_text(encoding="utf-8")
        self.assertIn("./" + str(self.relative_appdir), checksums)
        self.assertIn("application binary", checksums)
        self.assertNotIn("  " + str(self.appdir), checksums)
        self.assertNotIn("  -\n", checksums)

    def test_identical_staged_payload_passes_without_host_installation(self):
        self.assertEqual(self.appdir.resolve(), self.root / "host" / "DeepSeek Harness")
        self.appdir.rename(self.appdir.with_name("absent host backup"))
        result = self.run_verification()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_workdir_fails(self):
        self.assertEqual(self.workdir.resolve(), self.root / "extracted")
        self.workdir.rename(self.workdir.with_name("missing workdir backup"))
        result = self.run_verification()
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_corrupted_staged_payload_fails_even_with_host_copy(self):
        (self.destination / "application binary").write_bytes(b"CORRUPTED\n")
        result = self.run_verification()
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_missing_source_directory_fails_even_with_host_copy(self):
        # Move only this test's verified temporary staging directory.
        self.assertEqual(self.source.resolve(), self.workdir / self.relative_appdir)
        self.source.rename(self.source.with_name("missing source backup"))
        result = self.run_verification()
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_empty_source_directory_fails(self):
        self.assertEqual(self.source.resolve(), self.workdir / self.relative_appdir)
        self.source.rename(self.source.with_name("empty source backup"))
        self.source.mkdir()
        result = self.run_verification()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("no regular files", result.stderr)

    def test_missing_buildroot_file_fails(self):
        path = self.destination / "application binary"
        self.assertEqual(path.resolve(), self.buildroot / self.relative_appdir / path.name)
        path.rename(path.with_name("missing destination backup"))
        result = self.run_verification()
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_checksum_pipeline_tool_failures_are_not_masked(self):
        for tool in ("find", "sort", "xargs", "sha256sum"):
            with self.subTest(tool=tool):
                result = self.run_verification(failing_tool=tool)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                stub = self.root / "tools" / tool
                self.assertEqual(stub.resolve(), self.root / "tools" / tool)
                stub.unlink()


if __name__ == "__main__":
    unittest.main()
