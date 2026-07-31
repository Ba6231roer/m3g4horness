#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Resilience tests for discover_controls.py: callgraph cache, scan resume,
soft time-budget partial exit, atomic writes (stdlib unittest + subprocess).

Exercises the real CLI path (subprocess) so flags, stdout contract, exit codes,
and on-disk cache/ + scan_progress.json are verified end-to-end. Zero runtime deps.
Run: py -m unittest tests.test_discover_resilience
"""
import importlib.util, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
DISCOVER = SCRIPTS / "discover_controls.py"
PY = sys.executable

JAVA = """\
package pkg{pkg};
import javax.crypto.Cipher;
import com.bank.util.MaskUtil;
public class Ctrl{pkg} {
  @PreAuthorize("hasRole('USER')")
  public String t(@Valid String card) { return MaskUtil.mask(card); }
  public byte[] enc(byte[] k) throws Exception { Cipher c = Cipher.getInstance("AES"); return c.doFinal(k); }
}
"""


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _repo(n=6, prefix="resil"):
    """Build a temp repo of n Java files (each yields authorization + input-validation
    + data-masking + crypto candidates). n large enough (>=~80) makes a 1ms budget trip
    deterministically at the callgraph-built boundary."""
    repo = Path(tempfile.mkdtemp(prefix=f"mgh_{prefix}_"))
    for i in range(n):
        p = repo / f"src/mod{i}/C.java"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(JAVA.replace("{pkg}", str(i)), encoding="utf-8")
    return repo


def _run(repo, out, *flags, cwd=None):
    """Run discover via subprocess; return (rc, stdout_json|None, stderr)."""
    r = subprocess.run(
        [PY, str(DISCOVER), "--repo", str(repo), "--out", str(out),
         "--progress-every", "1", *flags],
        capture_output=True, cwd=str(cwd) if cwd else None)
    out_txt = r.stdout.decode("utf-8", "replace")
    summary = None
    try:
        summary = json.loads(out_txt)
    except ValueError:
        pass
    return r.returncode, summary, r.stderr.decode("utf-8", "replace")


def _cand_set(out):
    d = json.loads((Path(out) / "controls_candidates.json").read_text(encoding="utf-8"))
    return sorted((c["file"], c["line"], c["category"], c["pattern"]) for c in d["candidates"])


class TestDiscoverContract(unittest.TestCase):
    def test_help_exposes_resilience_flags(self):
        # --help IS the contract surface (flags the agent learns from); the stdout
        # fields partial/resume_hint/cache_hit are documented in core/contracts/init/
        # discover-cache.md and asserted by the run tests below.
        r = subprocess.run([PY, str(DISCOVER), "--help"], capture_output=True)
        txt = r.stdout.decode("utf-8", "replace")
        for flag in ("--time-budget-ms", "--rebuild-cache", "--resume"):
            self.assertIn(flag, txt, f"--help missing {flag}")

    def test_runs_from_non_script_cwd(self):
        # import-robustness: runs from a cwd that is NOT the scripts dir (R5.3a)
        repo = _repo(3, "cwd")
        out = Path(tempfile.mkdtemp(prefix="mgh_cwd_out_"))
        with tempfile.TemporaryDirectory() as other:
            rc, summ, _ = _run(repo, out, cwd=Path(other))
        self.assertEqual(rc, 0)
        self.assertFalse(summ["partial"])


class TestCallgraphCache(unittest.TestCase):
    def test_cache_hit_second_run_and_equivalence(self):
        repo = _repo(5, "cache")
        out = Path(tempfile.mkdtemp(prefix="mgh_cache_out_"))
        rc1, s1, _ = _run(repo, out)
        self.assertEqual(rc1, 0)
        self.assertFalse(s1["cache_hit"], "cold run must not hit cache")
        rc2, s2, _ = _run(repo, out)
        self.assertEqual(rc2, 0)
        self.assertTrue(s2["cache_hit"], "warm run must hit cache")
        self.assertEqual(_cand_set(out), _cand_set(out))  # stable

    def test_warm_run_skips_rebuild(self):
        # perf proxy (deterministic): a cache hit emits NO "callgraph pass1" progress
        repo = _repo(5, "perf")
        out = Path(tempfile.mkdtemp(prefix="mgh_perf_out_"))
        _run(repo, out)                       # cold: rebuilds
        rc, s, err = _run(repo, out)          # warm: cache hit
        self.assertEqual(rc, 0)
        self.assertTrue(s["cache_hit"])
        self.assertNotIn("callgraph pass1", err,
                         "cache hit must skip the two regex passes")

    def test_cache_invalidated_on_source_change(self):
        repo = _repo(4, "inv")
        out = Path(tempfile.mkdtemp(prefix="mgh_inv_out_"))
        _run(repo, out)                       # populate cache
        # change content (size differs) -> manifest mismatch -> rebuild
        p = next(repo.rglob("C.java"))
        p.write_text(p.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
        rc, s, err = _run(repo, out)
        self.assertEqual(rc, 0)
        self.assertFalse(s["cache_hit"], "changed source must invalidate cache")
        self.assertIn("callgraph pass1", err, "stale cache must rebuild")

    def test_rebuild_cache_forces_rebuild(self):
        repo = _repo(4, "reb")
        out = Path(tempfile.mkdtemp(prefix="mgh_reb_out_"))
        _run(repo, out)                       # warm cache
        rc, s, err = _run(repo, out, "--rebuild-cache")
        self.assertEqual(rc, 0)
        self.assertFalse(s["cache_hit"], "--rebuild-cache must force a rebuild")
        self.assertIn("callgraph pass1", err)


class TestSoftBudget(unittest.TestCase):
    def test_partial_exit_clean(self):
        # 120 files -> callgraph build is well over a 1ms budget, so the partial trips
        # deterministically at the callgraph-built safe boundary.
        repo = _repo(120, "part")
        out = Path(tempfile.mkdtemp(prefix="mgh_part_out_"))
        rc, s, err = _run(repo, out, "--time-budget-ms", "1")
        self.assertEqual(rc, 0, "partial must exit 0, not be killed")
        self.assertTrue(s["partial"], "budget exceeded -> partial:true")
        self.assertTrue(s["resume_hint"], "partial must carry a resume_hint")
        self.assertTrue((out / "cache" / "callgraph.json").is_file(),
                        "callgraph cache must land on partial")
        self.assertTrue((out / "cache" / "scan_progress.json").is_file(),
                        "scan checkpoint must land on partial")
        self.assertFalse((out / "controls_candidates.json").is_file(),
                         "partial must NOT write a truncated final product")

    def test_finishes_in_one_go_when_budget_off(self):
        repo = _repo(5, "off")
        out = Path(tempfile.mkdtemp(prefix="mgh_off_out_"))
        rc, s, _ = _run(repo, out)            # default budget 0 = off
        self.assertEqual(rc, 0)
        self.assertFalse(s["partial"])
        self.assertEqual(s["resume_hint"], "")


class TestScanResume(unittest.TestCase):
    def _baseline_and_sorted_files(self, repo, out):
        _run(repo, out)                       # full cold run
        base = _cand_set(out)
        sk = json.loads((out / "skeleton.json").read_text(encoding="utf-8"))
        files_sorted = [f["file"] for f in sk["files"]]
        return base, files_sorted

    def test_resume_from_midpoint_equivalent(self):
        repo = _repo(6, "res")
        out = Path(tempfile.mkdtemp(prefix="mgh_res_out_"))
        base, files_sorted = self._baseline_and_sorted_files(repo, out)
        self.assertGreaterEqual(len(files_sorted), 2)
        # construct a partial checkpoint at the midpoint with the real prior candidates
        k = len(files_sorted) // 2
        first_k = set(files_sorted[:k])
        prior = [c for c in json.loads(
            (out / "controls_candidates.json").read_text(encoding="utf-8"))["candidates"]
            if c["file"] in first_k]
        manifest = json.loads((out / "cache" / "manifest.json").read_text(encoding="utf-8"))
        (out / "cache" / "scan_progress.json").write_text(json.dumps(
            {"scanned_index": k, "candidates": prior, "manifest": manifest},
            ensure_ascii=False), encoding="utf-8")
        # drop final products; keep cache -> resume must reconstruct the full set
        for p in ("controls_candidates.json", "clusters.json", "skeleton.json"):
            (out / p).unlink(missing_ok=True)
        rc, s, _ = _run(repo, out, "--resume")
        self.assertEqual(rc, 0)
        self.assertFalse(s["partial"])
        self.assertEqual(_cand_set(out), base,
                         "resume from midpoint must equal a full run's candidate set")

    def test_resume_idempotent(self):
        repo = _repo(5, "idem")
        out = Path(tempfile.mkdtemp(prefix="mgh_idem_out_"))
        _run(repo, out)
        rc, _, _ = _run(repo, out, "--resume")
        self.assertEqual(rc, 0)
        first = _cand_set(out)
        rc, _, _ = _run(repo, out, "--resume")
        self.assertEqual(rc, 0)
        self.assertEqual(_cand_set(out), first, "re-resume must be idempotent")

    def test_resume_preserves_checkpoint_when_budget_trips_at_callgraph(self):
        # Regression: a --resume call whose fixed overhead (re-reading files + loading
        # the cache) already exceeds the budget MUST NOT clobber the existing scan
        # checkpoint to (0, []) — otherwise progress is lost and convergence stalls.
        # Dense repo (shared mask/Cipher names) -> a non-trivial cache load that
        # reliably exceeds a 1ms budget at the callgraph-built boundary.
        repo = _repo(40, "pres")
        out = Path(tempfile.mkdtemp(prefix="mgh_pres_out_"))

        def _progress():
            return json.loads(
                (out / "cache" / "scan_progress.json").read_text(encoding="utf-8"))

        # 1) cold partial during SCAN (budget large enough to pass callgraph+read,
        #    small enough to trip mid-scan) -> a real checkpoint with candidates
        rc, s, _ = _run(repo, out, "--time-budget-ms", "30")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"], "cold run must partial within 30ms on 40 dense files")
        cp1 = _progress()
        self.assertGreater(cp1["scanned_index"], 0, "cold partial must have scanned some files")
        self.assertGreater(len(cp1["candidates"]), 0, "cold partial must have candidates")

        # 2) resume with a budget smaller than the per-call read+load overhead ->
        #    trips at the callgraph-built boundary. The checkpoint MUST be preserved.
        rc, s, _ = _run(repo, out, "--time-budget-ms", "1", "--resume")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"])
        self.assertTrue(s["cache_hit"])
        cp2 = _progress()
        self.assertEqual(cp2["scanned_index"], cp1["scanned_index"],
                         "callgraph-boundary partial must not reset scanned_index")
        self.assertEqual(len(cp2["candidates"]), len(cp1["candidates"]),
                         "callgraph-boundary partial must not discard prior candidates")


class TestAtomicWrite(unittest.TestCase):
    def test_no_tmp_leftover_after_run(self):
        repo = _repo(4, "atom")
        out = Path(tempfile.mkdtemp(prefix="mgh_atom_out_"))
        _run(repo, out)
        leftovers = list(out.rglob("*.tmp"))
        self.assertEqual(leftovers, [], f"atomic write left .tmp: {leftovers}")

    def test_atomic_helper_valid_json_no_tmp(self):
        d = _load("discover_controls")
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "x" / "f.json"
            d._atomic_write_json(target, {"a": 1, "b": [2, 3]})
            self.assertFalse((Path(td) / "x" / "f.json.tmp").is_file(),
                             "no .tmp must remain after a successful atomic write")
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")),
                             {"a": 1, "b": [2, 3]})

    def test_check_passes_after_run(self):
        repo = _repo(3, "chk")
        out = Path(tempfile.mkdtemp(prefix="mgh_chk_out_"))
        _run(repo, out)
        r = subprocess.run([PY, str(DISCOVER), "--check", str(out)],
                           capture_output=True)
        self.assertEqual(r.returncode, 0, "--check must pass on atomic complete products")
        d = json.loads(r.stdout.decode("utf-8", "replace"))
        self.assertTrue(d["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
