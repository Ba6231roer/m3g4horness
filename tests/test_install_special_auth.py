#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install.sh special-auth doc copy convergence (R5.8 fail-soft family).

The optional, maintainer-carried `mgh-special-auth.md` (NOT in git) converges
to `<dest>/mgh-core/mgh-special-auth.md` with a THREE-STATE contract:

  1. source present → target copy installed, install output discloses it;
  2. source absent, stale target copy exists → copy removed, output discloses;
  3. source absent, no target copy → byte-identical to a generic install (no
     mention, no file, self-check never warns).

Runs the REAL `install.sh --opencode` into a scratch target (fast path: no
dsh wiring). Skipped when bash is unavailable."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOC_NAME = "mgh-special-auth.md"


class InstallSpecialAuthConvergence(unittest.TestCase):
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
        # restore the maintainer's real copy exactly as found
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

    def test_three_state_convergence(self):
        # state 3: no source, no target copy → generic install, no mention
        r = self._install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertFalse(self._dst().exists())
        self.assertNotIn("special-auth", r.stdout)
        # state 1: source present → installed + disclosed
        self.SRC.write_text("# guide\n", encoding="utf-8")
        try:
            r = self._install()
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertTrue(self._dst().is_file())
            self.assertEqual(self._dst().read_text(encoding="utf-8"),
                             "# guide\n")
            self.assertIn("special-auth deployment doc", r.stdout)
        finally:
            self.SRC.unlink(missing_ok=True)
        # state 2: source gone again, stale target copy → removed + disclosed
        r = self._install()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertFalse(self._dst().exists())
        self.assertIn("stale special-auth deployment doc", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
