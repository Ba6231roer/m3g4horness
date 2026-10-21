#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""resume_sdr_state.py unit tests (add-mgh-sdr-resume-surface task 3.7).

Builds synthetic sdr run dirs (no git, no LLM) covering every intermediate disk
state and asserts the derived step / tiers / next_action / disclosures, the
--check gate semantics (sentinel window, ambiguous terminals, work-list
agreement), the sentinel re-arm (idempotent, Windows-native, fail-closed on a
vanished external root), and pure-function idempotence of the reporter.

Run: py tests/test_resume_sdr_state.py
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "resume_sdr_state.py"
TS = "20260918_120000-feat"


class ResumeSdrStateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    # --- harness ----------------------------------------------------------

    def _run_dir(self, make_repo_layout=True):
        if make_repo_layout:
            run = self.tmp / "repo" / ".mgh-sdr" / "runs" / TS
        else:
            run = self.tmp / "loose-somewhere"
        run.mkdir(parents=True, exist_ok=True)
        return run

    def _repo(self):
        return self.tmp / "repo"

    def _context(self, run, repo=None, base="master", branch="feat", external=None):
        repo = repo or self._repo()
        (run / "context.json").write_text(json.dumps({
            "repo": str(repo), "run_dir": str(run), "base": base, "branch": branch,
            "baseline_path": str(run / "baseline.md"),
            "external_repos": external if external is not None else [],
        }, ensure_ascii=False), encoding="utf-8")

    def _grouping(self, run, unit_ids, repo=None, base="master", branch="feat",
                  empty=False, total=None, excluded=0, status="pending", pending=None):
        repo = repo or self._repo()
        units = [{"unit_id": u, "kind": "interface", "route": "/x",
                  "chain": [], "status": status} for u in unit_ids]
        (run / "grouping.json").write_text(json.dumps({
            "repo": str(repo), "base": base, "branch": branch,
            "empty": empty, "total": len(unit_ids) if total is None else total,
            "units": units, "done": 0, "failed": 0,
            "excluded": {"count": excluded, "by_reason": {}},
            "pending": pending if pending is not None else [],
        }, ensure_ascii=False), encoding="utf-8")

    def _mark(self, run, uid, kind="done"):
        cp = run / "markers"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{uid}.{kind}").write_text("{}", encoding="utf-8")

    def _sentinel(self, top=None):
        sp = (top or self._repo()) / ".mgh-sdr" / ".active"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"domain": "mgh-sdr", "target": str(self._repo()),
                                  "out_roots": [], "read_roots": [], "v": 1}),
                      encoding="utf-8")
        return sp

    def _run(self, *extra):
        run = extra[0] if extra else None
        args = list(extra)
        p = subprocess.run([sys.executable, str(SCRIPT), *args],
                           capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout, p.stderr

    def _state(self, run, *extra):
        code, out, err = self._run("--run-dir", str(run), *extra)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    # --- step derivation --------------------------------------------------

    def test_empty_run_dir_is_not_started(self):
        run = self._run_dir()
        st = self._state(run)
        self.assertEqual(st["step"], "not-started")
        self.assertTrue(st["resumable"])
        self.assertEqual(st["tiers"], {"done": 0, "failed": 0, "total": 0})
        self.assertTrue(any("start state is not on disk" in n for n in st["notes"]))
        # repo still derivable from the layout, so no "pass --repo" complaint
        self.assertFalse(any("could not be derived" in n for n in st["notes"]))
        self.assertEqual(st["discipline_reminders"],
                         {"gates": [], "path_recipes": [], "nevers": []})

    def test_context_only_is_group(self):
        run = self._run_dir()
        self._context(run)
        st = self._state(run)
        self.assertEqual(st["step"], "group")
        self.assertEqual(st["base"], "master")
        self.assertEqual(st["branch"], "feat")
        self.assertIn("diff_group.py", st["next_action"]["desc"])
        self.assertTrue(all(Path(p).is_absolute()
                            for p in st["next_action"]["absolute_paths"]))
        self.assertTrue(st["discipline_reminders"]["gates"], "group carries its gates")

    def test_grouping_present_is_fanout(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1", "u2"])
        st = self._state(run)
        self.assertEqual(st["step"], "fanout")
        self.assertEqual(st["tiers"], {"done": 0, "failed": 0, "total": 2})
        self.assertIn("fanout_runner.py", st["next_action"]["desc"])
        self.assertIn("--tier sdr", st["next_action"]["desc"])
        self.assertTrue(any("2/2 unit(s) have no terminal marker" in n for n in st["notes"]))

    def test_partial_terminal_stays_fanout_with_counts(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1", "u2", "u3"])
        self._mark(run, "u1")
        self._mark(run, "u2", "failed")
        st = self._state(run)
        self.assertEqual(st["step"], "fanout")
        self.assertEqual(st["tiers"], {"done": 1, "failed": 1, "total": 3})
        self.assertTrue(any("1/3 unit(s) have no terminal marker" in n for n in st["notes"]))
        self.assertTrue(any("FAILED" in n for n in st["notes"]))

    def test_all_terminal_advances_to_render(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1", "u2"])
        self._mark(run, "u1")
        self._mark(run, "u2")
        st = self._state(run)
        self.assertEqual(st["step"], "render")
        self.assertIn("render_sdr_report.py", st["next_action"]["desc"])
        self.assertTrue(any("render_sdr_report.py" in g["command"]
                            for g in st["discipline_reminders"]["gates"]))

    def test_manifest_advances_to_done(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        self._mark(run, "u1")
        (run / "sdr_manifest.json").write_text("{}", encoding="utf-8")
        st = self._state(run)
        self.assertEqual(st["step"], "done")
        self.assertFalse(st["resumable"])
        self.assertEqual(st["next_action"]["kind"], "done")
        self.assertEqual(st["discipline_reminders"],
                         {"gates": [], "path_recipes": [], "nevers": []})

    def test_zero_diff_does_not_idle_in_fanout(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, [], empty=True)
        st = self._state(run)
        self.assertEqual(st["step"], "render")
        self.assertTrue(any("zero-diff" in n for n in st["notes"]))

    def test_all_excluded_does_not_idle_in_fanout(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, [], excluded=7)
        st = self._state(run)
        self.assertEqual(st["step"], "render")
        self.assertTrue(any("excluded by the closed exclusion set" in n for n in st["notes"]))

    def test_stale_status_field_is_not_trusted(self):
        # the enumeration-time snapshot says everything is pending; the markers say
        # otherwise. Markers win — otherwise a finished run would be re-dispatched.
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1", "u2"], status="pending")
        self._mark(run, "u1")
        self._mark(run, "u2")
        st = self._state(run)
        self.assertEqual(st["step"], "render")
        self.assertEqual(st["tiers"]["done"], 2)

    def test_legacy_run_config_is_ignored(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        baseline = self._state(run)
        (run / "run_config.json").write_text(json.dumps({
            "base": "WRONG", "branch": "WRONG", "no_codegraph": True,
        }), encoding="utf-8")
        after = self._state(run)
        self.assertEqual(after["base"], "master")
        self.assertEqual(after["branch"], "feat")
        self.assertEqual(after, baseline, "a legacy run_config changed the derivation")

    def test_base_conflict_disclosed_context_wins(self):
        run = self._run_dir()
        self._context(run, base="master")
        self._grouping(run, ["u1"], base="develop", branch="other")
        st = self._state(run)
        self.assertEqual(st["base"], "master")
        self.assertEqual(st["branch"], "feat")
        self.assertTrue(any("base disagrees" in n for n in st["notes"]))
        self.assertTrue(any("branch disagrees" in n for n in st["notes"]))

    def test_malformed_grouping_exits_2_and_never_guesses(self):
        run = self._run_dir()
        self._context(run)
        (run / "grouping.json").write_text("{not json", encoding="utf-8")
        code, out, err = self._run("--run-dir", str(run))
        self.assertEqual(code, 2)
        self.assertIn("NEVER guess", err)

    def test_missing_run_dir_exits_1(self):
        code, out, err = self._run("--run-dir", str(self.tmp / "nope"))
        self.assertEqual(code, 1)
        self.assertIn("recipe", err.lower())

    def test_missing_run_dir_flag_exits_2(self):
        code, out, err = self._run()
        self.assertEqual(code, 2)
        self.assertIn("--run-dir", err)

    def test_underivable_repo_is_disclosed_not_invented(self):
        run = self._run_dir(make_repo_layout=False)
        st = self._state(run)
        self.assertEqual(st["repo"], "")
        self.assertTrue(any("--repo" in n and "derived" in n for n in st["notes"]))
        self.assertIn("<repo abs>", st["next_action"]["desc"])

    def test_explicit_repo_is_used_when_underivable(self):
        run = self._run_dir(make_repo_layout=False)
        st = self._state(run, "--repo", str(self.tmp / "somewhere"))
        self.assertEqual(st["repo"], str((self.tmp / "somewhere").resolve()))

    def test_same_disk_state_two_calls_are_byte_identical(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1", "u2"])
        self._mark(run, "u1")
        _, out1, _ = self._run("--run-dir", str(run))
        _, out2, _ = self._run("--run-dir", str(run))
        self.assertEqual(out1, out2)

    def test_stale_fanout_liveness_reported(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        (run / "fanout_runner.sdr.pid").write_text(json.dumps({
            "pid": 999999999, "tier": "sdr", "children": [],
        }), encoding="utf-8")
        st = self._state(run)
        self.assertEqual(len(st["stale_fanout"]), 1)
        entry = st["stale_fanout"][0]
        self.assertEqual(entry["tier"], "sdr")
        self.assertFalse(entry["pid_alive"])
        self.assertIn("--kill-stale", entry["note"])

    # --- --check ----------------------------------------------------------

    def test_check_flags_missing_sentinel_during_the_guard_window(self):
        for prep in ("group", "fanout", "render"):
            with self.subTest(step=prep):
                run = self._run_dir()
                self._context(run)
                if prep != "group":
                    self._grouping(run, ["u1"])
                    if prep == "render":
                        self._mark(run, "u1")
                code, out, err = self._run("--run-dir", str(run), "--check")
                self.assertEqual(code, 2, err)
                res = json.loads(out)
                self.assertFalse(res["ok"])
                self.assertIn("sentinel MISSING", res["violations"][0]["issue"])
                self.assertIn("--rearm-sentinel", res["violations"][0]["issue"])

    def test_check_passes_when_sentinel_present(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        self._sentinel()
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])

    def test_check_does_not_flag_sentinel_for_done_run(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        self._mark(run, "u1")
        (run / "sdr_manifest.json").write_text("{}", encoding="utf-8")
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])

    def test_check_is_advisory_for_not_started(self):
        run = self._run_dir()
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertTrue(res["ok"])
        self.assertTrue(any("not applicable" in n for n in res["notes"]))

    def test_check_flags_ambiguous_terminal(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        self._sentinel()
        self._mark(run, "u1", "done")
        self._mark(run, "u1", "failed")
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 2)
        self.assertIn("ambiguous terminal", json.loads(out)["violations"][0]["issue"])

    def test_check_flags_worklist_unknown_unit(self):
        run = self._run_dir()
        self._context(run)
        self._sentinel()
        self._grouping(run, ["u1"], pending=[{"unit_id": "ghost"}])
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 2)
        self.assertIn("absent from", json.loads(out)["violations"][0]["issue"])

    def test_check_treats_orphan_markers_as_advisory(self):
        run = self._run_dir()
        self._context(run)
        self._grouping(run, ["u1"])
        self._sentinel()
        self._mark(run, "legacy-unit")
        code, out, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertTrue(res["ok"])
        self.assertTrue(any("orphan marker" in n for n in res["notes"]))

    # --- --rearm-sentinel -------------------------------------------------

    def test_rearm_is_idempotent_and_windows_native(self):
        run = self._run_dir()
        ext = self.tmp / "frontend"
        ext.mkdir()
        self._context(run, external=[{"path": str(ext), "slug": "frontend"}])
        self._grouping(run, ["u1"])
        code, out, err = self._run("--run-dir", str(run), "--rearm-sentinel")
        self.assertEqual(code, 0, err)
        sp = self._repo() / ".mgh-sdr" / ".active"
        first = sp.read_text(encoding="utf-8")
        body = json.loads(first)
        self.assertEqual(body["domain"], "mgh-sdr")
        self.assertEqual(body["target"], str(self._repo()))
        self.assertEqual(body["out_roots"], [])
        self.assertEqual(body["read_roots"], [str(ext)])
        self.assertNotIn("/c/", first, "MSYS-form path leaked into the sentinel")
        code, out2, err = self._run("--run-dir", str(run), "--rearm-sentinel")
        self.assertEqual(code, 0, err)
        self.assertEqual(sp.read_text(encoding="utf-8"), first, "re-arm is not idempotent")
        # ... and the re-armed sentinel makes --check pass
        code, _, err = self._run("--run-dir", str(run), "--check")
        self.assertEqual(code, 0, err)

    def test_rearm_drops_a_vanished_external_root(self):
        run = self._run_dir()
        gone = self.tmp / "gone"
        alive = self.tmp / "frontend"
        alive.mkdir()
        self._context(run, external=[{"path": str(gone), "slug": "gone"},
                                     {"path": str(alive), "slug": "frontend"}])
        self._grouping(run, ["u1"])
        code, out, err = self._run("--run-dir", str(run), "--rearm-sentinel")
        self.assertEqual(code, 0, err)
        body = json.loads((self._repo() / ".mgh-sdr" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(body["read_roots"], [str(alive)])

    def test_rearm_without_context_fails_loud(self):
        run = self._run_dir()
        code, out, err = self._run("--run-dir", str(run), "--rearm-sentinel")
        self.assertEqual(code, 2)
        self.assertIn("context.json absent", err)
        # the pre-arm entry point is named so a step-0 recovery never dead-ends
        self.assertIn("--arm-sentinel", err)

    def test_rearm_accepts_explicit_repo(self):
        run = self._run_dir()
        (run / "context.json").write_text(json.dumps({"base": "master"}),
                                          encoding="utf-8")
        target = self.tmp / "explicit-repo"
        code, out, err = self._run("--run-dir", str(run), "--rearm-sentinel",
                                   "--repo", str(target))
        self.assertEqual(code, 0, err)
        sp = target / ".mgh-sdr" / ".active"
        self.assertTrue(sp.is_file())
        self.assertEqual(json.loads(sp.read_text(encoding="utf-8"))["target"],
                         str(target.resolve()))

    # --- --arm-sentinel (step-0 pre-arm) ----------------------------------

    def test_arm_writes_minimal_sentinel_and_is_idempotent(self):
        run = self._run_dir()  # fresh run: no context.json yet
        code, out, err = self._run("--run-dir", str(run), "--repo", str(self._repo()),
                                   "--arm-sentinel")
        self.assertEqual(code, 0, err)
        res = json.loads(out)
        self.assertIs(res["armed"], True)
        self.assertEqual(res["target"], str(self._repo().resolve()))
        self.assertTrue(Path(res["sentinel_path"]).is_absolute())
        sp = self._repo() / ".mgh-sdr" / ".active"
        self.assertEqual(Path(res["sentinel_path"]), sp)
        body = json.loads(sp.read_text(encoding="utf-8"))
        self.assertEqual(body, {"domain": "mgh-sdr", "target": str(self._repo().resolve()),
                                "out_roots": [], "read_roots": [], "v": 1})
        # second call: no-op, file byte-identical
        code, out2, err = self._run("--run-dir", str(run), "--repo", str(self._repo()),
                                    "--arm-sentinel")
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out2)["armed"], False)
        self.assertEqual(sp.read_text(encoding="utf-8"),
                         json.dumps(body, ensure_ascii=False))

    def test_arm_noop_never_clears_refined_read_roots(self):
        # step 1 already refined the sentinel (read_roots non-empty); a re-entry
        # pre-arm must leave it untouched, not re-strip the authorization.
        run = self._run_dir()
        ext = self.tmp / "frontend"
        ext.mkdir()
        sp = self._repo() / ".mgh-sdr" / ".active"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"domain": "mgh-sdr", "target": str(self._repo()),
                                  "out_roots": [], "read_roots": [str(ext)], "v": 1}),
                      encoding="utf-8")
        before = sp.read_text(encoding="utf-8")
        code, out, err = self._run("--run-dir", str(run), "--repo", str(self._repo()),
                                   "--arm-sentinel")
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["armed"], False)
        self.assertEqual(sp.read_text(encoding="utf-8"), before)

    def test_arm_conflicting_target_refused(self):
        run = self._run_dir()
        other = self.tmp / "other-repo"
        sp = self._repo() / ".mgh-sdr" / ".active"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({"domain": "mgh-sdr", "target": str(other),
                                  "out_roots": [], "read_roots": [], "v": 1}),
                      encoding="utf-8")
        before = sp.read_text(encoding="utf-8")
        code, out, err = self._run("--run-dir", str(run), "--repo", str(self._repo()),
                                   "--arm-sentinel")
        self.assertEqual(code, 2)
        self.assertIn("different target", err)
        self.assertEqual(sp.read_text(encoding="utf-8"), before,
                         "conflict must never overwrite the existing anchor")

    def test_arm_without_repo_or_layout_exits_2_with_recipe(self):
        run = self._run_dir(make_repo_layout=False)
        code, out, err = self._run("--run-dir", str(run), "--arm-sentinel")
        self.assertEqual(code, 2)
        self.assertIn("--repo", err)
        # explicit --repo makes it effective even outside the standard layout
        target = self.tmp / "explicit-repo"
        code, out, err = self._run("--run-dir", str(run), "--repo", str(target),
                                   "--arm-sentinel")
        self.assertEqual(code, 0, err)
        self.assertTrue((target / ".mgh-sdr" / ".active").is_file())

    def test_arm_and_rearm_are_mutually_exclusive(self):
        run = self._run_dir()
        code, out, err = self._run("--run-dir", str(run), "--arm-sentinel",
                                   "--rearm-sentinel")
        self.assertEqual(code, 2)
        self.assertIn("not allowed with argument", err)

    def test_not_started_next_action_carries_arm_recipe(self):
        run = self._run_dir()
        st = self._state(run)
        self.assertEqual(st["step"], "not-started")
        desc = st["next_action"]["desc"]
        self.assertIn("--arm-sentinel", desc)
        self.assertIn("sdr_context.py", desc)
        self.assertLess(desc.index("--arm-sentinel"), desc.index("sdr_context.py"),
                        "pre-arm must come BEFORE step 1 in the recipe")


