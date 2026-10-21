#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install.sh special-auth retirement (R5.8 fail-soft family).

fix-mgh-sdr-native-default-dispatch 7.6: the special-auth note is a PROJECT-owned
optional entry (`<target>/.mgh/special-auth.md`), never an install artifact. The
installer has a THREE-STATE contract:

  1. package-side source present → still NOT copied into the target;
  2. stale `<dest>/mgh-core/mgh-special-auth.md` from an older version → removed,
     output carries the migration hint (move it to `<target>/.mgh/`);
  3. neither → byte-identical to a generic install (no mention, no file).

Runs the REAL `install.sh --opencode` into a scratch target (fast path: no
dsh wiring). Skipped when bash is unavailable."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOC_NAME = "mgh-special-auth.md"


class InstallSpecialAuthRetirement(unittest.TestCase):
    SRC = ROOT / DOC_NAME

    def setUp(self):
        self.bash = shutil.which("bash")
        if not self.bash:
            self.skipTest("bash not on PATH")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_auth_install_"))
        self.target = self.d / "proj"
        self.target.mkdir()
        self.saved_src = None
        if self.SRC.exists():  # never touch the maintainer's real copy
            self.saved_src = self.d / "saved-src.md"
            shutil.copy2(self.SRC, self.saved_src)
            self.SRC.unlink()

    def tearDown(self):
        if self.SRC.exists():
            self.SRC.unlink(missing_ok=True)
        if self.saved_src is not None:
            shutil.copy2(self.saved_src, self.SRC)
        shutil.rmtree(self.d, ignore_errors=True)

    def _install(self):
        return subprocess.run(
            [self.bash, "install.sh", "--opencode", str(self.target)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300)

    def _dst(self) -> Path:
        return self.target / ".opencode" / "mgh-core" / DOC_NAME

    def test_source_present_is_not_copied(self):
        self.SRC.write_text("# guide\n", encoding="utf-8")
        r = self._install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertFalse(self._dst().exists(),
                         "the package-side doc must NEVER be installed")
        self.assertNotIn("installed special-auth", r.stdout)

    def test_stale_install_tree_copy_is_removed_with_hint(self):
        self._dst().parent.mkdir(parents=True, exist_ok=True)
        self._dst().write_text("legacy", encoding="utf-8")
        r = self._install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertFalse(self._dst().exists())
        self.assertIn("removed legacy install-tree special-auth doc", r.stdout)
        self.assertIn(".mgh/special-auth.md", r.stdout)

    def test_no_source_no_copy_is_silent(self):
        r = self._install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertFalse(self._dst().exists())
        self.assertNotIn("special-auth", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
