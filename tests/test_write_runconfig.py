#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for write_runconfig.py — atomic run_config.json start-state intent writer.

Asserts: atomic write of <target>/.mgh-init/run_config.json; target recorded ABSOLUTE;
--no-scout / mode=merge / skip_consistency recorded; --target/--format required (exit 2);
stdout ack shape. Run from a non-script cwd (import robustness).
"""
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WC = _load("write_runconfig")


def _run(*argv):
    old, sys.argv = sys.argv, ["write_runconfig.py"] + list(argv)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = WC.main()
    except SystemExit as e:           # argparse misuse (missing required / bad choice) -> exit 2
        code = int(e.code) if isinstance(e.code, int) else 2
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class TestWriteRunconfig(unittest.TestCase):
    def test_writes_run_config_with_absolute_target(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_")).resolve()
        code, out, _ = _run("--target", str(target), "--format", "opencode", "--no-scout")
        self.assertEqual(code, 0)
        rc_path = target / ".mgh-init" / "run_config.json"
        self.assertTrue(rc_path.is_file())
        cfg = json.loads(rc_path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["target"], str(target))           # ABSOLUTE
        self.assertTrue(Path(cfg["target"]).is_absolute())
        self.assertEqual(cfg["format"], "opencode")
        self.assertTrue(cfg["no_scout"])
        self.assertEqual(cfg["mode"], "normal")
        ack = json.loads(out)
        self.assertEqual(ack["run_config"], str(rc_path.resolve()))

    def test_merge_sets_mode(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc2_")).resolve()
        code, out, _ = _run("--target", str(target), "--format", "claude", "--merge", "/tmp/p")
        self.assertEqual(code, 0)
        ack = json.loads(out)
        self.assertEqual(ack["mode"], "merge")

    def test_atomic_no_tmp_left(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc3_")).resolve()
        _run("--target", str(target), "--format", "opencode")
        rc_dir = target / ".mgh-init"
        self.assertFalse(any(p.suffix == ".tmp" for p in rc_dir.glob("*.tmp")))

    def test_missing_required_exit2(self):
        code, _, _ = _run("--format", "opencode")  # no --target
        self.assertEqual(code, 2)

    def test_bad_budget_exit2(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc4_")).resolve()
        code, _, _ = _run("--target", str(target), "--format", "opencode", "--max-unit-bytes", "-5")
        self.assertEqual(code, 2)

    def test_skip_consistency_recorded(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc5_")).resolve()
        _run("--target", str(target), "--format", "opencode", "--skip-consistency")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["skip_consistency"])

    def test_include_tests_recorded(self):
        # --include-tests → run_config["include_tests"] == True (mirrors include_dotfiles).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc6_")).resolve()
        _run("--target", str(target), "--format", "opencode", "--include-tests")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["include_tests"])

    def test_include_tests_default_false(self):
        # Default (flag absent) → include_tests == False (mgh-init excludes test sources).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc7_")).resolve()
        _run("--target", str(target), "--format", "opencode")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["include_tests"])


if __name__ == "__main__":
    unittest.main()
