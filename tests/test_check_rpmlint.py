import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-rpmlint.py"

HEADER = """\
============================ rpmlint session starts ============================
rpmlint: 2.9.0
configuration:
    /usr/share/rpmlint/configdefaults.toml
checks: 32, packages: 1

"""


class CheckRpmlintTest(unittest.TestCase):
    def run_checker(self, report: str, allowed: list[str]) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = pathlib.Path(tmp)
            (tmpdir / "report.txt").write_text(report, encoding="utf-8")
            (tmpdir / "exceptions.txt").write_text("\n".join(allowed) + "\n", encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    str(tmpdir / "report.txt"),
                    "--exceptions",
                    str(tmpdir / "exceptions.txt"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_allowed_findings_pass(self):
        report = HEADER + (
            "deepseek-harness.x86_64: W: dir-or-file-in-opt /opt/DeepSeek Harness/x\n"
            "deepseek-harness.x86_64: E: binary-or-shlib-defines-rpath /opt/DeepSeek Harness/y (RUNPATH: $ORIGIN)\n"
            " 1 packages and 0 specfiles checked; 1 errors, 1 warnings, 1 filtered, 1 badness; has taken 1.0 s\n"
        )
        result = self.run_checker(report, ["dir-or-file-in-opt", "binary-or-shlib-defines-rpath"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unlisted_finding_fails(self):
        report = HEADER + "deepseek-harness.x86_64: E: missing-something /opt/DeepSeek Harness/x\n"
        result = self.run_checker(report, [])
        self.assertEqual(result.returncode, 1)
        self.assertIn("missing-something", result.stderr)

    def test_unparseable_line_fails(self):
        report = HEADER + "this is not rpmlint output\n"
        result = self.run_checker(report, [])
        self.assertEqual(result.returncode, 2)

    def test_percent_in_check_name_is_supported(self):
        report = "deepseek-harness.x86_64: W: dangerous-command-in-%posttrans ln\n"
        result = self.run_checker(report, ["dangerous-command-in-%posttrans"])
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
