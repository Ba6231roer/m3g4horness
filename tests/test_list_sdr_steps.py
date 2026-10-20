#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""list_sdr_steps.py unit tests (add-mgh-sdr-resume-surface task 4.2).

The manifest must (a) resolve every script path absolutely from __file__, (b) stay
queryable with zero disk preconditions, (c) reject unknown step ids with exit 2, and
(d) carry EXACTLY the discipline subset `resume_sdr_state.py` reports for the same
step — one static table, two consumers, asserted byte-verbatim here.

Run: py tests/test_list_sdr_steps.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
SCRIPT = SCRIPTS / "list_sdr_steps.py"
RESUME = SCRIPTS / "resume_sdr_state.py"

STEP_IDS = {"not-started", "group", "fanout", "render", "done"}


class ListSdrStepsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args, cwd=None):
        p = subprocess.run([sys.executable, str(SCRIPT), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           cwd=cwd or self.tmp)
        return p.returncode, p.stdout, p.stderr

    def test_emits_all_steps_with_absolute_scripts(self):
        code, out, err = self._run()
        self.assertEqual(code, 0, err)
        steps = json.loads(out)["steps"]
        self.assertEqual({s["step"] for s in steps}, STEP_IDS)
        for s in steps:
            if s["script"] is None:
                self.assertEqual(s["step"], "done")
                self.assertIsNone(s["script_abs"])
                self.assertIsNone(s["invocation"])
                continue
            self.assertTrue(Path(s["script_abs"]).is_absolute(), s["script_abs"])
            self.assertTrue(Path(s["script_abs"]).is_file(), s["script_abs"])
            self.assertTrue(s["invocation"].startswith("py "), s["invocation"])
            self.assertIn(s["script_abs"], s["invocation"])

    def test_queryable_from_any_cwd_with_zero_disk_preconditions(self):
        else_where = self.tmp / "some" / "where"
        else_where.mkdir(parents=True)
        code, out, err = self._run(cwd=else_where)
        self.assertEqual(code, 0, err)
        self.assertEqual({s["step"] for s in json.loads(out)["steps"]}, STEP_IDS)

    def test_step_filter_emits_one(self):
        code, out, err = self._run("--step", "fanout")
        self.assertEqual(code, 0, err)
        steps = json.loads(out)["steps"]
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["step"], "fanout")

    def test_unknown_step_id_exits_2_and_lists_known(self):
        code, out, err = self._run("--step", "bogus")
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "", "no JSON on a misuse exit")
        for known in STEP_IDS:
            self.assertIn(known, err)

    def test_numeric_step_index_rejected_with_hint(self):
        code, out, err = self._run("--step", "0")
        self.assertEqual(code, 2)
        self.assertIn("NAMED", err)

    def test_target_must_be_a_dir(self):
        code, out, err = self._run("--target", str(self.tmp / "nope"))
        self.assertEqual(code, 1)

    def test_discipline_is_verbatim_identical_to_resume_sdr_state(self):
        # one static table, two consumers: --step X here must equal the
        # discipline_reminders resume_sdr_state reports when the run sits on X.
        run = self.tmp / "repo" / ".mgh-sdr" / "runs" / "20260918_120000-feat"
        run.mkdir(parents=True)
        repo = self.tmp / "repo"
        fmt = {"repo": str(repo), "base": "master", "branch": "feat"}
        (run / "context.json").write_text(json.dumps(fmt), encoding="utf-8")
        (run / "grouping.json").write_text(json.dumps(dict(
            fmt, empty=False, total=1, units=[{"unit_id": "u1", "status": "pending"}],
            done=0, failed=0, excluded={"count": 0, "by_reason": {}}, pending=[],
        )), encoding="utf-8")
        (run / "markers").mkdir()
        (run / "markers" / "u1.done").write_text("{}", encoding="utf-8")
        (run / "sdr_manifest.json").write_text("{}", encoding="utf-8")

        for step in ("group", "fanout", "render", "done", "not-started"):
            with self.subTest(step=step):
                code, out, err = self._run("--step", step)
                self.assertEqual(code, 0, err)
                listed = json.loads(out)["steps"][0]["discipline"]
                # the live run sits on `done`; compare the static tables against the
                # same-domain lookup resume_sdr_state would use for that step.
                sys.path.insert(0, str(SCRIPTS))
                from discipline_core import get_discipline
                self.assertEqual(listed, get_discipline(step, domain="sdr"))

    def test_live_run_reports_the_same_discipline_object(self):
        run = self.tmp / "repo" / ".mgh-sdr" / "runs" / "20260918_120000-feat"
        run.mkdir(parents=True)
        repo = self.tmp / "repo"
        (run / "context.json").write_text(json.dumps(
            {"repo": str(repo), "base": "master", "branch": "feat"}), encoding="utf-8")
        (run / "grouping.json").write_text(json.dumps(
            {"repo": str(repo), "base": "master", "branch": "feat", "empty": False,
             "total": 1, "units": [{"unit_id": "u1", "status": "pending"}], "done": 0,
             "failed": 0, "excluded": {"count": 0, "by_reason": {}}, "pending": []}),
            encoding="utf-8")
        (run / "markers").mkdir()
        (run / "markers" / "u1.done").write_text("{}", encoding="utf-8")
        p = subprocess.run([sys.executable, str(RESUME), "--run-dir", str(run)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        state = json.loads(p.stdout)
        self.assertEqual(state["step"], "render")
        code, out, err = self._run("--step", "render")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["steps"][0]["discipline"],
                         state["discipline_reminders"])

    def test_render_step_names_html_report_and_data_file(self):
        # improve-mgh-sdr-report-html-render: the render step's output surface is the
        # self-contained .html report + the canonical data file beside the manifest —
        # a stale `.md` pattern here would send an agent hunting a file that is never
        # produced again.
        code, out, err = self._run("--step", "render")
        self.assertEqual(code, 0, err)
        pattern = json.loads(out)["steps"][0]["output"]["path_pattern"]
        self.assertIn(".html", pattern)
        self.assertNotIn(".md", pattern)
        self.assertIn("sdr_report_data.json", pattern)
        self.assertIn("sdr_manifest.json", pattern)


class ShellOutsourcedInvocationAnchorTest(unittest.TestCase):
    """fix-mgh-sdr-quota-adaptive-fanout 7.x: the shells outsourced the canonical
    call lines to this manifest (D8 A案) — the manifest is now the assertion home
    for (a) the `--wave 1` serial default + quota triple on the fanout invocation,
    (b) the step-level recipes that left the shells (fast-fail storm tri-layer,
    slice-budget calibration)."""

    def test_fanout_invocation_wave1_and_quota_flags(self):
        p = subprocess.run([sys.executable, str(SCRIPT), "--step", "fanout"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        inv = json.loads(p.stdout)["steps"][0]["invocation"]
        for needle in ("--wave 1", "--quota-calls <N>", "--quota-window-s <W>",
                       "--quota-calls-per-unit <K>", "--time-budget-ms",
                       "--call-timeout-s", "--stall-timeout-s"):
            self.assertIn(needle, inv, needle)

    def test_fanout_discipline_carries_storm_trilayer_and_quota(self):
        sys.path.insert(0, str(SCRIPTS))
        from discipline_core import get_discipline
        d = get_discipline("fanout", domain="sdr")
        text = json.dumps(d, ensure_ascii=False)
        # tri-layer: congestion re-dispatch / rate-limit window wait / retry-failed once
        for needle in ("stalled:true", "rate_limited:true", "配额窗口", "--retry-failed",
                       "--quota-calls", "--quota-window-s", "--quota-calls-per-unit",
                       "--wave 1"):
            self.assertIn(needle, text, needle)

    def test_group_discipline_carries_budget_calibration(self):
        sys.path.insert(0, str(SCRIPTS))
        from discipline_core import get_discipline
        d = get_discipline("group", domain="sdr")
        text = json.dumps(d, ensure_ascii=False)
        for needle in ("96KB", "98304", "65536", "150K", "-partN", "粘滞",
                       "grouping.json"):
            self.assertIn(needle, text, needle)



class SpecialAuthFieldTest(unittest.TestCase):
    """The top-level special_auth presence field (the manifest's ONE allowed
    disk probe): absent doc → {present: false, path: null} with every other
    field unchanged; present doc → {present: true, path: <abs>}. The doc is
    transiently created at <mgh-core>/mgh-special-auth.md (its real,
    gitignored location) and removed in the finally block."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.doc = SCRIPT.parent.parent / "mgh-special-auth.md"

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self):
        p = subprocess.run([sys.executable, str(SCRIPT)],
                           capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout, p.stderr

    def test_absent_doc_shape(self):
        code, out, err = self._run()
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["special_auth"], {"present": False, "path": None})
        # the steps surface is untouched by the new field
        self.assertEqual({s["step"] for s in d["steps"]}, STEP_IDS)

    def test_present_doc_shape(self):
        created = False
        try:
            if not self.doc.exists():
                self.doc.write_text("guide", encoding="utf-8")
                created = True
            code, out, err = self._run()
            self.assertEqual(code, 0, err)
            d = json.loads(out)
            self.assertTrue(d["special_auth"]["present"])
            self.assertTrue(Path(d["special_auth"]["path"]).is_absolute())
        finally:
            if created:
                self.doc.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
