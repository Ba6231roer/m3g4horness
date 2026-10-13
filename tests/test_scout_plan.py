#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plan_scout.py (D4 byte-budget + package-co-located batching)."""
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


def _skeleton(files):
    """files: list of (rel, pkg, bytes, regex_hit)."""
    return {"repo": "x", "generated_by": "discover_controls.py",
            "files": [{"file": r, "lang": "java", "pkg": p, "classes": [],
                       "imports": [], "method_sigs": [], "fan_in": 0,
                       "bytes": b, "regex_hit": h} for (r, p, b, h) in files]}


class TestPlanScout(unittest.TestCase):
    def setUp(self):
        self.ps = _load("plan_scout")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_sp_"))

    def _plan(self, skeleton, candidates=None, batch_bytes=98304, batch_cap=40, budget=0):
        sk = self.tmp / "skeleton.json"
        sk.write_text(json.dumps(skeleton), encoding="utf-8")
        cand = self.tmp / "cands.json"
        cand.write_text(json.dumps({"candidates": candidates or []}), encoding="utf-8")
        out = self.tmp / "scout_plan.json"
        argv = ["plan_scout.py", "--skeleton", str(sk), "--candidates", str(cand),
                "--out", str(out), "--batch-bytes", str(batch_bytes),
                "--batch-cap", str(batch_cap), "--budget", str(budget)]
        old, sys.argv = sys.argv, argv
        try:
            rc = self.ps.main()
        finally:
            sys.argv = old
        self.assertEqual(rc, 0)
        return json.loads(out.read_text(encoding="utf-8"))

    def test_targets_exclude_regex_hit(self):
        sk = _skeleton([("a/A.java", "a", 100, False), ("b/B.java", "b", 100, True)])
        plan = self._plan(sk)
        files = [t["file"] for bat in plan["batches"] for t in bat["targets"]]
        self.assertIn("a/A.java", files)
        self.assertNotIn("b/B.java", files)  # regex_hit -> already a candidate, scout skips

    def test_batch_byte_budget_respected(self):
        # 5 files x 30KB = 150KB; batch_bytes=96KB -> >=2 batches, each <= 96KB
        sk = _skeleton([(f"p/F{i}.java", "p", 30000, False) for i in range(5)])
        plan = self._plan(sk, batch_bytes=96000)
        self.assertGreaterEqual(len(plan["batches"]), 2)
        for bat in plan["batches"]:
            self.assertLessEqual(bat["bytes"], 96000)

    def test_package_colocation(self):
        # same-package files sorted adjacent -> land in the same batch when under budget
        sk = _skeleton([("p1/A.java", "p1", 1000, False), ("p1/B.java", "p1", 1000, False),
                        ("p2/C.java", "p2", 1000, False)])
        plan = self._plan(sk, batch_bytes=100000)
        same_pkg = next(b for b in plan["batches"]
                        if any(t["file"] == "p1/A.java" for t in b["targets"]))
        files = {t["file"] for t in same_pkg["targets"]}
        self.assertIn("p1/A.java", files)
        self.assertIn("p1/B.java", files)

    def test_oversize_file_marked_for_slice(self):
        sk = _skeleton([("big/X.java", "big", 250000, False)])
        plan = self._plan(sk, batch_bytes=96000)
        bat = plan["batches"][0]
        self.assertEqual(len(bat["targets"]), 1)
        self.assertEqual(bat["needs_slice"], ["big/X.java"])

    def test_batch_cap_respected(self):
        sk = _skeleton([(f"p/F{i}.java", "p", 100, False) for i in range(50)])
        plan = self._plan(sk, batch_bytes=10_000_000, batch_cap=40)
        for bat in plan["batches"]:
            self.assertLessEqual(len(bat["targets"]), 40)

    def test_budget_truncation(self):
        sk = _skeleton([(f"p/F{i}.java", "p", 100, False) for i in range(100)])
        plan = self._plan(sk, batch_bytes=10_000_000, batch_cap=40, budget=10)
        self.assertTrue(plan["truncated"])
        total_targets = sum(len(b["targets"]) for b in plan["batches"])
        self.assertLessEqual(total_targets, 10)

    def test_batch_ids_sequential(self):
        sk = _skeleton([(f"p/F{i}.java", "p", 100, False) for i in range(90)])
        plan = self._plan(sk, batch_bytes=960, batch_cap=40)
        ids = [b["batch_id"] for b in plan["batches"]]
        self.assertEqual(ids, [f"scout-{i:03d}" for i in range(1, len(ids) + 1)])


