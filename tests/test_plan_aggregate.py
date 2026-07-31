#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plan_aggregate.py — hard-budget aggregate map-reduce gate.

Asserts: ≤ budget → needs_reduce=false (single-context path); > budget → needs_reduce=true,
each shard ≤ budget, pending[] carries input_path; paging shrunk/effective_limit; t2 sharding
by category, scout-merge by batch cluster; absolute paths.
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


PA = _load("plan_aggregate")


class _Agg:
    def __init__(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_pa_"))
        self.init = self.target / ".mgh-init"
        self.init.mkdir(parents=True, exist_ok=True)

    def write_t1(self, records):
        cp = self.init / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(records):
            (cp / f"unit-{i:03d}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def write_scout(self, records):
        cp = self.init / "checkpoints" / "scout"
        cp.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(records):
            (cp / f"scout-{i:03d}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def run(self, *extra):
        argv = ["plan_aggregate.py", "--init-dir", str(self.init)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = PA.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()


SMALL = [{"category": "authorization", "name": "a", "kind": "auth"},
         {"category": "crypto", "name": "b", "kind": "other"}]


class TestPlanAggregateT2(unittest.TestCase):
    def setUp(self):
        self.a = _Agg()

    def test_under_budget_single_context(self):
        self.a.write_t1(SMALL)
        code, out, _ = self.a.run("--node", "t2", "--budget", "100000")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertFalse(d["needs_reduce"])
        self.assertEqual(d["pending"], [])
        self.assertNotIn("rollup", d)

    def test_over_budget_needs_reduce_shards_by_category(self):
        records = [{"category": c, "name": f"n{i}", "kind": "auth", "pad": "x" * 2000}
                   for i, c in enumerate(["authorization"] * 3 + ["crypto"] * 3 + ["csrf"] * 3)]
        self.a.write_t1(records)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4000", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertEqual(d["shards"], 3)  # one per category
        cats = sorted(item["categories"][0] for item in d["pending"])
        self.assertEqual(cats, ["authorization", "crypto", "csrf"])
        for item in d["pending"]:
            self.assertIn("input_path", item)
            self.assertTrue(Path(item["checkpoint_path"]).is_absolute())
            self.assertTrue(item["done_marker"].endswith(".done"))
        self.assertIn("rollup", d)
        self.assertTrue(d["rollup"]["output"].endswith("controls_inventory.json"))

    def test_paging_and_shrink(self):
        records = [{"category": f"cat-{i}", "name": "n", "kind": "auth", "pad": "x" * 1000}
                   for i in range(6)]
        self.a.write_t1(records)
        self.a.run("--node", "t2", "--budget", "500", "--materialize", str(self.a.init / "shards"))
        _, out, _ = self.a.run("--node", "t2", "--budget", "500", "--offset", "0", "--limit", "2",
                               "--materialize", str(self.a.init / "shards"))
        d = json.loads(out)
        self.assertLessEqual(len(d["pending"]), 2)
        _, out2, _ = self.a.run("--node", "t2", "--budget", "500", "--orch-budget-bytes", "60",
                                "--materialize", str(self.a.init / "shards"))
        self.assertTrue(json.loads(out2)["shrunk"])

    def test_empty_records_single_context(self):
        code, out, _ = self.a.run("--node", "t2", "--budget", "1000")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["needs_reduce"])


class TestPlanAggregateScoutMerge(unittest.TestCase):
    def test_over_budget_batches_packed_into_shards(self):
        a = _Agg()
        records = [{"batch_id": f"scout-{i:03d}", "candidates": [{"pad": "y" * 2000}]}
                   for i in range(8)]
        a.write_scout(records)
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertGreater(d["shards"], 1)
        self.assertTrue(d["rollup"]["output"].endswith("scout_candidates.json"))
        self.assertTrue(d["rollup"]["done_marker"].endswith("merge.json.done"))


class TestBadInput(unittest.TestCase):
    def test_negative_budget_exit2(self):
        a = _Agg()
        code, _, _ = a.run("--node", "t2", "--budget", "-1")
        self.assertEqual(code, 2)

    def test_init_dir_missing_exit1(self):
        argv = ["plan_aggregate.py", "--node", "t2", "--init-dir", "/no/such/dir"]
        old, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = PA.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
