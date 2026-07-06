#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""R5.9 stage-boundary --check tests: good artifact -> exit 0, broken -> exit 2.

Covers discover_controls / plan_scout / merge_scout --check + validate_inventory.
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


def _run(mod, argv):
    old, sys.argv = sys.argv, ["x.py", *argv]
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.argv = old
    return code


class TestDiscoverCheck(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.dir = Path(tempfile.mkdtemp(prefix="mgh_dchk_"))

    def _dir(self, cands, clusters):
        (self.dir / "controls_candidates.json").write_text(
            json.dumps({"repo": "r", "candidates": cands}, ensure_ascii=False), encoding="utf-8")
        (self.dir / "clusters.json").write_text(
            json.dumps({"repo": "r", "clusters": clusters, "truncated": False},
                       ensure_ascii=False), encoding="utf-8")

    def test_good(self):
        self._dir([{"id": "C-1", "file": "a.java", "source": "regex"}],
                  [{"cluster_id": "a::A::1", "category": "authorization"}])
        self.assertEqual(_run(self.d, ["--check", str(self.dir)]), 0)

    def test_bad_missing_source(self):
        self._dir([{"id": "C-1", "file": "a.java"}],  # no source
                  [{"cluster_id": "a::A::1", "category": "authorization"}])
        self.assertEqual(_run(self.d, ["--check", str(self.dir)]), 2)

    def test_bad_dup_cluster_id(self):
        self._dir([{"id": "C-1", "file": "a.java", "source": "regex"}],
                  [{"cluster_id": "dup", "category": "authorization"},
                   {"cluster_id": "dup", "category": "crypto"}])
        self.assertEqual(_run(self.d, ["--check", str(self.dir)]), 2)


class TestPlanScoutCheck(unittest.TestCase):
    def setUp(self):
        self.d = _load("plan_scout")
        self.dir = Path(tempfile.mkdtemp(prefix="mgh_pchk_"))

    def _plan(self, batches, targets_total=2):
        (self.dir / "plan.json").write_text(json.dumps(
            {"repo": "r", "targets_total": targets_total, "batches": batches},
            ensure_ascii=False), encoding="utf-8")

    def test_good(self):
        self._plan([{"batch_id": "scout-001", "targets": [{"file": "a.java", "bytes": 100}],
                     "bytes": 100, "needs_slice": []}])
        self.assertEqual(_run(self.d, ["--check", str(self.dir / "plan.json"),
                                      "--batch-bytes", "98304"]), 0)

    def test_bad_over_budget_unsliced(self):
        self._plan([{"batch_id": "scout-001",
                     "targets": [{"file": "a.java", "bytes": 999999}],
                     "bytes": 999999, "needs_slice": []}])  # oversize but not sliced
        self.assertEqual(_run(self.d, ["--check", str(self.dir / "plan.json"),
                                      "--batch-bytes", "98304"]), 2)


class TestMergeScoutCheck(unittest.TestCase):
    def setUp(self):
        self.d = _load("merge_scout")
        self.dir = Path(tempfile.mkdtemp(prefix="mgh_mchk_"))

    def test_good(self):
        (self.dir / "sc.json").write_text(json.dumps({"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout", "category": "crypto"}]}),
            encoding="utf-8")
        self.assertEqual(_run(self.d, ["--check", str(self.dir / "sc.json")]), 0)

    def test_bad_wrong_source(self):
        (self.dir / "sc.json").write_text(json.dumps({"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "regex", "category": "crypto"}]}),
            encoding="utf-8")
        self.assertEqual(_run(self.d, ["--check", str(self.dir / "sc.json")]), 2)


class TestValidateInventory(unittest.TestCase):
    def setUp(self):
        self.d = _load("validate_inventory")
        self.dir = Path(tempfile.mkdtemp(prefix="mgh_vchk_"))

    def _inv(self, controls):
        (self.dir / "inv.json").write_text(json.dumps(
            {"repo": "r", "format": "claude", "controls": controls}, ensure_ascii=False),
            encoding="utf-8")

    def test_good(self):
        self._inv([{"name": "a", "kind": "auth", "category": "authorization",
                    "evidence": ["a.java:Auth:check"]}])
        self.assertEqual(_run(self.d, ["--inventory", str(self.dir / "inv.json")]), 0)

    def test_bad_kind_drift(self):
        self._inv([{"name": "a", "kind": "sandbox", "category": "authorization",
                    "evidence": ["a.java:1"]}])  # auth category, sandbox kind
        self.assertEqual(_run(self.d, ["--inventory", str(self.dir / "inv.json")]), 2)

    def test_bad_missing_evidence(self):
        self._inv([{"name": "a", "kind": "auth", "category": "authorization", "evidence": []}])
        self.assertEqual(_run(self.d, ["--inventory", str(self.dir / "inv.json")]), 2)


if __name__ == "__main__":
    unittest.main()
