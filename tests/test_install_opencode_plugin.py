#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install_opencode_plugin.py idempotent .ts placement (R5.7 deliverable, opencode analog
of install_hook.py; harden-mgh-opencode-hook-parity §4.1).

Asserts: place writes the file; double-place is idempotent (present, no rewrite); the user's
existing plugins are preserved; --remove takes ours back out; missing source exits 1. Plus
(fix-mgh-opencode2-plugin-compat): the INSTALLED copy satisfies the opencode 2.x module-contract
shape assertions (same source of truth as tests/test_opencode_hook_parity.py) — a skewed or
stale install must not reintroduce a silently-rejected 1.x-shaped file.
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


def _load_parity():
    """The shared shim-shape assertions live with the parity tests (single source of truth);
    import that module by path (same standalone-script convention as the tools modules)."""
    spec = importlib.util.spec_from_file_location("test_opencode_hook_parity", HERE / "test_opencode_hook_parity.py")
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


class TestInstalledCopyV2Shape(unittest.TestCase):
    """fix-mgh-opencode2-plugin-compat: the INSTALLED copy must satisfy the 2.x module-contract
    shape assertions. opencode rejects a 1.x-shaped plugin with only a WARN (fail-soft, the
    guard silently never loads), so a stale/skewed install is caught here at install-test time
    via the same shared assertion the repo shim passes in CI."""

    def setUp(self):
        self.m = _load()
        self.parity = _load_parity()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_iop_shape_"))
        self.pdir = self.d / ".opencode" / "plugins"

    def _run(self, plugins_dir, source=str(SRC)):
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(plugins_dir), "--source", source]
        old, sys.argv = sys.argv, argv
        old_out, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            return self.m.main()
        finally:
            sys.argv = old
            sys.stdout.close()
            sys.stdout = old_out

    def _installed_text(self):
        return (self.pdir / "block_adhoc_scripts.ts").read_text(encoding="utf-8")

    def test_installed_copy_satisfies_v2_module_shape(self):
        self.assertEqual(self._run(self.pdir), 0)
        self.parity.assert_shim_v2_shape(self._installed_text())

    def test_one_x_shaped_source_installs_but_fails_the_shape_assertion(self):
        # the installer is a pure copier (filename + bytes unchanged) — placing a 1.x-shaped
        # file still exits 0, but the shape assertion must trip on the installed copy: the
        # loader would reject it (WARN) and the guard would silently never load.
        legacy = self.d / "legacy.ts"
        legacy.write_text(
            'export const BlockAdhocScripts = async (ctx: { client?: any }) => ({\n'
            '  "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {},\n'
            '})\n',
            encoding="utf-8")
        self.assertEqual(self._run(self.pdir, source=str(legacy)), 0)
        with self.assertRaises(AssertionError):
            self.parity.assert_shim_v2_shape(self._installed_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
