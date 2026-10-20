#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""env_profile.py unit tests.

Covers: missing file/dir -> full defaults (auto -> current dispatch form, concurrency 3,
no quota) with zero behavior change; every fail-closed shape (unparsable JSON, non-object,
unknown v, non-int v, dispatch_mode outside the enum, native_concurrency 0/6/non-int/bool,
partial quota, non-positive quota values) -> CLI exit 2 + recipe naming the file and the
violating field, import form raises the typed EnvProfileError (a ValueError subclass —
NEVER a silent fall-back to defaults); valid shapes parse; unknown fields ignored;
--check is read-only and reports the resolved result (or the failure); stdout is exactly
one JSON line; --help carries every flag and the value ranges.

Run: py tests/test_env_profile.py
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "env_profile.py"


def _load():
    spec = importlib.util.spec_from_file_location("env_profile", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class EnvProfileTest(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_envprof_"))
        self.proj = self.tmp / "proj"
        self.proj.mkdir(parents=True)
        self.cfg = self.proj / ".mgh" / "env-profile.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cfg(self, body):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps(body), encoding="utf-8")
        return self.cfg

    def _run(self, *args):
        sys.argv = ["env_profile.py"] + list(args)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    # --- missing config -> defaults, zero behavior change ---
    def test_missing_file_resolves_defaults(self):
        p = self.m.load(self.proj)
        self.assertEqual(p.dispatch_mode, "auto")
        self.assertEqual(p.native_concurrency, 3)
        self.assertIsNone(p.quota)

    def test_missing_dir_resolves_defaults(self):
        p = self.m.load(self.tmp / "no-such-project")
        self.assertEqual(p.dispatch_mode, "auto")
        self.assertEqual(p.native_concurrency, 3)
        self.assertIsNone(p.quota)

    def test_cli_missing_file_reports_defaults_exit0(self):
        code, out, err = self._run("--target", str(self.proj))
        self.assertEqual(code, 0, err)
        d = json.loads(out)                      # stdout = exactly one JSON line
        self.assertEqual(out.count("\n"), 1)
        self.assertEqual(d["profile"], {"dispatch_mode": "auto",
                                        "native_concurrency": 3, "quota": None})
        self.assertFalse(d["exists"])

    def test_check_missing_file_reports_defaults_exit0(self):
        code, out, err = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["check"], "ok")
        self.assertEqual(d["profile"]["dispatch_mode"], "auto")

    # --- valid shapes ---
    def test_full_valid_config_parses(self):
        self._write_cfg({"v": 1, "dispatch_mode": "native",
                         "native_concurrency": 5,
                         "quota": {"calls": 100, "window_s": 600,
                                   "calls_per_unit": 10}})
        p = self.m.load(self.proj)
        self.assertEqual(p.dispatch_mode, "native")
        self.assertEqual(p.native_concurrency, 5)
        self.assertEqual(p.quota, {"calls": 100, "window_s": 600,
                                   "calls_per_unit": 10})

    def test_each_dispatch_mode_value_parses(self):
        for mode in ("auto", "runner", "native"):
            self._write_cfg({"dispatch_mode": mode})
            self.assertEqual(self.m.load(self.proj).dispatch_mode, mode)

    def test_concurrency_boundaries_parse(self):
        for n in (1, 5):
            self._write_cfg({"native_concurrency": n})
            self.assertEqual(self.m.load(self.proj).native_concurrency, n)

    def test_v_absent_is_accepted(self):
        self._write_cfg({"dispatch_mode": "runner"})
        p = self.m.load(self.proj)
        self.assertEqual(p.dispatch_mode, "runner")

    def test_unknown_fields_ignored(self):
        self._write_cfg({"v": 1, "dispatch_mode": "native", "future_field": {"x": 1},
                         "quota": {"calls": 30, "window_s": 600,
                                   "calls_per_unit": 10, "extra": 1}})
        p = self.m.load(self.proj)
        self.assertEqual(p.quota, {"calls": 30, "window_s": 600,
                                   "calls_per_unit": 10})

    # --- fail-closed shapes: NEVER a silent fall-back ---
    def _assert_bad(self, raw_text, needle):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(raw_text, encoding="utf-8")
        # import form: typed exception (ValueError subclass), not silent defaults
        with self.assertRaises(self.m.EnvProfileError) as cm:
            self.m.load(self.proj)
        self.assertIn(str(self.cfg), str(cm.exception))
        # CLI form: exit 2 + recipe naming the file and the violating field
        code, out, err = self._run("--target", str(self.proj))
        self.assertEqual(code, 2)
        self.assertIn(str(self.cfg), err)
        self.assertIn(needle, err)
        self.assertIn("recipe", err)
        # --check form: same fail-closed verdict
        code2, out2, err2 = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code2, 2)
        self.assertIn(needle, err2)

    def test_unparsable_json_fail_closed(self):
        self._assert_bad("{not json", "unparsable")

    def test_non_object_fail_closed(self):
        self._assert_bad("[1, 2]", "JSON object")

    def test_unknown_v_fail_closed(self):
        self._assert_bad('{"v": 2}', "v")

    def test_non_int_v_fail_closed(self):
        self._assert_bad('{"v": "1"}', "v")

    def test_dispatch_mode_outside_enum_fail_closed(self):
        self._assert_bad('{"dispatch_mode": "nativ"}', "dispatch_mode")

    def test_non_string_dispatch_mode_fail_closed(self):
        self._assert_bad('{"dispatch_mode": 3}', "dispatch_mode")

    def test_concurrency_zero_fail_closed(self):
        self._assert_bad('{"native_concurrency": 0}', "native_concurrency")

    def test_concurrency_six_fail_closed(self):
        self._assert_bad('{"native_concurrency": 6}', "native_concurrency")

    def test_concurrency_non_int_fail_closed(self):
        self._assert_bad('{"native_concurrency": "3"}', "native_concurrency")

    def test_concurrency_bool_fail_closed(self):
        self._assert_bad('{"native_concurrency": true}', "native_concurrency")

    def test_partial_quota_fail_closed(self):
        self._assert_bad('{"quota": {"calls": 100, "window_s": 600}}',
                         "quota")

    def test_non_positive_quota_fail_closed(self):
        self._assert_bad('{"quota": {"calls": 0, "window_s": 600, '
                         '"calls_per_unit": 10}}', "quota")

    def test_non_int_quota_fail_closed(self):
        self._assert_bad('{"quota": {"calls": 100, "window_s": 600, '
                         '"calls_per_unit": 1.5}}', "quota")

    # --- CLI misuse / surface ---
    def test_missing_target_exit2(self):
        code, out, err = self._run()
        self.assertEqual(code, 2)
        self.assertIn("--target", err)

    def test_target_not_a_dir_exit2(self):
        code, out, err = self._run("--target", str(self.tmp / "nope"))
        self.assertEqual(code, 2)

    def test_check_is_read_only(self):
        self._write_cfg({"dispatch_mode": "native"})
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        code, out, err = self._run("--target", str(self.proj), "--check")
        self.assertEqual(code, 0, err)
        after = sorted(str(p) for p in self.tmp.rglob("*"))
        self.assertEqual(before, after)

    def test_help_lists_flags_and_ranges(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0)
        for token in ("--target", "--check", "dispatch_mode", "auto", "runner",
                      "native", "native_concurrency", "1..5", "quota",
                      "calls", "window_s", "calls_per_unit"):
            self.assertIn(token, r.stdout, f"--help missing {token!r}")

    def test_import_from_non_script_dir_cwd(self):
        # R5.3a self-location: the module must import cleanly from any cwd
        r = subprocess.run(
            [sys.executable, "-c",
             f"import importlib.util as u; s=u.spec_from_file_location("
             f"'env_profile', r'''{SCRIPT}'''); m=u.module_from_spec(s); "
             f"s.loader.exec_module(m); print(m.load(r'''{self.proj}''')"
             f".dispatch_mode)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("auto", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
