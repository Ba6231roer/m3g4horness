#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install_opencode_plugin.py idempotent FIXED-FILE-SET placement (R5.7 deliverable, opencode
analog of install_hook.py; harden-mgh-opencode-hook-parity §4.1 + native dispatch tool).

The installer manages a FIXED two-file set (guard block_adhoc_scripts.ts + dispatch
mgh_dispatch.ts). Asserts: place writes BOTH files; double-place is idempotent (present, no
rewrite); the user's existing plugins are preserved; --remove takes both back out; a source
dir missing either file exits 1 BEFORE any write; placement without --source-dir exits 2.
Plus (fix-mgh-opencode2-plugin-compat + native dispatch tool): each INSTALLED copy satisfies
its own 2.x module-contract shape assertions (same sources of truth as
tests/test_opencode_hook_parity.py) — a skewed or stale install must not reintroduce a
silently-rejected file.
Run: py tests/test_install_opencode_plugin.py
"""
import importlib.util, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"
SRC_DIR = HERE.parent / "releases" / "opencode" / "plugins"
SRC = SRC_DIR / "block_adhoc_scripts.ts"          # guard (set member 1)
DISPATCH = SRC_DIR / "mgh_dispatch.ts"            # dispatch (set member 2)
FILES = ("block_adhoc_scripts.ts", "mgh_dispatch.ts")


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

    def _run(self, plugins_dir, remove=False, source_dir=str(SRC_DIR)):
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(plugins_dir)]
        if remove:
            argv.append("--remove")
        elif source_dir is not None:
            argv += ["--source-dir", source_dir]
        old, sys.argv = sys.argv, argv
        old_out, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            return self.m.main()
        finally:
            sys.argv = old
            sys.stdout.close()
            sys.stdout = old_out

    def test_place_creates_both_plugin_files(self):
        self.assertEqual(self._run(self.pdir), 0)
        for name in FILES:
            self.assertTrue((self.pdir / name).is_file(), f"{name} missing after place")

    def test_double_place_is_idempotent(self):
        self._run(self.pdir)
        before = {n: (self.pdir / n).read_text(encoding="utf-8") for n in FILES}
        self.assertEqual(self._run(self.pdir), 0)
        for n in FILES:
            self.assertEqual(before[n], (self.pdir / n).read_text(encoding="utf-8"),
                             f"{n} rewritten on double place (present, not written)")

    def test_preserves_user_existing_plugin(self):
        (self.pdir).mkdir(parents=True, exist_ok=True)
        user = self.pdir / "user_other.ts"
        user.write_text("// my plugin\n", encoding="utf-8")
        self._run(self.pdir)
        self.assertTrue(user.is_file())
        self.assertEqual(user.read_text(encoding="utf-8"), "// my plugin\n")  # untouched
        for n in FILES:
            self.assertTrue((self.pdir / n).is_file(), f"{n} missing (ours added)")

    def test_remove_takes_both_out(self):
        self._run(self.pdir)
        user = self.pdir / "user_other.ts"
        user.write_text("// my plugin\n", encoding="utf-8")
        self.assertEqual(self._run(self.pdir, remove=True), 0)
        for n in FILES:
            self.assertFalse((self.pdir / n).exists(), f"{n} still present after remove")
        self.assertTrue(user.is_file())                                   # user's kept

    def test_missing_source_file_exits_one_before_any_write(self):
        skewed = self.d / "skewed_src"
        skewed.mkdir()
        (skewed / FILES[0]).write_text("// guard only\n", encoding="utf-8")
        self.assertEqual(self._run(self.pdir, source_dir=str(skewed)), 1)
        for n in FILES:
            self.assertFalse((self.pdir / n).exists(),
                             "a skewed source tree must not leave a half-installed set")

    def test_placement_without_source_dir_exits_two(self):
        self.assertEqual(self._run(self.pdir, source_dir=None), 2)

    def test_stdout_contract_per_file_action(self):
        import contextlib, io, json
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(self.pdir),
                "--source-dir", str(SRC_DIR)]
        old, sys.argv = sys.argv, argv
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = self.m.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["plugins_dir"], str(self.pdir))
        self.assertEqual([f["plugin"] for f in payload["files"]],
                         ["block_adhoc_scripts", "mgh_dispatch"])
        self.assertTrue(all(f["action"] in ("written", "present", "removed", "absent")
                            for f in payload["files"]))


class TestInstalledCopyShape(unittest.TestCase):
    """fix-mgh-opencode2-plugin-compat + native dispatch tool: EACH INSTALLED copy must
    satisfy its own 2.x module-contract shape assertions. opencode rejects a wrong-shaped
    plugin with only a WARN (fail-soft, the plugin silently never loads), so a stale/skewed
    install is caught here at install-test time via the same shared assertions the repo
    sources pass in CI."""

    def setUp(self):
        self.m = _load()
        self.parity = _load_parity()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_iop_shape_"))
        self.pdir = self.d / ".opencode" / "plugins"

    def _place(self):
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(self.pdir),
                "--source-dir", str(SRC_DIR)]
        old, sys.argv = sys.argv, argv
        old_out, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            code = self.m.main()
        finally:
            sys.argv = old
            sys.stdout.close()
            sys.stdout = old_out
        self.assertEqual(code, 0)

    def test_installed_guard_copy_satisfies_v2_module_shape(self):
        self._place()
        self.parity.assert_shim_v2_shape(
            (self.pdir / "block_adhoc_scripts.ts").read_text(encoding="utf-8"))

    def test_installed_dispatch_copy_satisfies_dispatch_shape(self):
        self._place()
        self.parity.assert_dispatch_plugin_shape(
            (self.pdir / "mgh_dispatch.ts").read_text(encoding="utf-8"))

    def test_one_x_shaped_source_installs_but_fails_the_shape_assertion(self):
        # the installer is a pure copier (filename + bytes unchanged) — placing a 1.x-shaped
        # file still exits 0, but the shape assertion must trip on the installed copy: the
        # loader would reject it (WARN) and the plugin would silently never load.
        legacy = self.d / "legacy_src"
        legacy.mkdir()
        (legacy / "block_adhoc_scripts.ts").write_text(
            'export const BlockAdhocScripts = async (ctx: { client?: any }) => ({\n'
            '  "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {},\n'
            '})\n', encoding="utf-8")
        (legacy / "mgh_dispatch.ts").write_text("// stub\n", encoding="utf-8")
        self.assertEqual(self._place_or_code(legacy), 0)
        with self.assertRaises(AssertionError):
            self.parity.assert_shim_v2_shape(
                (self.pdir / "block_adhoc_scripts.ts").read_text(encoding="utf-8"))

    def _place_or_code(self, source_dir):
        argv = ["install_opencode_plugin.py", "--plugins-dir", str(self.pdir),
                "--source-dir", str(source_dir)]
        old, sys.argv = sys.argv, argv
        old_out, sys.stdout = sys.stdout, open(os.devnull, "w")
        try:
            return self.m.main()
        finally:
            sys.argv = old
            sys.stdout.close()
            sys.stdout = old_out


if __name__ == "__main__":
    unittest.main(verbosity=2)
