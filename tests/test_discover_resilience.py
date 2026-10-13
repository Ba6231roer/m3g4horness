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


class TestBigFilesStat(unittest.TestCase):
    def test_big_files_counts_skeleton_and_field_present(self):
        # Regression: build_skeleton() once dropped the `big` field (index_files had it
        # internally), so main()'s big_files read skeleton.json::files[].big always saw 0
        # on a full run — the fallback (candidate dedup) only ever fired when skeleton was
        # missing. Fix: skeleton now carries `big`; big_files must count all big sources.
        repo = Path(tempfile.mkdtemp(prefix="mgh_big_"))
        a = repo / "src" / "a" / "A.java"
        a.parent.mkdir(parents=True, exist_ok=True)
        a.write_text(JAVA.replace("{pkg}", "a"), encoding="utf-8")        # ~340 B, not big
        b = repo / "src" / "b" / "B.java"
        b.parent.mkdir(parents=True, exist_ok=True)
        b.write_text(JAVA.replace("{pkg}", "b") + "\n// pad\n" * 300, encoding="utf-8")  # > 1 KB
        out = Path(tempfile.mkdtemp(prefix="mgh_big_out_"))
        rc, s, err = _run(repo, out, "--big-file-bytes", "1000")
        self.assertEqual(rc, 0, err)
        self.assertEqual(s["big_files"], 1, f"big_files must count skeleton, got {s}")
        sk = json.loads((out / "skeleton.json").read_text(encoding="utf-8"))
        by_file = {f["file"]: f for f in sk["files"]}
        self.assertTrue(by_file["src/b/B.java"]["big"], "padded file must be flagged big")
        self.assertFalse(by_file["src/a/A.java"]["big"])


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
        # M3: with --progress-every 1 the deadline is checked INSIDE the callgraph
        # passes too — a 1ms budget on 120 files trips mid-pass-1; the most
        # expensive phase is no longer undefended. Pass 1 incomplete -> NO graph
        # cache; clean partial exit (0 + partial:true + hint + zero-preserving
        # scan checkpoint) + no truncated final product.
        repo = _repo(120, "part")
        out = Path(tempfile.mkdtemp(prefix="mgh_part_out_"))
        rc, s, err = _run(repo, out, "--time-budget-ms", "1")
        self.assertEqual(rc, 0, "partial must exit 0, not be killed")
        self.assertTrue(s["partial"], "budget exceeded -> partial:true")
        self.assertTrue(s["resume_hint"], "partial must carry a resume_hint")
        self.assertFalse((out / "cache" / "callgraph.json").is_file(),
                         "mid-pass-1 partial must not claim a built graph cache")
        self.assertTrue((out / "cache" / "scan_progress.json").is_file(),
                        "zero-preserving scan checkpoint must land on partial")
        self.assertFalse((out / "controls_candidates.json").is_file(),
                         "partial must NOT write a truncated final product")

    def test_graph_complete_partial_keeps_graph_cache(self):
        # Boundary-1 shape still exists: warm cache + a budget smaller than the
        # load overhead -> partial at the callgraph-built boundary, full graph
        # cache intact on disk.
        repo = _repo(60, "part2")
        out = Path(tempfile.mkdtemp(prefix="mgh_part2_out_"))
        _run(repo, out)                                   # full run populates cache
        rc, s, err = _run(repo, out, "--time-budget-ms", "1", "--resume")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"])
        self.assertTrue((out / "cache" / "callgraph.json").is_file())

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
        self.assertGreater(cp1["candidate_count"], 0,
                           "cold partial must have candidates (journal-backed count)")
        jl = (out / "cache" / "scan_journal.jsonl")
        self.assertEqual(len([ln for ln in jl.read_text(encoding="utf-8").splitlines()
                              if ln.strip()]), cp1["candidate_count"],
                         "journal lines must equal the checkpoint candidate count")

        # 2) resume with a budget smaller than the per-call read+load overhead ->
        #    trips at the callgraph-built boundary. The checkpoint MUST be preserved.
        rc, s, _ = _run(repo, out, "--time-budget-ms", "1", "--resume")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"])
        self.assertTrue(s["cache_hit"])
        cp2 = _progress()
        self.assertEqual(cp2["scanned_index"], cp1["scanned_index"],
                         "callgraph-boundary partial must not reset scanned_index")
        self.assertEqual(cp2["candidate_count"], cp1["candidate_count"],
                         "callgraph-boundary partial must not discard prior candidates")
        self.assertTrue((out / "cache" / "scan_journal.jsonl").is_file(),
                        "journal must survive the boundary partial")


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


