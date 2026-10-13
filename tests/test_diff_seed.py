#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""diff_seed.py unit tests (fix-mgh-sdr-diffgroup-coverage M14).

Builds a throwaway git repo with non-ASCII paths under the DEFAULT git config
(NEVER preset core.quotePath — the fixture must reproduce git's quoting) and
asserts: non-ASCII source files enter seed[] under their real names with no
quoted-tail pseudo entries, and deleted[] honors the same SOURCE_EXT filter as
seed[].

Run: py tests/test_diff_seed.py
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "diff_seed.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _load_mod():
    spec = importlib.util.spec_from_file_location("diff_seed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DiffSeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_diffseed_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir(parents=True)
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rel: str, text: str):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def _commit_all(self, msg: str):
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", msg)

    def test_nonascii_source_enters_seed(self):
        # M14: with git's default quotePath the non-ASCII path arrived quoted
        # (`"src/\346..."` with a glued `"` tail), the extension filter saw `.java"`
        # and the source file silently vanished from seed[].
        self._write("src/Keep.java", "class Keep { }\n")
        self._commit_all("init")
        _git(self.repo, "checkout", "-qb", "feat")
        self._write("src/妇科/患者服务.java", "class PatientService { }\n")
        self._write("src/OrderController.java", "class OrderController { }\n")
        self._write("docs/说明.md", "changed doc\n")
        self._commit_all("feat")
        seed, deleted = _load_mod().changed_files(self.repo, "master")
        self.assertIn("src/妇科/患者服务.java", seed)
        self.assertIn("src/OrderController.java", seed)
        self.assertNotIn("docs/说明.md", seed)   # non-source stays out under any name
        self.assertFalse(any(p.endswith('"') for p in seed),
                         "quoted-tail pseudo entry — quotePath still active")
        self.assertEqual(deleted, [])

    def test_deleted_nonascii_source_same_filter(self):
        # deleted[] must honor the SAME source-extension filter as seed[] (it used to
        # record everything, and quoted non-ASCII names never matched the filter's
        # intent on the seed side).
        self._write("src/妇科/旧服务.java", "class OldService { }\n")
        self._write("README.md", "readme\n")
        self._commit_all("init")
        _git(self.repo, "checkout", "-qb", "feat")
        _git(self.repo, "rm", "-q", "src/妇科/旧服务.java")
        _git(self.repo, "rm", "-q", "README.md")
        self._write("src/New.java", "class New { }\n")
        self._commit_all("feat")
        seed, deleted = _load_mod().changed_files(self.repo, "master")
        self.assertIn("src/妇科/旧服务.java", deleted)
        self.assertNotIn("README.md", deleted)   # same SOURCE_EXT filter as seed[]
        self.assertFalse(any(p.endswith('"') for p in deleted))
        self.assertIn("src/New.java", seed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
