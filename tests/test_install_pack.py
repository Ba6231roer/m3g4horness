#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install.sh --pack end-to-end (add-mgh-opencode-pack).

Really runs `bash install.sh --pack` (skipped when bash is unavailable): asserts
the versioned default zip name, the top-level closed set (SKILL.md / .opencode /
.mgh-sra), key assets per tree, the lazy SKILL.md shape, zero bytecode entries,
the fail-loud rejections (claude / dsh / --no-enforce-hook / positional target /
empty --pack= / missing or empty VERSION), the completeness gate on a trimmed
repo copy (missing plugin -> exit 2, staging kept), bytecode pruning (pack AND
plain install), no SKILL.md on a plain install, and byte equivalence between
"extract the zip" and "run the installer" (difference = SKILL.md only).

A py->python forwarding shim is prepended to PATH so the suite also runs where
the `py` launcher is a broken Store placeholder (maintainer-machine note).
Slow file (~1 min): seven real install/pack flows.
Run: py tests/test_install_pack.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
COMMANDS = ("mgh-blst", "mgh-init", "mgh-sast", "mgh-sdr", "mgh-sra", "mgh-srr", "mgh-ut-init")
PLUGINS = ("block_adhoc_scripts.ts", "mgh_dispatch.ts")
AGENT_SPOT = ("init-scout-native", "init-induct-native", "init-synthesis-native",
              "init-scout-merge-native", "init-rulewriter-native",
              "init-scout-fanout", "sdr-review-native")
SCRIPT_SPOT = ("discover_controls.py", "fanout_runner.py", "emit_native_plan.py",
               "env_profile.py", "block_adhoc_scripts.py")
FRAGMENT_SPOT = ("sdr-native-dispatch.md", "init-scout-native-dispatch.md",
                 "init-aggregate-native-dispatch.md")

_CACHE = {"shim": None, "pack": None}


def _shim_dir():
    """py->interpreter forwarding shim, first on PATH for install.sh subprocesses.

    Forwards to sys.executable (the interpreter running this suite) — robust on
    machines where `py` is a broken Store placeholder and `python` is the silent
    Store alias alike."""
    if _CACHE["shim"] is None:
        d = Path(tempfile.mkdtemp(prefix="mgh_pyshim_"))
        (d / "py").write_text('#!/usr/bin/env bash\nexec "%s" "$@"\n'
                              % str(sys.executable).replace("\\", "/"), encoding="utf-8")
        _CACHE["shim"] = d
    return _CACHE["shim"]


def _env():
    return dict(os.environ, PATH="%s%s%s" % (_shim_dir(), os.pathsep,
                                             os.environ.get("PATH", "")))