class TelemetryMountTest(unittest.TestCase):
    """Usage-telemetry mount (add-mgh-telemetry-seam): the DERIVE path fires with
    `--resume` + state-rebuilt base/branch; --arm-sentinel / --check never fire;
    ANY telemetry failure leaves the state JSON / exit code unchanged. The
    subprocess harness above cannot patch the sibling import, so this class runs
    main() in-process with a fake module in sys.modules."""

    def _main(self, *argv):
        spec = importlib.util.spec_from_file_location("resume_sdr_state_tel", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = sys.argv
        sys.argv = ["resume_sdr_state.py", *argv]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mod.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _run_dir(self):
        run = Path(tempfile.mkdtemp(prefix="mgh_rsdr_tel_")) / "repo" / ".mgh-sdr" \
            / "runs" / TS
        run.mkdir(parents=True)
        (run / "context.json").write_text(json.dumps(
            {"repo": str(run.parent.parent.parent), "base": "master",
             "branch": "feat"}), encoding="utf-8")
        return run

    def _fake(self):
        fake = mock.MagicMock()
        fake.fire.return_value = {"sent": False, "reason": "test"}
        # the host calls resume_params on the module too — delegate it to the REAL
        # implementation so the rebuilt params string is assertable
        spec = importlib.util.spec_from_file_location(
            "mgh_telemetry_helper", SCRIPT.parent / "mgh_telemetry.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        fake.resume_params = helper.resume_params
        return fake

    def test_fire_on_derive_path_with_state_params(self):
        run = self._run_dir()
        fake = self._fake()
        with mock.patch.dict(sys.modules, {"mgh_telemetry": fake}):
            code, out, err = self._main("--run-dir", str(run))
        self.assertEqual(code, 0, err)
        fake.fire.assert_called_once()
        method, params, marker = fake.fire.call_args[0]
        self.assertEqual(method, "mgh-sdr")
        self.assertEqual(params, "--resume --base master --branch feat")
        self.assertEqual(marker, str(run))

    def test_arm_sentinel_never_fires(self):
        run = self._run_dir()
        fake = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"mgh_telemetry": fake}):
            code, _, err = self._main("--run-dir", str(run), "--arm-sentinel")
        self.assertEqual(code, 0, err)
        fake.fire.assert_not_called()

    def test_fire_raising_and_missing_module_keep_state_output(self):
        for patch in (mock.MagicMock(side_effect=RuntimeError("boom")), None):
            run = self._run_dir()
            f = mock.MagicMock()
            if patch is not None:
                f.fire = patch
            mod = {"mgh_telemetry": f} if patch is not None \
                else {"mgh_telemetry": None}
            with mock.patch.dict(sys.modules, mod):
                code, out, err = self._main("--run-dir", str(run))
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["step"], "group")



