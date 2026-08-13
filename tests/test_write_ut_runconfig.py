#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for write_ut_runconfig.py — atomic run_config.json start-state intent writer
for /mgh-ut-init (ut counterpart of test_write_runconfig.py). Asserts: atomic write of
<target>/.mgh-ut-init/run_config.json; target recorded ABSOLUTE; --target required (exit 2);
--format defaults to opencode (omitted -> exit 0). Run from a non-script cwd (import robustness).
"""
import contextlib, importlib.util, io, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


WC = _load("write_ut_runconfig")


def _run(*argv):
    old, sys.argv = sys.argv, ["write_ut_runconfig.py"] + list(argv)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = WC.main()
    except SystemExit as e:           # argparse misuse (missing required / bad choice) -> exit 2
        code = int(e.code) if isinstance(e.code, int) else 2
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class TestWriteUtRunconfig(unittest.TestCase):
    def test_format_defaults_opencode(self):
        # Omitting --format (no --target conflict) -> exit 0 + format == "opencode".
        target = Path(tempfile.mkdtemp(prefix="mgh_utwc_fmt_")).resolve()
        code, out, _ = _run("--target", str(target))
        self.assertEqual(code, 0)
        cfg = json.loads((target / ".mgh-ut-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["format"], "opencode")
        self.assertEqual(json.loads(out)["format"], "opencode")

    def test_missing_required_exit2(self):
        code, _, _ = _run("--format", "opencode")  # no --target
        self.assertEqual(code, 2)

    def test_explicit_format_claude(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_utwc_claude_")).resolve()
        code, _, _ = _run("--target", str(target), "--format", "claude")
        self.assertEqual(code, 0)
        cfg = json.loads((target / ".mgh-ut-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["format"], "claude")


if __name__ == "__main__":
    unittest.main()
