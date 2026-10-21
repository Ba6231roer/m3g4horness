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


class DefaultResolutionTest(unittest.TestCase):
    """fix-mgh-sdr-native-default-dispatch 1.x: the default dispatch form is
    resolved from the host install face x the calling consumer. ONLY consumer=sdr
    on the opencode face becomes native; every other combination keeps runner.
    Explicit dispatch_mode values always win; bad profiles stay fail-closed."""

    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_envprof_res_"))
        self.proj = self.tmp / "proj"
        self.proj.mkdir(parents=True)
        self.cfg = self.proj / ".mgh" / "env-profile.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cfg(self, body):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps(body), encoding="utf-8")

    # --- default resolution matrix ---
    def test_missing_profile_sdr_opencode_is_native(self):
        r = self.m.resolve(self.proj, consumer="sdr", host_face="opencode")
        self.assertEqual(r.form, "native")
        self.assertEqual(r.source, "host-default")
        self.assertFalse(r.profile_exists)
        self.assertEqual(r.profile.dispatch_mode, "auto")
        # no config file is ever created by the resolution
        self.assertFalse(self.cfg.exists())

    def test_auto_profile_sdr_opencode_is_native(self):
        self._write_cfg({"v": 1, "dispatch_mode": "auto"})
        r = self.m.resolve(self.proj, consumer="sdr", host_face="opencode")
        self.assertEqual(r.form, "native")
        self.assertEqual(r.source, "host-default")
        self.assertTrue(r.profile_exists)

    def test_generic_consumer_on_opencode_stays_runner(self):
        r = self.m.resolve(self.proj, consumer="generic", host_face="opencode")
        self.assertEqual(r.form, "runner")
        self.assertEqual(r.source, "host-default")

    def test_claude_and_other_faces_stay_runner_for_sdr(self):
        for face in ("claude", "other"):
            with self.subTest(face=face):
                r = self.m.resolve(self.proj, consumer="sdr", host_face=face)
                self.assertEqual(r.form, "runner")
                self.assertEqual(r.source, "host-default")

    def test_explicit_native_overrides_any_face(self):
        self._write_cfg({"dispatch_mode": "native"})
        for face in self.m.HOST_FACES:
            with self.subTest(face=face):
                r = self.m.resolve(self.proj, consumer="sdr", host_face=face)
                self.assertEqual(r.form, "native")
                self.assertEqual(r.source, "profile")

    def test_explicit_runner_overrides_opencode_sdr_default(self):
        self._write_cfg({"dispatch_mode": "runner"})
        r = self.m.resolve(self.proj, consumer="sdr", host_face="opencode")
        self.assertEqual(r.form, "runner")
        self.assertEqual(r.source, "profile")

    def test_resolution_as_dict_shape(self):
        r = self.m.resolve(self.proj, consumer="sdr", host_face="opencode")
        d = r.as_dict()
        self.assertEqual(set(d), {"host_face", "consumer", "form", "source",
                                  "profile_exists", "profile"})
        self.assertEqual(d["host_face"], "opencode")
        self.assertEqual(d["consumer"], "sdr")
        self.assertEqual(d["form"], "native")

    # --- host face detection ---
    def test_detect_host_face_from_install_segments(self):
        cases = {
            self.tmp / ".opencode" / "mgh-core" / "scripts" / "env_profile.py": "opencode",
            self.tmp / ".claude" / "mgh-core" / "scripts" / "env_profile.py": "claude",
            self.tmp / "mgh-core" / "scripts" / "env_profile.py": "other",
            self.tmp / "core" / "scripts" / "env_profile.py": "other",
        }
        for path, face in cases.items():
            with self.subTest(path=str(path)):
                self.assertEqual(self.m.detect_host_face(script_path=path), face)

    def test_detect_host_face_explicit_wins(self):
        self.assertEqual(self.m.detect_host_face(explicit="opencode"), "opencode")
        with self.assertRaises(ValueError):
            self.m.detect_host_face(explicit="vscode")

    def test_resolve_rejects_unknown_consumer(self):
        with self.assertRaises(ValueError):
            self.m.resolve(self.proj, consumer="blst", host_face="opencode")

    # --- CLI surface ---
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

    def test_cli_reports_resolution_fields(self):
        code, out, err = self._run("--target", str(self.proj), "--consumer", "sdr")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["consumer"], "sdr")
        self.assertEqual(d["host_face"], "other")      # dev-tree invocation
        self.assertEqual(d["form"], "runner")          # non-opencode face
        self.assertEqual(d["source"], "host-default")

    def test_cli_check_reports_resolution_read_only(self):
        self._write_cfg({"dispatch_mode": "auto"})
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        code, out, err = self._run("--target", str(self.proj), "--consumer",
                                   "sdr", "--check")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["check"], "ok")
        self.assertEqual(d["form"], "runner")
        self.assertEqual(d["host_face"], "other")
        self.assertEqual(before, sorted(str(p) for p in self.tmp.rglob("*")))

    def test_cli_mirrored_opencode_face_sdr_is_native(self):
        # the install-face probe is the SCRIPT'S OWN path: a mirrored copy under
        # .opencode/mgh-core/scripts must resolve native for consumer=sdr without
        # any config file, while the same call for generic stays runner.
        mirror = self.tmp / ".opencode" / "mgh-core" / "scripts"
        mirror.mkdir(parents=True)
        import shutil
        shutil.copy2(SCRIPT, mirror / "env_profile.py")
        r = subprocess.run([sys.executable, str(mirror / "env_profile.py"),
                            "--target", str(self.proj), "--consumer", "sdr"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["host_face"], d["consumer"], d["form"]),
                         ("opencode", "sdr", "native"))
        r2 = subprocess.run([sys.executable, str(mirror / "env_profile.py"),
                             "--target", str(self.proj)],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(json.loads(r2.stdout)["form"], "runner")

    def test_help_declares_consumer_choices(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0)
        for token in ("--consumer", "sdr", "generic", "native", "runner",
                      "host"):
            self.assertIn(token, r.stdout, f"--help missing {token!r}")

    # --- native asset gate (single shared helper) ---
    def test_native_assets_missing_and_present(self):
        root = self.tmp / ".opencode" / "mgh-core"
        (root / "scripts").mkdir(parents=True)
        missing = self.m.missing_native_assets(root)
        self.assertEqual(len(missing), 2)
        recipe = self.m.require_native_assets(root)
        self.assertIn("install.sh --opencode", recipe)
        self.assertIn("dispatch_mode", recipe)
        # create both assets -> gate opens
        (root.parent / "agent").mkdir(parents=True)
        (root.parent / "agent" / "sdr-review-native.md").write_text(
            "x", encoding="utf-8")
        (root / "prompts" / "fragments").mkdir(parents=True)
        (root / "prompts" / "fragments" / "sdr-native-dispatch.md").write_text(
            "x", encoding="utf-8")
        self.assertEqual(self.m.missing_native_assets(root), [])
        self.assertIsNone(self.m.require_native_assets(root))


class InitConsumerDefaultTest(unittest.TestCase):
    """fix-mgh-init-native-scout-dispatch 2.1: the init consumer joins the
    native-default set — `consumer=init ∧ host=opencode` resolves native (no
    profile file means native too; the user-approved mgh-init default-form
    change). Explicit dispatch_mode values still always win; generic/claude/
    other stay runner; bad profiles stay fail-closed; the native-asset gate is
    parameterized by surface without moving the sdr default."""

    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_envprof_init_"))
        self.proj = self.tmp / "proj"
        self.proj.mkdir(parents=True)
        self.cfg = self.proj / ".mgh" / "env-profile.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_cfg(self, body):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text(json.dumps(body), encoding="utf-8")

    # --- default resolution matrix for consumer=init ---
    def test_missing_profile_init_opencode_is_native(self):
        r = self.m.resolve(self.proj, consumer="init", host_face="opencode")
        self.assertEqual(r.form, "native")
        self.assertEqual(r.source, "host-default")
        self.assertFalse(r.profile_exists)
        self.assertEqual(r.profile.dispatch_mode, "auto")
        # no config file is ever created by the resolution
        self.assertFalse(self.cfg.exists())

    def test_auto_profile_init_opencode_is_native(self):
        self._write_cfg({"v": 1, "dispatch_mode": "auto"})
        r = self.m.resolve(self.proj, consumer="init", host_face="opencode")
        self.assertEqual(r.form, "native")
        self.assertEqual(r.source, "host-default")
        self.assertTrue(r.profile_exists)

    def test_explicit_runner_overrides_opencode_init_default(self):
        self._write_cfg({"dispatch_mode": "runner"})
        r = self.m.resolve(self.proj, consumer="init", host_face="opencode")
        self.assertEqual(r.form, "runner")
        self.assertEqual(r.source, "profile")

    def test_claude_and_other_faces_stay_runner_for_init(self):
        for face in ("claude", "other"):
            with self.subTest(face=face):
                r = self.m.resolve(self.proj, consumer="init", host_face=face)
                self.assertEqual(r.form, "runner")
                self.assertEqual(r.source, "host-default")

    def test_explicit_native_overrides_any_face_for_init(self):
        # parser level: explicit native wins everywhere; the ORCHESTRATION faces
        # fail-closed on non-opencode native (their own contract, tested there).
        self._write_cfg({"dispatch_mode": "native"})
        for face in self.m.HOST_FACES:
            with self.subTest(face=face):
                r = self.m.resolve(self.proj, consumer="init", host_face=face)
                self.assertEqual(r.form, "native")
                self.assertEqual(r.source, "profile")

    def test_sdr_default_resolution_unregressed(self):
        # the init addition must not move the sdr default (or anything else)
        self.assertEqual(
            self.m.resolve(self.proj, consumer="sdr",
                           host_face="opencode").form, "native")
        self.assertEqual(
            self.m.resolve(self.proj, consumer="generic",
                           host_face="opencode").form, "runner")
        self.assertEqual(
            self.m.resolve(self.proj, consumer="sdr",
                           host_face="claude").form, "runner")

    def test_bad_profile_init_consumer_fail_closed(self):
        self.cfg.parent.mkdir(parents=True, exist_ok=True)
        self.cfg.write_text('{"dispatch_mode": "nativ"}', encoding="utf-8")
        with self.assertRaises(self.m.EnvProfileError):
            self.m.load(self.proj)
        sys.argv = ["env_profile.py", "--target", str(self.proj),
                    "--consumer", "init"]
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        self.assertEqual(code, 2)
        self.assertIn("dispatch_mode", err.getvalue())
        self.assertIn("recipe", err.getvalue())

    def test_cli_accepts_init_consumer(self):
        sys.argv = ["env_profile.py", "--target", str(self.proj),
                    "--consumer", "init"]
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        self.assertEqual(code, 0, err.getvalue())
        d = json.loads(out.getvalue())
        self.assertEqual(d["consumer"], "init")

    def test_help_declares_init_consumer(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0)
        for token in ("--consumer", "sdr", "init", "generic"):
            self.assertIn(token, r.stdout, f"--help missing {token!r}")

    # --- native asset gate: surface dimension ---
    def _gate_root(self):
        root = self.tmp / ".opencode" / "mgh-core"
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "prompts" / "fragments").mkdir(parents=True, exist_ok=True)
        (root.parent / "agent").mkdir(parents=True, exist_ok=True)
        # sdr assets present so the sdr default path is unaffected
        (root.parent / "agent" / "sdr-review-native.md").write_text(
            "x", encoding="utf-8")
        (root / "prompts" / "fragments" / "sdr-native-dispatch.md").write_text(
            "x", encoding="utf-8")
        return root

    def _write_init_assets(self, root, skip=()):
        """Write the FULL init native asset set (5 twins + 2 fragments),
        skipping the names in `skip` — fix-mgh-init-native-aggregate-dispatch
        widened the init surface from 2 assets to 7."""
        agent_dir = root.parent / "agent"
        frag_dir = root / "prompts" / "fragments"
        names = [f"{a}.md" for a in self.m.INIT_NATIVE_AGENTS]
        names += ["init-scout-native-dispatch.md",
                  "init-aggregate-native-dispatch.md"]
        for i, name in enumerate(names):
            if name in skip:
                continue
            target = agent_dir / name if i < len(self.m.INIT_NATIVE_AGENTS)                 else frag_dir / name
            target.write_text("x", encoding="utf-8")

    def test_init_surface_missing_agent(self):
        root = self._gate_root()
        missing = self.m.missing_native_assets(root, surface="init")
        self.assertEqual(len(missing), 7)
        self.assertIn("init-scout-native.md", missing[0])
        self.assertIn("init-scout-native-dispatch.md", missing[5])
        self.assertIn("init-aggregate-native-dispatch.md", missing[6])
        recipe = self.m.require_native_assets(root, surface="init")
        self.assertIsNotNone(recipe)
        self.assertIn("install.sh --opencode", recipe)
        # the sdr gate on the SAME tree stays green (surface isolation)
        self.assertEqual(self.m.missing_native_assets(root), [])

    def test_init_surface_missing_one_aggregate_twin(self):
        # a PARTIAL twin set (e.g. only the aggregate fragment missing) is a
        # version-skewed install: the gate blocks startup, NEVER a silent
        # layer-by-layer fallback.
        root = self._gate_root()
        self._write_init_assets(
            root, skip=("init-aggregate-native-dispatch.md",))
        missing = self.m.missing_native_assets(root, surface="init")
        self.assertEqual(len(missing), 1)
        self.assertIn("init-aggregate-native-dispatch.md", missing[0])
        self._write_init_assets(root)
        self.assertEqual(self.m.missing_native_assets(root, surface="init"), [])

    def test_init_surface_gate_opens_when_complete(self):
        root = self._gate_root()
        self._write_init_assets(root)
        self.assertEqual(self.m.missing_native_assets(root, surface="init"), [])
        self.assertIsNone(self.m.require_native_assets(root, surface="init"))

    def test_unknown_surface_rejected(self):
        root = self._gate_root()
        with self.assertRaises(KeyError):
            self.m.missing_native_assets(root, surface="blst")

    def test_sdr_surface_explicit_equals_default(self):
        root = self._gate_root()
        (root.parent / "agent").mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            self.m.missing_native_assets(root, surface="sdr"),
            self.m.missing_native_assets(root))


if __name__ == "__main__":
    unittest.main(verbosity=2)
