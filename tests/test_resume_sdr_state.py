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
import json
import os
import subprocess
import sys
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