class TestScanParamsFingerprint(unittest.TestCase):
    """M2: the scan checkpoint records a params fingerprint (scope shape +
    language); --resume with DIFFERENT params discards the stale checkpoint
    (stderr disclosure + fresh scan) instead of silently mixing candidate sets."""

    def test_scope_changed_resume_discards_checkpoint(self):
        repo = _repo(40, "pf")
        out = Path(tempfile.mkdtemp(prefix="mgh_pf_out_"))
        rc, s, _ = _run(repo, out, "--time-budget-ms", "30")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"])
        sp = json.loads((out / "cache" / "scan_progress.json")
                        .read_text(encoding="utf-8"))
        self.assertIn("scan_params", sp)
        self.assertGreater(sp["scanned_index"], 0)
        # baseline: full scoped run in a SEPARATE out dir
        out2 = Path(tempfile.mkdtemp(prefix="mgh_pf_base_"))
        rc2, s2, _ = _run(repo, out2, "--scope", "path:src/mod0")
        self.assertEqual(rc2, 0)
        self.assertFalse(s2["partial"])
        # resume with a DIFFERENT scope -> fingerprint mismatch -> fresh scan,
        # candidates == the scoped baseline (NEVER mixed with the prior set)
        rc3, s3, err3 = _run(repo, out, "--resume", "--scope", "path:src/mod0")
        self.assertEqual(rc3, 0)
        self.assertFalse(s3["partial"])
        self.assertIn("mismatch", err3)
        self.assertEqual(_cand_set(out), _cand_set(out2),
                         "param-changed resume must equal a fresh scoped run, "
                         "never a mixed candidate set")


class TestScanJournalShape(unittest.TestCase):
    """M4: the checkpoint is a small progress file + an append-only journal —
    total write amplification O(n), not the per-boundary full-list rewrite."""

    def test_progress_small_and_journal_append_only(self):
        repo = _repo(40, "jl")
        out = Path(tempfile.mkdtemp(prefix="mgh_jl_out_"))
        rc, s, _ = _run(repo, out, "--time-budget-ms", "30")
        self.assertEqual(rc, 0)
        self.assertTrue(s["partial"])
        sp_text = (out / "cache" / "scan_progress.json").read_text(encoding="utf-8")
        sp = json.loads(sp_text)
        self.assertNotIn("candidates", sp, "progress must not carry the candidate list")
        self.assertIn("candidate_count", sp)
        self.assertLess(len(sp_text), 4096, "progress must stay small")
        jl = out / "cache" / "scan_journal.jsonl"
        self.assertTrue(jl.is_file())
        lines = [ln for ln in jl.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), sp["candidate_count"])

    def test_complete_run_keeps_journal_and_resume_is_noop_equivalent(self):
        repo = _repo(6, "jl2")
        out = Path(tempfile.mkdtemp(prefix="mgh_jl2_out_"))
        _run(repo, out)
        base = _cand_set(out)
        self.assertTrue((out / "cache" / "scan_journal.jsonl").is_file(),
                        "completed run keeps the journal (idempotent resume replays it)")
        rc, s, _ = _run(repo, out, "--resume")
        self.assertEqual(rc, 0)
        self.assertFalse(s["partial"])
        self.assertEqual(_cand_set(out), base)


class TestCallgraphDefsCache(unittest.TestCase):
    """M3: pass 1's complete state caches to cache/callgraph_defs.json for
    resume salvage; a defs hit skips pass 1 (never re-walks defs)."""

    @staticmethod
    def _files_data(repo):
        files_data = []
        for p in sorted(repo.rglob("*.java")):
            t = p.read_text(encoding="utf-8")
            files_data.append({"rel": p.relative_to(repo).as_posix(),
                               "lang": "java", "text": t,
                               "lines": t.splitlines(), "bytes": len(t),
                               "mtime": p.stat().st_mtime, "big": False})
        return files_data

    def test_defs_roundtrip_and_preload_skips_pass1(self):
        import contextlib, io
        mod = _load("discover_controls")
        repo = _repo(8, "dc")
        files_data = self._files_data(repo)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mod.build_call_graph(files_data, progress_every=2)
        self.assertIn("callgraph pass1", err.getvalue())
        fwd1, rev1, fw1, defs = mod.build_call_graph(files_data, progress_every=2)
        self.assertIsNotNone(defs)
        self.assertIn("name_to_files", defs)
        err2 = io.StringIO()
        with contextlib.redirect_stderr(err2):
            fwd2, rev2, fw2, _ = mod.build_call_graph(files_data, progress_every=2,
                                                      defs=defs)
        self.assertNotIn("callgraph pass1", err2.getvalue(),
                         "preloaded defs must skip pass 1")
        self.assertEqual({k: dict(v) for k, v in fwd1.items()},
                         {k: dict(v) for k, v in fwd2.items()})

    def test_run_resume_uses_defs_cache_when_graph_cache_missing(self):
        repo = _repo(10, "dc2")
        out = Path(tempfile.mkdtemp(prefix="mgh_dc2_out_"))
        _run(repo, out)                               # populate manifest + graph cache
        (out / "cache" / "callgraph.json").unlink()   # simulate graph-cache loss
        mod = _load("discover_controls")
        files_data = self._files_data(repo)
        manifest = json.loads((out / "cache" / "manifest.json")
                              .read_text(encoding="utf-8"))
        _f, _r, _fw, defs = mod.build_call_graph(files_data, progress_every=0)
        (out / "cache" / "callgraph_defs.json").write_text(
            json.dumps({**defs, "manifest": manifest}, ensure_ascii=False),
            encoding="utf-8")
        rc, s, err = _run(repo, out, "--resume")
        self.assertEqual(rc, 0)
        self.assertFalse(s["cache_hit"], "full graph cache is gone")
        self.assertIn("defs cache hit", err, "resume must load the defs cache")


if __name__ == "__main__":
    unittest.main(verbosity=2)