class SpecialAuthFanoutNoteTest(unittest.TestCase):
    """fanout-step resume note: when the special-auth deployment doc is
    present in the install tree, the stdout notes carry one pointer line
    (credential renewal follows that doc); doc absent → no note, notes
    unchanged. The doc is transiently created at its real (gitignored)
    location and removed afterwards."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.doc = SCRIPT.parent.parent / "mgh-special-auth.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _fanout_state(self):
        run = self.tmp / "repo" / ".mgh-sdr" / "runs" / "20260101_000000"
        run.mkdir(parents=True, exist_ok=True)
        repo = self.tmp / "repo"
        (run / "context.json").write_text(json.dumps({
            "repo": str(repo), "run_dir": str(run), "base": "master",
            "branch": "feat",
            "baseline_path": str(run / "baseline.md"),
            "external_repos": []}), encoding="utf-8")
        (run / "grouping.json").write_text(json.dumps({
            "repo": str(repo), "base": "master", "branch": "feat",
            "empty": False, "total": 2,
            "units": [{"unit_id": "u1", "kind": "standalone", "route": "",
                       "chain": [], "status": "pending"},
                      {"unit_id": "u2", "kind": "standalone", "route": "",
                       "chain": [], "status": "pending"}],
            "done": 0, "failed": 0,
            "excluded": {"count": 0, "by_reason": {}}, "pending": [],
        }, ensure_ascii=False), encoding="utf-8")
        p = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(run)],
                           capture_output=True, text=True, encoding="utf-8")
        assert p.returncode == 0, p.stderr
        return json.loads(p.stdout)

    def test_doc_present_note_and_absent_silent(self):
        # absent (or pre-existing) baseline first
        st = self._fanout_state()
        self.assertEqual(st["step"], "fanout")
        base_notes = list(st["notes"])
        # generic install (doc absent this run): the executed path stays clean
        if not self.doc.exists():
            self.assertNotIn("special-auth", st["next_action"]["desc"])
        has_note_without_doc = any("special-auth deployment doc present" in n
                                   for n in base_notes)
        created = False
        try:
            if not self.doc.exists():
                self.doc.write_text("guide", encoding="utf-8")
                created = True
            st2 = self._fanout_state()
            if created:
                notes_with_doc = st2["notes"]
                self.assertTrue(any("special-auth deployment doc present" in n
                                    and "credential renewal" in n
                                    for n in notes_with_doc))
                # the pointer rides next_action.desc (the executed path), not
                # just notes — a recovering orchestrator may never read notes
                self.assertIn("special-auth deployment doc is PRESENT",
                              st2["next_action"]["desc"])
                self.assertIn("--cred-file <run-dir>/cred.json",
                              st2["next_action"]["desc"])
                self.assertIn("mgh_credentials.py",
                              st2["next_action"]["desc"])
            else:
                # doc already exists on this machine: the note is expected in
                # BOTH states — assert presence in the baseline instead
                self.assertTrue(has_note_without_doc)
        finally:
            if created:
                self.doc.unlink(missing_ok=True)
        if not created and not has_note_without_doc:
            self.fail("doc exists but the fanout note is missing")


class NativeFormResumeTest(unittest.TestCase):
    """fix-mgh-sdr-native-dispatch: the run's repo env profile decides the
    native face. Missing/auto/runner profile → byte-shape unchanged (no
    `dispatch` field, subprocess fanout next_action); profile `native` → the
    `dispatch` field + the fanout arc's sub-phase next_action (materialize when
    no plan artifact yet, same-message wave dispatch once it exists) + the
    native discipline variant on the fanout step only; a malformed profile is
    fail-closed exit 2 through BOTH the derive and --check paths. Progress
    derivation stays purely on-disk in every case."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"

    def tearDown(self):
        self._tmp.cleanup()

    def _run_dir(self):
        run = self.repo / ".mgh-sdr" / "runs" / TS
        (run / "markers").mkdir(parents=True, exist_ok=True)
        (run / "slices").mkdir(exist_ok=True)
        return run

    def _profile(self, body):
        (self.repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.repo / ".mgh" / "env-profile.json").write_text(
            json.dumps(body), encoding="utf-8")

    def _seed(self, run, uids=("u1", "u2", "u3")):
        (run / "context.json").write_text(json.dumps({
            "repo": str(self.repo), "run_dir": str(run), "base": "master",
            "branch": "feat", "baseline_path": str(run / "baseline.md"),
            "external_repos": []}), encoding="utf-8")
        (run / "grouping.json").write_text(json.dumps({
            "repo": str(self.repo), "base": "master", "branch": "feat",
            "empty": False, "total": len(uids),
            "units": [{"unit_id": u, "kind": "interface", "route": "/x",
                       "chain": [], "status": "pending"} for u in uids],
            "done": 0, "failed": 0,
            "excluded": {"count": 0, "by_reason": {}}, "pending": [],
        }, ensure_ascii=False), encoding="utf-8")

    def _mark(self, run, uid, kind="done"):
        (run / "markers" / f"{uid}.{kind}").write_text("{}", encoding="utf-8")

    def _state(self, run, *extra):
        p = subprocess.run([sys.executable, str(SCRIPT), "--run-dir", str(run),
                            *extra], capture_output=True, text=True,
                           encoding="utf-8")
        return p.returncode, p.stdout, p.stderr

    def test_missing_profile_has_no_dispatch_field(self):
        run = self._run_dir()
        self._seed(run)
        code, out, err = self._state(run)
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertEqual(st["step"], "fanout")
        self.assertNotIn("dispatch", st)
        self.assertIn("fanout_runner.py", st["next_action"]["desc"])

    def test_auto_profile_is_subprocess_face(self):
        run = self._run_dir()
        self._seed(run)
        self._profile({"v": 1, "dispatch_mode": "auto"})
        code, out, err = self._state(run)
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertNotIn("dispatch", st)
        self.assertIn("fanout_runner.py", st["next_action"]["desc"])

    def test_native_no_plan_next_action_is_materialize(self):
        run = self._run_dir()
        self._seed(run)
        self._profile({"v": 1, "dispatch_mode": "native"})
        code, out, err = self._state(run)
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertEqual(st["step"], "fanout")
        self.assertEqual(st["dispatch"]["form"], "native")
        self.assertFalse(st["dispatch"]["plan_present"])
        self.assertEqual(st["next_action"]["kind"], "bash")
        desc = st["next_action"]["desc"]
        self.assertIn("emit_native_plan.py", desc)
        self.assertIn("--profile", desc)
        self.assertIn("native_watchdog.py", desc, "watchdog-first rides the arc start")
        self.assertIn("sdr-native-dispatch.md", desc)
        self.assertTrue(Path(st["dispatch"]["discipline_fragment"]).is_absolute())

    def test_native_plan_present_next_action_is_wave_dispatch(self):
        run = self._run_dir()
        self._seed(run)
        self._profile({"v": 1, "dispatch_mode": "native"})
        (run / "native_plan.json").write_text("{}", encoding="utf-8")
        code, out, err = self._state(run)
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertTrue(st["dispatch"]["plan_present"])
        self.assertEqual(st["next_action"]["kind"], "subagent")
        desc = st["next_action"]["desc"]
        self.assertIn("ONE assistant message", desc)
        self.assertIn("sdr-review-native", desc)
        self.assertIn("mgh-dispatch: plan=<plan_path> unit=<short id>", desc)
        self.assertIn("mgh_dispatch.ts", desc)
        self.assertIn("sdr-native-dispatch.md", desc)

    def test_native_marker_combos(self):
        self._profile({"v": 1, "dispatch_mode": "native"})
        # partial done → still fanout, wave dispatch, tiers correct
        run = self._run_dir()
        self._seed(run)
        (run / "native_plan.json").write_text("{}", encoding="utf-8")
        self._mark(run, "u1")
        code, out, err = self._state(run)
        st = json.loads(out)
        self.assertEqual((code, st["step"]), (0, "fanout"))
        self.assertEqual(st["tiers"], {"done": 1, "failed": 0, "total": 3})
        # has failed → retry-once note rides notes
        self._mark(run, "u2", "failed")
        code, out, err = self._state(run)
        st = json.loads(out)
        self.assertEqual(st["step"], "fanout")
        self.assertTrue(any("AT MOST ONE" in n for n in st["notes"]), st["notes"])
        self.assertEqual(st["tiers"], {"done": 1, "failed": 1, "total": 3})
        # native discipline variant on the fanout step only
        self.assertIn("sdr-native-wave",
                      json.dumps(st["discipline_reminders"]))
        # all terminal → render, dispatch field still present (form-level)
        self._mark(run, "u3")
        code, out, err = self._state(run)
        st = json.loads(out)
        self.assertEqual(st["step"], "render")
        self.assertIn("dispatch", st)
        self.assertNotIn("sdr-native-wave",
                         json.dumps(st["discipline_reminders"]))

    def test_bad_profile_fail_closed_derive_and_check(self):
        run = self._run_dir()
        self._seed(run)
        self._profile({"v": 1, "dispatch_mode": "wrong"})
        code, out, err = self._state(run)
        self.assertEqual(code, 2)
        self.assertIn("env profile rejected", err)
        code, out, err = self._state(run, "--check")
        self.assertEqual(code, 2)
        self.assertIn("env profile rejected", out + err)

    def test_native_no_plan_watchdog_note_when_artifacts_absent(self):
        run = self._run_dir()
        self._seed(run)
        self._profile({"v": 1, "dispatch_mode": "native"})
        code, out, err = self._state(run)
        st = json.loads(out)
        self.assertTrue(any("watchdog artifacts absent" in n for n in st["notes"]))
        # subprocess face (profile removed) never carries the watchdog note
        (self.repo / ".mgh" / "env-profile.json").unlink()
        code, out, err = self._state(run)
        st2 = json.loads(out)
        self.assertNotIn("dispatch", st2)
        self.assertFalse(any("watchdog artifacts absent" in n for n in st2["notes"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
