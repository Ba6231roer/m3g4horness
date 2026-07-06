#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Runtime robustness tests for the /mgh-init discover pipeline (FD2 / FD3).

These complement test_init_discover.py / test_init_clusters.py (which load modules
IN-PROCESS after `sys.path.insert(SCRIPTS)`) by exercising the scripts as REAL
SUBPROCESSES from a NON-script cwd — proving the sibling-import self-location (FD2)
and the single-pass rewrite (FD3) work end-to-end without the test harness masking
them. Run with: py -3 tests/test_init_runtime.py
"""
import json, subprocess, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
DISCOVER = SCRIPTS / "discover_controls.py"
CHUNK = SCRIPTS / "chunk_sources.py"
LIST = SCRIPTS / "list_clusters.py"
PY = sys.executable  # real interpreter when launched via `py -3`


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


CONTROLLER = """\
package com.bank.api;
import com.bank.util.MaskUtil;
public class TransferController {
  @PreAuthorize("hasRole('USER')")
  public String transfer(@Valid String card) {
    return MaskUtil.mask(card);
  }
}
"""
MASK = """\
package com.bank.util;
public class MaskUtil {
  public static String mask(String s) { return s.substring(0,2); }
}
"""


class TestStandaloneInvocation(unittest.TestCase):
    """FD2: scripts run as subprocesses from a NON-script cwd without import errors."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_rt_"))
        _write(self.repo, "src/main/java/com/bank/api/TransferController.java", CONTROLLER)
        _write(self.repo, "src/main/java/com/bank/util/MaskUtil.java", MASK)
        self.out = Path(tempfile.mkdtemp(prefix="mgh_rt_out_"))
        self.cwd = self.repo  # run from repo root, NOT the scripts dir

    def _run(self, script, *args):
        return subprocess.run([PY, str(script), *args], cwd=str(self.cwd),
                              capture_output=True, text=True, encoding="utf-8")

    def test_discover_runs_from_non_script_cwd(self):
        r = self._run(DISCOVER, "--repo", ".", "--out", str(self.out))
        self.assertEqual(r.returncode, 0,
                         f"discover failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        self.assertNotIn("No module named 'expand_scope'", r.stderr + r.stdout)

    def test_discover_needs_no_python_c_workaround(self):
        # Direct execution works; no gbk/UnicodeDecodeError from reading own source.
        r = self._run(DISCOVER, "--repo", ".", "--out", str(self.out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("UnicodeDecodeError", r.stderr + r.stdout)

    def test_chunk_sources_runs_from_non_script_cwd(self):
        big = _write(self.repo, "src/main/java/com/bank/Big.java",
                     "package com.bank;\npublic class Big {\n"
                     "  public void m(){ return; }\n}\n")
        r = self._run(CHUNK, "--in", str(big), "--line", "3",
                      "--out", str(self.out / "slice.json"))
        self.assertEqual(r.returncode, 0,
                         f"chunk_sources failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        self.assertNotIn("No module named 'expand_scope'", r.stderr + r.stdout)


class TestSinglePassEquivalence(unittest.TestCase):
    """FD3: single-pass rewrite preserves the candidate/cluster contract."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_eq_"))
        _write(self.repo, "src/main/java/com/bank/api/TransferController.java", CONTROLLER)
        _write(self.repo, "src/main/java/com/bank/util/MaskUtil.java", MASK)
        self.out = Path(tempfile.mkdtemp(prefix="mgh_eq_out_"))

    def test_candidates_categories_and_entry_points(self):
        r = subprocess.run([PY, str(DISCOVER), "--repo", str(self.repo),
                            "--out", str(self.out)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((self.out / "controls_candidates.json")
                          .read_text(encoding="utf-8"))
        cats = {c["category"] for c in data["candidates"]}
        self.assertIn("authorization", cats)   # @PreAuthorize
        self.assertIn("data-masking", cats)    # mask(...)
        # reverse wiring survived the single-pass rewrite
        mask_cand = next(c for c in data["candidates"]
                         if c["file"].endswith("MaskUtil.java"))
        self.assertIn("src/main/java/com/bank/api/TransferController.java",
                      mask_cand["entry_points"])
        cl = json.loads((self.out / "clusters.json").read_text(encoding="utf-8"))
        self.assertIsInstance(cl["clusters"], list)
        self.assertGreater(len(cl["clusters"]), 0)


class TestPerformanceNonRegression(unittest.TestCase):
    """FD3: many candidates in one file resolve enclosing without quadratic blow-up
    (the old per-candidate full-text finditer in _enclosing was O(candidates × filesize))."""

    def test_many_candidates_in_one_file_are_fast(self):
        repo = Path(tempfile.mkdtemp(prefix="mgh_perf_"))
        out = Path(tempfile.mkdtemp(prefix="mgh_perf_out_"))
        lines = ["package com.bank;", "public class Wide {"]
        for i in range(200):
            lines.append(f"  @PreAuthorize(\"hasRole('R{i}')\")")
            lines.append(f"  public void mth{i}() {{}}")
        lines.append("}")
        _write(repo, "src/Wide.java", "\n".join(lines) + "\n")
        t0 = time.perf_counter()
        r = subprocess.run([PY, str(DISCOVER), "--repo", str(repo),
                            "--out", str(out)],
                           capture_output=True, text=True, encoding="utf-8")
        elapsed = time.perf_counter() - t0
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((out / "controls_candidates.json")
                          .read_text(encoding="utf-8"))
        preauth = [c for c in data["candidates"]
                   if c["pattern"].startswith("@PreAuthorize")]
        self.assertEqual(len(preauth), 200, "all 200 @PreAuthorize candidates detected")
        # loose upper bound — guards against gross regression, not a tight benchmark
        self.assertLess(elapsed, 10.0, f"discover too slow: {elapsed:.2f}s")


class TestListClustersStandalone(unittest.TestCase):
    """list_clusters.py runs as a subprocess from a NON-script cwd (self-contained, FD2 family)."""

    def test_runs_from_non_script_cwd(self):
        repo = Path(tempfile.mkdtemp(prefix="mgh_lc_rt_"))
        cl = repo / "clusters.json"
        cl.write_text(json.dumps({"repo": str(repo), "clusters": [
            {"cluster_id": "a::A::1", "category": "authorization", "kind": "auth",
             "shape": "centralized", "evidence_files": ["a.java"],
             "usage_sites": ["a.java"], "candidate_ids": ["C-1"]},
            {"cluster_id": "b::B::2", "category": "crypto", "kind": "other",
             "shape": "centralized", "evidence_files": ["b.java"],
             "usage_sites": ["b.java"], "candidate_ids": ["C-2"]},
        ], "truncated": False}, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([PY, str(LIST), "--clusters", str(cl)],
                           cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0,
                         f"list_clusters failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 2)             # NOT 3 (wrapper key count)
        self.assertEqual(len(data["pending"]), 2)


class TestNewScriptsStandalone(unittest.TestCase):
    """FD2 family: the new enumeration / describe / validate scripts run as subprocesses
    from a NON-script cwd (self-contained, import-robust, R5.3a)."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp(prefix="mgh_new_rt_"))

    def _run(self, script, *args):
        return subprocess.run([PY, str(script), *args], cwd=str(self.cwd),
                              capture_output=True, text=True, encoding="utf-8")

    def test_list_scout_batches_help_is_contract(self):
        r = self._run(SCRIPTS / "list_scout_batches.py", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--scout-plan", r.stdout)

    def test_describe_artifact_runs_from_non_script_cwd(self):
        art = self.cwd / "a.json"
        art.write_text('{"x":[1,2,3]}', encoding="utf-8")
        r = self._run(SCRIPTS / "describe_artifact.py", "--in", str(art), "--keys")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["keys"], ["x"])

    def test_validate_inventory_help_is_contract(self):
        r = self._run(SCRIPTS / "validate_inventory.py", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--inventory", r.stdout)

    def test_list_rule_jobs_runs_from_non_script_cwd(self):
        inv = self.cwd / "inv.json"
        inv.write_text(json.dumps({"format": "opencode",
                                   "controls": [{"name": "a", "category": "crypto"}]}),
                       encoding="utf-8")
        r = self._run(SCRIPTS / "list_rule_jobs.py", "--inventory", str(inv),
                      "--format", "opencode")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["total"], 1)


if __name__ == "__main__":
    unittest.main()