def _run(args, cwd=ROOT, timeout=600):
    bash = shutil.which("bash")
    if not bash:
        raise unittest.SkipTest("bash not on PATH")
    return subprocess.run([bash, *args], cwd=str(cwd), env=_env(),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def _pack(out_zip, cwd=ROOT, extra=()):
    return _run(["install.sh", "--pack=%s" % out_zip, *extra], cwd=cwd)


def _pack_real_once():
    """One shared real-repo pack run for the read-only assertion classes."""
    if _CACHE["pack"] is None:
        d = Path(tempfile.mkdtemp(prefix="mgh_pack_"))
        out = d / "out.zip"
        r = _pack(out)
        if r.returncode != 0:
            raise AssertionError("shared real-repo pack run failed:\n%s" % r.stderr[-1500:])
        _CACHE["pack"] = (out, r)
    return _CACHE["pack"]


def _repo_lite(prefix):
    """Trimmed repo copy (no .git/openspec/docs/tests) for destructive scenarios."""
    lite = Path(tempfile.mkdtemp(prefix=prefix))
    shutil.copy2(ROOT / "install.sh", lite / "install.sh")
    shutil.copy2(ROOT / "VERSION", lite / "VERSION")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(ROOT / "core", lite / "core", ignore=ignore)
    (lite / "releases").mkdir()
    shutil.copytree(ROOT / "releases" / "opencode", lite / "releases" / "opencode",
                    ignore=ignore)
    shutil.copytree(ROOT / "tools", lite / "tools", ignore=ignore)
    return lite


def _bytecode_names(names):
    return [n for n in names if "__pycache__" in n or n.lower().endswith((".pyc", ".pyo"))]


def _rel_files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


class TestPackStructure(unittest.TestCase):
    """Shared real-repo pack run: structure, key assets, SKILL.md, bytecode."""

    @classmethod
    def setUpClass(cls):
        cls.zip_path, cls.result = _pack_real_once()
        with zipfile.ZipFile(cls.zip_path) as z:
            cls.names = z.namelist()

    def test_explicit_out_path_receives_zip(self):
        self.assertTrue(self.zip_path.is_file())
        self.assertIn("packed opencode release", self.result.stdout)

    def test_top_level_closed_set(self):
        top = {n.split("/")[0] for n in self.names}
        self.assertEqual(top, {"SKILL.md", ".opencode", ".mgh-sra"})

    def test_command_closed_set(self):
        for c in COMMANDS:
            self.assertIn(".opencode/command/%s.md" % c, self.names)

    def test_agent_hook_plugin_assets(self):
        for a in AGENT_SPOT:
            self.assertIn(".opencode/agent/%s.md" % a, self.names)
        self.assertIn(".opencode/hooks/block_adhoc_scripts.py", self.names)
        plugins = {n[len(".opencode/plugins/"):] for n in self.names
                   if n.startswith(".opencode/plugins/")}
        self.assertEqual(plugins, set(PLUGINS))

    def test_mgh_core_assets(self):
        for s in SCRIPT_SPOT:
            self.assertIn(".opencode/mgh-core/scripts/%s" % s, self.names)
        self.assertTrue(any(n.startswith(".opencode/mgh-core/contracts/") for n in self.names))
        for f in FRAGMENT_SPOT:
            self.assertIn(".opencode/mgh-core/prompts/fragments/%s" % f, self.names)

    def test_mgh_sra_template(self):
        self.assertIn(".mgh-sra/sensitive_catalog.json.example", self.names)

    def test_skill_md_shape(self):
        with zipfile.ZipFile(self.zip_path) as z:
            text = z.read("SKILL.md").decode("utf-8")
        self.assertIn("name: m3g4horness", text)
        self.assertRegex(text, r"(?m)^description: \S")
        self.assertIn("可删除", text)
        self.assertIn("非功能入口", text)

    def test_zero_bytecode_entries(self):
        self.assertEqual(_bytecode_names(self.names), [])

    def test_default_name_carries_version(self):
        d = Path(tempfile.mkdtemp(prefix="mgh_packname_"))
        script = str(ROOT / "install.sh").replace("\\", "/")
        r = _run([script, "--pack"], cwd=d)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        expected = d / ("m3g4horness-%s-opencode.zip" % VERSION)
        self.assertTrue(expected.is_file(), str(sorted(p.name for p in d.iterdir())))


class TestPackFailLoud(unittest.TestCase):
    """Early rejections: exit 2 before any staging/zip work."""

    def _reject(self, extra, needle, cwd=ROOT):
        d = Path(tempfile.mkdtemp(prefix="mgh_reject_"))
        r = _run(["install.sh", "--pack=%s" % (d / "out.zip"), *extra], cwd=cwd)
        self.assertEqual(r.returncode, 2, r.stderr[-500:])
        self.assertIn(needle, r.stderr)
        self.assertFalse((d / "out.zip").exists())

    def test_claude_rejected(self):
        self._reject(["--claude"], "opencode face only")

    def test_dsh_rejected(self):
        self._reject(["--dsh"], "opencode face only")

    def test_no_enforce_hook_rejected(self):
        self._reject(["--no-enforce-hook"], "drop --no-enforce-hook")

    def test_positional_target_rejected(self):
        self._reject([str(ROOT)], "target_project_dir")

    def test_empty_pack_value_rejected(self):
        d = Path(tempfile.mkdtemp(prefix="mgh_reject2_"))
        script = str(ROOT / "install.sh").replace("\\", "/")
        r = _run([script, "--pack="], cwd=d)
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs an output zip path", r.stderr)

    def test_version_empty_rejected(self):
        vpath = ROOT / "VERSION"
        orig = vpath.read_bytes()
        vpath.write_bytes(b"")
        try:
            self._reject([], "VERSION file is empty")
        finally:
            vpath.write_bytes(orig)

    def test_version_missing_rejected(self):
        vpath = ROOT / "VERSION"
        backup = vpath.with_suffix(".bak_test")
        shutil.move(str(vpath), str(backup))
        try:
            self._reject([], "VERSION file missing")
        finally:
            shutil.move(str(backup), str(vpath))


class TestPackGateLite(unittest.TestCase):
    """Dynamic gate + pruning coverage on trimmed repo copies (no repo mutation)."""

    def test_control_pack_succeeds_on_lite(self):
        lite = _repo_lite("mgh_lite_ctl_")
        out = lite / "out.zip"
        r = _pack(out, cwd=lite)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertTrue(out.is_file())

    def test_missing_plugin_fails_gate_and_keeps_staging(self):
        lite = _repo_lite("mgh_lite_gate_")
        (lite / "releases" / "opencode" / "plugins" / "mgh_dispatch.ts").unlink()
        out = lite / "out.zip"
        r = _pack(out, cwd=lite)
        self.assertEqual(r.returncode, 2)
        self.assertIn("pack gate", r.stderr)
        self.assertIn("mgh_dispatch.ts", r.stderr)
        self.assertIn("staging kept at", r.stderr)
        self.assertFalse(out.exists())

    def test_loose_pyc_pruned_from_pack(self):
        lite = _repo_lite("mgh_lite_pyc_")
        hooks = lite / "releases" / "opencode" / "hooks"
        (hooks / "junk.pyc").write_bytes(b"x")
        (hooks / "__pycache__").mkdir()
        (hooks / "__pycache__" / "junk.pyc").write_bytes(b"x")
        out = lite / "out.zip"
        r = _pack(out, cwd=lite)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        with zipfile.ZipFile(out) as z:
            self.assertEqual(_bytecode_names(z.namelist()), [])

    def test_plain_install_no_skill_md_and_prunes_pyc(self):
        lite = _repo_lite("mgh_lite_plain_")
        hooks = lite / "releases" / "opencode" / "hooks"
        (hooks / "junk.pyc").write_bytes(b"x")
        target = lite / "proj"
        target.mkdir()
        r = _run(["install.sh", "--opencode", str(target)], cwd=lite)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        self.assertFalse((target / "SKILL.md").exists())
        self.assertEqual(_bytecode_names(
            [p.relative_to(target).as_posix() for p in target.rglob("*")]), [])


class TestExtractEquivalence(unittest.TestCase):
    """Extract-the-zip vs run-the-installer: byte-identical minus SKILL.md."""

    @classmethod
    def setUpClass(cls):
        cls.zip_path, _ = _pack_real_once()
        cls.d = Path(tempfile.mkdtemp(prefix="mgh_equiv_"))
        cls.extracted = cls.d / "extracted"
        cls.installed = cls.d / "installed"
        cls.extracted.mkdir()
        cls.installed.mkdir()
        with zipfile.ZipFile(cls.zip_path) as z:
            z.extractall(cls.extracted)
        r = _run(["install.sh", "--opencode", str(cls.installed)])
        if r.returncode != 0:
            raise AssertionError("install run failed:\n%s" % r.stderr[-1500:])

    def test_extract_equals_install_minus_skill_md(self):
        a = _rel_files(self.extracted)
        b = _rel_files(self.installed)
        self.assertNotIn("SKILL.md", b)
        a_wo_skill = {k: v for k, v in a.items() if k != "SKILL.md"}
        self.assertEqual(set(a_wo_skill), set(b),
                         "set diff: %s" % (set(a_wo_skill) ^ set(b)))
        for k, data in a_wo_skill.items():
            self.assertEqual(data, b[k], "byte diff at %s" % k)


if __name__ == "__main__":
    unittest.main(verbosity=1)