class TestPlanSelfDescribingCheck(unittest.TestCase):
    """M2: the plan records the generation-time `batch_bytes`/`batch_cap` at top
    level and `--check` judges the budget by the RECORDED value — a custom-budget
    plan re-checked with default flags is zero-violation (pre-fix the check fell
    back to the CLI default 98304 and mis-flagged the plan's oversize batches →
    rollback loop). A corrupt plan (malformed JSON / wrong wrapper shape) fails
    the boundary check with exit 2 (the gate recipe only recognizes 2), never 1.
    A legacy plan without the record falls back to the CLI value (compat anchor)."""

    def setUp(self):
        self.ps = _load("plan_scout")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_spc_"))

    def _gen(self, batch_bytes, batch_cap=40):
        sk = {"repo": "x", "generated_by": "discover_controls.py", "files": [
            {"file": f"p/F{i}.java", "lang": "java", "pkg": "p", "classes": [],
             "imports": [], "method_sigs": [], "fan_in": 0, "bytes": 30000,
             "regex_hit": False} for i in range(8)]}
        sk_p = self.tmp / "skeleton.json"
        sk_p.write_text(json.dumps(sk), encoding="utf-8")
        cand = self.tmp / "cands.json"
        cand.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        out = self.tmp / "scout_plan.json"
        argv = ["plan_scout.py", "--skeleton", str(sk_p), "--candidates", str(cand),
                "--out", str(out), "--batch-bytes", str(batch_bytes),
                "--batch-cap", str(batch_cap)]
        old, sys.argv = sys.argv, argv
        try:
            rc = self.ps.main()
        finally:
            sys.argv = old
        self.assertEqual(rc, 0)
        return out

    def _check(self, plan_path, *extra):
        argv = ["plan_scout.py", "--check", str(plan_path)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = self.ps.main()
        finally:
            sys.argv = old
        return rc, out.getvalue(), err.getvalue()

    def test_plan_records_generation_budget(self):
        out = self._gen(204800)
        plan = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(plan["batch_bytes"], 204800)
        self.assertEqual(plan["batch_cap"], 40)

    def test_custom_budget_plan_zero_violation_under_default_check(self):
        out = self._gen(204800)
        rc, o, _ = self._check(out)          # NO --batch-bytes: default 98304
        self.assertEqual(rc, 0, o)           # judged by the recorded 204800
        self.assertTrue(json.loads(o)["ok"])

    def test_corrupt_plan_malformed_json_exit_2(self):
        p = self.tmp / "broken.json"
        p.write_text('{"batches": [', encoding="utf-8")
        rc, o, _ = self._check(p)
        self.assertEqual(rc, 2)              # NOT 1 — gate recipe only knows 2

    def test_corrupt_plan_wrong_wrapper_exit_2(self):
        p = self.tmp / "broken.json"
        p.write_text(json.dumps({"batches": "not-a-list"}), encoding="utf-8")
        rc, o, _ = self._check(p)
        self.assertEqual(rc, 2)

    def test_legacy_plan_without_record_falls_back_to_cli_value(self):
        # a pre-self-description plan (no batch_bytes field) keeps the old
        # semantics: the CLI --batch-bytes value judges the budget
        plan = {"repo": "x", "targets_total": 1, "truncated": False, "batches": [
            {"batch_id": "scout-001", "targets": [{"file": "a.java", "bytes": 500}],
             "bytes": 500, "needs_slice": []}]}
        p = self.tmp / "legacy.json"
        p.write_text(json.dumps(plan), encoding="utf-8")
        rc, o, _ = self._check(p, "--batch-bytes", "600")
        self.assertEqual(rc, 0)
        rc, o, _ = self._check(p, "--batch-bytes", "400")
        self.assertEqual(rc, 2)              # 500 > 400 → violation (CLI fallback)

    def test_missing_plan_exit_2(self):
        rc, _, _ = self._check(self.tmp / "nope.json")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
