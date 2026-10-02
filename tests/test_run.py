"""Exercise the CLI's revision selection without provisioning a VM."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RemoteRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copy2(Path(__file__).resolve().parents[1] / "run", self.root / "run")
        self.git("init", "--quiet", "--initial-branch=feature")
        self.git("add", "run")
        self.git(
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "-m",
            "Initial CLI",
        )
        binaries = self.root / "bin"
        binaries.mkdir()
        uv = binaries / "uv"
        uv.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "print(json.dumps({'ref': os.environ['RUN_REF'], "
            "'name': os.environ['RUN_NAME'], 'args': sys.argv[1:]}))\n"
        )
        uv.chmod(0o755)
        self.environment = {**os.environ, "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}"}
        self.environment.pop("RUN_REF", None)

    def git(self, *arguments):
        return subprocess.check_output(["git", *arguments], cwd=self.root, text=True).strip()

    def run_remote(self):
        output = subprocess.check_output(
            ["./run", "up", "remote", "demo"], cwd=self.root, env=self.environment, text=True
        )
        result = json.loads(output)
        self.assertEqual(result["name"], "demo")
        self.assertEqual(
            result["args"][:6], ["run", "--frozen", "python", "-m", "runner.remote", "up"]
        )
        return result["ref"]

    def test_defaults_to_checked_out_commit_on_a_feature_branch(self):
        self.assertEqual(self.run_remote(), self.git("rev-parse", "HEAD"))

    def test_defaults_to_checked_out_commit_with_detached_head(self):
        self.git("checkout", "--quiet", "--detach")
        self.assertEqual(self.run_remote(), self.git("rev-parse", "HEAD"))

    def test_preserves_explicit_revision_override(self):
        for revision in ("main", "another/branch", "a" * 40):
            with self.subTest(revision=revision):
                self.environment["RUN_REF"] = revision
                self.assertEqual(self.run_remote(), revision)


if __name__ == "__main__":
    unittest.main()
