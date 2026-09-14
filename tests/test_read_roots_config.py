#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""read_roots_config.py unit tests (add-mgh-sdr-read-root-config task 1.2).

Covers: add/list/remove/check full paths; idempotent no-op (duplicate --add, absent
--remove); illegal --add fail-loud exit 2 (non-existent / file-not-dir / relative)
with zero partial write; bad-JSON repair path (verbatim .bad backup + fresh config);
`D:/x` vs `D:\\x` resolve-normalization never double-records; unknown JSON fields
preserved; mode ambiguity + nothing-to-do misuse gates; stale-entry --check exit 2;
non-script-dir cwd subprocess import robustness.

Run: py tests/test_read_roots_config.py
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "read_roots_config.py"


def _load():
    spec = importlib.util.spec_from_file_location("read_roots_config", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ReadRootsConfigTest(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_rr_"))
        self.proj = self.tmp / "proj"
        (self.proj / "sub").mkdir(parents=True)
        self.cfg = self.proj / ".mgh" / "read-roots.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        sys.argv = ["read_roots_config.py"] + list(args)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _read_cfg(self):
        return json.loads(self.cfg.read_text(encoding="utf-8"))

    # --- add / list / remove / check full paths ---
    def test_add_creates_config_and_reports(self):
        code, out, err = self._run("--target", str(self.proj), "--add",
                                   str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["added"], [str(self.proj / "sub")])
        self.assertEqual(d["configured"], [str(self.proj / "sub")])
        self.assertEqual(d["removed"], [])
        body = self._read_cfg()
        self.assertEqual(body, {"v": 1, "read_roots": [str(self.proj / "sub")]})
        self.assertIn("add:", err)          # stderr audit trail

    def test_list_missing_config_empty_ok(self):
        code, out, err = self._run("--target", str(self.proj), "--list")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["configured"], [])

    def test_list_reports_entries(self):
        self._run("--target", str(self.proj), "--add", str(self.proj / "sub"))
        code, out, _ = self._run("--target", str(self.proj), "--list")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["configured"], [str(self.proj / "sub")])

    def test_remove_present_and_absent(self):
        self._run("--target", str(self.proj), "--add", str(self.proj / "sub"))
        code, out, err = self._run("--target", str(self.proj), "--remove",
                                   str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["removed"], [str(self.proj / "sub")])
        self.assertEqual(self._read_cfg()["read_roots"], [])
        # absent remove: no-op, exit 0
        code, out, err = self._run("--target", str(self.proj), "--remove",
                                   str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["removed"], [])
        self.assertIn("no changes", err)

    def test_check_ok_and_stale_and_missing(self):
        code, _, err = self._run("--target", str(self.proj), "--add",
                                 str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        code, out, err = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["check"], "ok")
        # stale entry (dir removed after grant): --check exit 2 + names the entry
        gone = self.tmp / "gone"
        gone.mkdir()
        self._run("--target", str(self.proj), "--add", str(gone))
        import shutil
        shutil.rmtree(gone)
        code, out, err = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code, 2)
        self.assertIn("stale", err)
        self.assertIn(str(gone), err)
        # missing config: --check exit 2 (fail-loud boundary validation)
        self.cfg.unlink()
        code, _, err = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    # --- idempotency ---
    def test_duplicate_add_is_noop(self):
        self._run("--target", str(self.proj), "--add", str(self.proj / "sub"))
        code, out, err = self._run("--target", str(self.proj), "--add",
                                   str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["added"], [])
        self.assertEqual(self._read_cfg()["read_roots"], [str(self.proj / "sub")])
        self.assertIn("no changes", err)

    # --- illegal --add: exit 2, zero partial write ---
    def test_add_nonexistent_exits_2(self):
        code, _, err = self._run("--target", str(self.proj), "--add",
                                 str(self.tmp / "no-such-dir"))
        self.assertEqual(code, 2)
        self.assertIn("not an existing directory", err)
        self.assertFalse(self.cfg.exists())

    def test_add_file_not_dir_exits_2(self):
        f = self.proj / "afile.txt"
        f.write_text("x", encoding="utf-8")
        code, _, err = self._run("--target", str(self.proj), "--add", str(f))
        self.assertEqual(code, 2)
        self.assertFalse(self.cfg.exists())

    def test_add_relative_exits_2(self):
        code, _, err = self._run("--target", str(self.proj), "--add", "relative/dir")
        self.assertEqual(code, 2)
        self.assertIn("absolute", err)

    def test_mixed_add_transactional(self):
        # one valid + one invalid --add: exit 2, the valid one NOT written
        code, _, err = self._run("--target", str(self.proj), "--add",
                                 str(self.proj / "sub"), "--add",
                                 str(self.tmp / "nope"))
        self.assertEqual(code, 2)
        self.assertFalse(self.cfg.exists())

    # --- resolve normalization: D:/x vs D:\x never double-record ---
    def test_slash_forms_normalize_no_double_record(self):
        fwd = (self.proj / "sub").as_posix()
        back = str(self.proj / "sub")
        self.assertNotEqual(fwd, back)      # precondition: two textual forms
        code, out, _ = self._run("--target", str(self.proj), "--add", fwd)
        self.assertEqual(code, 0)
        code, out, _ = self._run("--target", str(self.proj), "--add", back)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["added"], [])
        self.assertEqual(self._read_cfg()["read_roots"], [back])

    # --- unknown fields preserved ---
    def test_unknown_fields_preserved(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps({
            "v": 1, "read_roots": [str(self.proj / "sub")], "team": "platform",
        }), encoding="utf-8")
        other = self.proj / "sub2"
        other.mkdir()
        code, _, err = self._run("--target", str(self.proj), "--add", str(other))
        self.assertEqual(code, 0, err)
        body = self._read_cfg()
        self.assertEqual(body["team"], "platform")
        self.assertEqual(len(body["read_roots"]), 2)

    # --- bad JSON repair path ---
    def test_bad_json_repaired_with_backup(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text("{not json", encoding="utf-8")
        code, out, err = self._run("--target", str(self.proj), "--add",
                                   str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        self.assertIn("WARN", err)
        bad = self.cfg.with_name(self.cfg.name + ".bad")
        self.assertTrue(bad.is_file())
        self.assertEqual(bad.read_text(encoding="utf-8"), "{not json")
        self.assertEqual(self._read_cfg()["read_roots"], [str(self.proj / "sub")])

    def test_wrong_typed_read_roots_repaired(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps({"v": 1, "read_roots": "oops"}),
                            encoding="utf-8")
        code, _, err = self._run("--target", str(self.proj), "--add",
                                 str(self.proj / "sub"))
        self.assertEqual(code, 0, err)
        self.assertIn("WARN", err)
        self.assertEqual(self._read_cfg()["read_roots"], [str(self.proj / "sub")])

    # --- misuse gates ---
    def test_mode_ambiguity_and_nothing_to_do(self):
        code, _, err = self._run("--target", str(self.proj), "--list", "--check")
        self.assertEqual(code, 2)
        code, _, err = self._run("--target", str(self.proj), "--list", "--add",
                                 str(self.proj / "sub"))
        self.assertEqual(code, 2)
        code, _, err = self._run("--target", str(self.proj))
        self.assertEqual(code, 2)
        self.assertIn("nothing to do", err)
        code, _, err = self._run()
        self.assertEqual(code, 2)
        self.assertIn("--target", err)
        code, _, err = self._run("--target", str(self.tmp / "nope"), "--list")
        self.assertEqual(code, 2)

    # --- non-script-dir cwd subprocess import robustness (R5.8) ---
    def test_subprocess_any_cwd(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--target", str(self.proj), "--add",
             str(self.proj / "sub")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["added"], [str(self.proj / "sub")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
