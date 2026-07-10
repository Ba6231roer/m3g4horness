#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install_opencode_plugin.py idempotent .ts placement (R5.7 deliverable, opencode analog
of install_hook.py; harden-mgh-opencode-hook-parity §4.1).

Asserts: place writes the file; double-place is idempotent (present, no rewrite); the user's
existing plugins are preserved; --remove takes ours back out; missing source exits 1.
Run: py tests/test_install_opencode_plugin.py
"""
import importlib.util, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
SRC = HERE.parent / "releases" / "opencode" / "plugins" / "block_adhoc_scripts.ts"


def _load():
    spec = importlib.util.spec_from_file_location("install_opencode_plugin", TOOLS / "install_opencode_plugin.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInstallOpencodePlugin(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_iop_"))
        self.pdir = self.d / ".opencode" / "plugins"

    def _run(self, plugins_dir, remove=False, source=str(SRC)):
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(plugins_dir), "--source", source]
        if remove:
            argv.append("--remove")
        old, sys.argv = sys.argv, argv
        old_out, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            return self.m.main()
        finally:
            sys.argv = old
            sys.stdout.close()
            sys.stdout = old_out

    def test_place_creates_plugin_file(self):
        self.assertEqual(self._run(self.pdir), 0)
        self.assertTrue((self.pdir / "block_adhoc_scripts.ts").is_file())

    def test_double_place_is_idempotent(self):
        self._run(self.pdir)
        before = (self.pdir / "block_adhoc_scripts.ts").read_text(encoding="utf-8")
        self.assertEqual(self._run(self.pdir), 0)
        after = (self.pdir / "block_adhoc_scripts.ts").read_text(encoding="utf-8")
        self.assertEqual(before, after)  # unchanged (present), not duplicated/rewritten

    def test_preserves_user_existing_plugin(self):
        (self.pdir).mkdir(parents=True, exist_ok=True)
        user = self.pdir / "user_other.ts"
        user.write_text("// my plugin\n", encoding="utf-8")
        self._run(self.pdir)
        self.assertTrue(user.is_file())
        self.assertEqual(user.read_text(encoding="utf-8"), "// my plugin\n")  # untouched
        self.assertTrue((self.pdir / "block_adhoc_scripts.ts").is_file())     # ours added

    def test_remove_takes_ours_out(self):
        self._run(self.pdir)
        user = self.pdir / "user_other.ts"
        user.write_text("// my plugin\n", encoding="utf-8")
        self.assertEqual(self._run(self.pdir, remove=True), 0)
        self.assertFalse((self.pdir / "block_adhoc_scripts.ts").exists())  # ours gone
        self.assertTrue(user.is_file())                                    # user's kept

    def test_missing_source_exits_one(self):
        self.assertEqual(self._run(self.pdir, source=str(self.d / "nope.ts")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
