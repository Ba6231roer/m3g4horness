#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_scout_batches.py + list_rule_jobs.py (FD3 enumeration closure).

Both mirror list_clusters.py (resume-aware pending work-list). Asserts:
  - total = real list length, NOT wrapper key count;
  - pending excludes done units (.done marker); total == done + len(pending);
  - empty / truncated handled without silent loss.
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


_BATCHES = [
    {"batch_id": "scout-001", "targets": [{"file": "a.java"}], "bytes": 100, "needs_slice": []},
    {"batch_id": "scout-002", "targets": [{"file": "b.java"}], "bytes": 200, "needs_slice": ["b.java"]},
    {"batch_id": "scout-003", "targets": [{"file": "c.java"}], "bytes": 300, "needs_slice": []},
]


class TestListScoutBatches(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_scout_batches")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lsb_"))

    def _run(self, plan, checkpoints=None):
        argv = ["list_scout_batches.py", "--scout-plan", str(plan)]
        if checkpoints:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _write(self, batches, truncated=False):
        p = self.d / "scout_plan.json"
        p.write_text(json.dumps({"repo": str(self.d), "targets_total": len(batches),
                                 "regex_known_count": 0, "truncated": truncated,
                                 "batches": batches}, ensure_ascii=False), encoding="utf-8")
        return p

    def _mark_done(self, bid):
        cp = self.d / "checkpoints" / "scout"
        cp.mkdir(parents=True, exist_ok=True)
        rec = cp / f"{bid}.json"
        rec.write_text(json.dumps({"batch_id": bid}), encoding="utf-8")
        rec.with_name(rec.name + ".done").write_text("", encoding="utf-8")

    def test_total_is_batch_count_not_wrapper_keys(self):
        code, out, _ = self._run(self._write(_BATCHES))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 3)

    def test_resume_pending_excludes_done(self):
        p = self._write(_BATCHES)
        cp = self.d / "checkpoints" / "scout"
        self._mark_done("scout-002")
        code, out, _ = self._run(p, cp)
        data = json.loads(out)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["done"], 1)
        ids = [b["batch_id"] for b in data["pending"]]
        self.assertNotIn("scout-002", ids)
        self.assertEqual(len(ids), 2)
        self.assertEqual(data["total"], data["done"] + len(data["pending"]))

    def test_lite_shape(self):
        code, out, _ = self._run(self._write(_BATCHES))
        by = {b["batch_id"]: b for b in json.loads(out)["pending"]}
        self.assertEqual(by["scout-002"]["targets_count"], 1)
        self.assertEqual(by["scout-002"]["needs_slice"], ["b.java"])
        self.assertEqual(by["scout-002"]["bytes"], 200)

    def test_empty_batches(self):
        code, out, _ = self._run(self._write([]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["done"], 0)

    def test_truncated_passthrough(self):
        code, out, _ = self._run(self._write(_BATCHES, truncated=True))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["truncated"])

    def test_missing_checkpoints_all_pending(self):
        code, out, _ = self._run(self._write(_BATCHES), self.d / "nope")
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)

    def test_missing_file_exit1(self):
        code, _, _ = self._run(self.d / "nope.json")
        self.assertEqual(code, 1)


class TestListRuleJobs(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_rule_jobs")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lrj_"))

    def _run(self, inv, fmt="opencode", checkpoints=None, target="."):
        argv = ["list_rule_jobs.py", "--inventory", str(inv), "--format", fmt, "--target", target]
        if checkpoints:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _write(self, controls):
        p = self.d / "controls_inventory.json"
        p.write_text(json.dumps({"repo": str(self.d), "format": "opencode",
                                 "controls": controls}, ensure_ascii=False), encoding="utf-8")
        return p

    def _mark_done(self, cat, fmt):
        cp = self.d / "checkpoints" / "t3"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{cat}.{fmt}.json.done").write_text("", encoding="utf-8")

    def test_distinct_categories(self):
        p = self._write([{"name": "a", "category": "authorization"},
                         {"name": "b", "category": "crypto"},
                         {"name": "c", "category": "crypto"}])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 2)  # distinct categories, not control count
        self.assertEqual(sorted(j["category"] for j in data["pending"]),
                         ["authorization", "crypto"])
        self.assertIn("rule_path", data["pending"][0])

    def test_resume_excludes_done(self):
        p = self._write([{"name": "a", "category": "authorization"},
                         {"name": "b", "category": "crypto"}])
        cp = self.d / "checkpoints" / "t3"
        self._mark_done("crypto", "opencode")
        code, out, _ = self._run(p, checkpoints=cp)
        data = json.loads(out)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["done"], 1)
        self.assertEqual([j["category"] for j in data["pending"]], ["authorization"])

    def test_empty_inventory(self):
        code, out, _ = self._run(self._write([]))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 0)

    def test_claude_rule_path(self):
        p = self._write([{"name": "a", "category": "crypto"}])
        code, out, _ = self._run(p, fmt="claude", target="/tmp/proj")
        rp = json.loads(out)["pending"][0]["rule_path"]
        self.assertIn(".claude/rules/security-crypto.md", rp)


if __name__ == "__main__":
    unittest.main()
