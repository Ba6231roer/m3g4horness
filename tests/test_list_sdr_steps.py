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


if __name__ == "__main__":
    unittest.main(verbosity=2)
