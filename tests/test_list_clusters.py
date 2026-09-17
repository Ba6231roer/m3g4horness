#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_clusters.py scout-tier gate (fix-mgh-init-scout-stranding).

Covers the deterministic T1 gate: when `<clusters.json 同目录>/run_config.json` enables
scout (`no_scout` false) and the scout tier is incomplete, list_clusters MUST fail-loud
exit 2 with `{"error":"scout-incomplete-gate"}` and NO `pending[]`; when scout is complete
(0 batches / full fold-in), or `--no-scout`, or run_config is absent, the gate is skipped
and the normal work-list is produced. Subprocess-driven so exit codes / stdout JSON match
the CLI contract (R5.3b). Zero runtime deps (Python >=3.10 stdlib).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "list_clusters.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(init_dir, *extra):
    argv = [sys.executable, str(SCRIPT),
            "--clusters", str(init_dir / "clusters.json"), *extra]
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout, p.stderr


def _w(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


class _Gate:
    """Minimal init-dir with run_config + clusters.json (+ optional scout state)."""

    def __init__(self, no_scout=False, run_config=True):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lc_gate_"))
        self.init = self.d / ".mgh-init"
        self.init.mkdir(parents=True, exist_ok=True)
        if run_config:
            _w(self.init / "run_config.json", {"target": str(self.d),
                                               "format": "opencode",
                                               "no_scout": bool(no_scout)})
        _w(self.init / "clusters.json", {"repo": str(self.d), "clusters": [
            {"cluster_id": "authorization::A::ab12", "category": "authorization",
             "kind": "auth", "shape": "centralized", "evidence_files": ["a.java"],
             "usage_sites": ["a.java"], "candidate_ids": ["C-1"]}],
            "truncated": False})

    def make_scout_complete(self, batches=1, merged=3):
        _w(self.init / "scout_plan.json", {"repo": str(self.d),
                                           "batches": [{"batch_id": f"b{i}"}
                                                       for i in range(batches)]})
        cp = self.init / "checkpoints" / "scout"
        cp.mkdir(parents=True, exist_ok=True)
        for i in range(batches):
            _w(cp / f"b{i}.json", {"batch_id": f"b{i}"})
            (cp / f"b{i}.json.done").write_text("", encoding="utf-8")
        (cp / "merge.json.done").write_text("", encoding="utf-8")
        _w(self.init / "scout_candidates.json", {"repo": str(self.d), "candidates": []})
        _w(self.init / "controls_candidates.json",
           {"repo": str(self.d), "candidates": [],
            "provenance": {"scout_merged": merged}})


class TestScoutGate(unittest.TestCase):
    def test_incomplete_scout_fails_loud_no_pending(self):
        # scout enabled (no_scout=false) but scout_plan absent → scout incomplete → gate
        g = _Gate()
        code, out, err = _run(g.init)
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertEqual(data["error"], "scout-incomplete-gate")
        self.assertNotIn("pending", data)
        self.assertIn("resume_state.py", err)  # recipe present

    def test_zero_batch_scout_passes_gate(self):
        # scout enabled, 0 batches → nothing to scout → complete → gate passes
        g = _Gate()
        g.make_scout_complete(batches=0)
        code, out, _ = _run(g.init)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(json.loads(out)["total"], 1)

    def test_no_scout_bypasses_gate(self):
        # no_scout=true → explicit regex-only → gate skipped even with zero scout artifacts
        g = _Gate(no_scout=True)
        code, out, _ = _run(g.init)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(json.loads(out)["total"], 1)

    def test_complete_scout_passes_gate(self):
        # scout fully done (readers .done + scout_candidates + merge.done + fold-in) → pass
        g = _Gate()
        g.make_scout_complete(batches=2)
        code, out, _ = _run(g.init)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(json.loads(out)["total"], 1)

    def test_run_config_absent_skips_gate(self):
        # bare clusters.json fixture (no run_config) → cannot judge scout intent → skip
        g = _Gate(run_config=False)
        code, out, _ = _run(g.init)
        self.assertEqual(code, 0)
        self.assertGreaterEqual(json.loads(out)["total"], 1)




# ---- deterministic small-cluster packing (--pack-bytes, improve-mgh-init-t1-cluster-packing) ----
import contextlib, hashlib, importlib.util, io
from unittest import mock


def _load_lc():
    spec = importlib.util.spec_from_file_location("list_clusters_packing", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pack_clusters(n_per_cat=4, cats=("authorization", "crypto")):
    """Same-category small clusters (multi-member packable) + matching candidates."""
    clusters = [
        {"cluster_id": f"{cat}::A::{i:04d}", "category": cat,
         "kind": "auth" if cat == "authorization" else "other",
         "shape": "centralized", "evidence_files": [f"{cat[0]}{i}.java"],
         "usage_sites": [f"{cat[0]}{i}.java"], "candidate_ids": [f"{cat}-C-{i}"]}
        for cat in cats for i in range(n_per_cat)]
    cands = [{"id": f"{cat}-C-{i}", "file": f"{cat[0]}{i}.java", "line": i + 1,
              "category": cat, "kind": "auth" if cat == "authorization" else "other",
              "snippet": "S" * 60}
             for cat in cats for i in range(n_per_cat)]
    return clusters, cands


def _safe_fn(unit_id: str) -> str:
    """Mirror of the `_safe_name` encoding (slashes and colons -> underscore)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


class TestListClustersPacking(unittest.TestCase):
    """--pack-bytes: deterministic pack partition + ids, merged inputs, member-marker
    pending derivation, oversize/terminal-failed exclusion, byte-identical off path."""

    def setUp(self):
        self.lc = _load_lc()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_pack_"))
        self.inputs = self.d / "inputs" / "t1"
        self.cp = self.d / "checkpoints" / "t1"

    def _write(self, clusters, cands):
        p = self.d / "clusters.json"
        p.write_text(json.dumps({"repo": str(self.d), "clusters": clusters,
                                 "truncated": False}, ensure_ascii=False), encoding="utf-8")
        (self.d / "controls_candidates.json").write_text(
            json.dumps({"candidates": cands}, ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, clusters_path, *extra):
        argv = ["list_clusters.py", "--clusters", str(clusters_path),
                "--checkpoints", str(self.cp),
                "--candidates", str(self.d / "controls_candidates.json"),
                "--materialize", str(self.inputs)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _run_sub(self, clusters_path, *extra, cwd=None):
        argv = [sys.executable, str(SCRIPT),
                "--clusters", str(clusters_path),
                "--checkpoints", str(self.cp),
                "--candidates", str(self.d / "controls_candidates.json"),
                "--materialize", str(self.inputs)] + list(extra)
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                           cwd=str(cwd) if cwd else None)
        return p.returncode, p.stdout, p.stderr

    # -- determinism: partition + ids are pure functions of clusters.json + flags --

    def test_packing_deterministic_byte_identical_reruns_and_any_cwd(self):
        clusters, cands = _pack_clusters()
        p = self._write(clusters, cands)
        _, out1, _ = self._run(p, "--pack-bytes", "5000", "--pack-max", "3")
        _, out2, _ = self._run(p, "--pack-bytes", "5000", "--pack-max", "3")
        self.assertEqual(out1, out2)  # same input twice -> byte-identical stdout
        _, out3, _ = self._run_sub(p, "--pack-bytes", "5000", "--pack-max", "3",
                                   cwd=tempfile.gettempdir())
        ids1 = sorted(it["cluster_id"] for it in json.loads(out1)["pending"])
        ids3 = sorted(it["cluster_id"] for it in json.loads(out3)["pending"])
        self.assertEqual(ids1, ids3)  # any cwd -> same pack id set
        self.assertTrue(ids1 and all(i.startswith("pack::") for i in ids1))

    def test_pack_id_shape_sha8_of_sorted_member_ids(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        pid = pack["cluster_id"]
        self.assertTrue(pid.startswith("pack::crypto::"))
        tail = pid.rsplit("::", 1)[1]
        self.assertEqual(len(tail), 8)
        self.assertLessEqual(len(pid), 160)
        expected = hashlib.sha1("\n".join(sorted(c["cluster_id"] for c in clusters))
                                .encode("utf-8")).hexdigest()[:8]
        self.assertEqual(tail, expected)

    def test_greedy_seals_on_pack_max_and_byte_cap(self):
        clusters, cands = _pack_clusters(n_per_cat=4, cats=("crypto",))
        p = self._write(clusters, cands)
        # pack-max seals at 3 members despite byte room
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--pack-max", "3")
        sizes = sorted(len(it["members"]) for it in json.loads(out)["pending"])
        self.assertEqual(sizes, [1, 3])
        # byte cap below a single cluster -> each cluster its own pack (never split)
        _, out, _ = self._run(p, "--pack-bytes", "100", "--pack-max", "8")
        packs = json.loads(out)["pending"]
        self.assertEqual(len(packs), 4)
        self.assertTrue(all(len(it["members"]) == 1 for it in packs))

    def test_never_mixes_categories(self):
        clusters, cands = _pack_clusters(n_per_cat=3)
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--pack-max", "8")
        for it in json.loads(out)["pending"]:
            cats = {m["cluster_id"].split("::", 1)[0] for m in it["members"]}
            self.assertEqual(len(cats), 1, f"pack {it['cluster_id']} mixed {cats}")
            self.assertEqual(it["category"], cats.pop())

    # -- merged input materialization --

    def test_merged_input_shape_and_paths(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        self.assertEqual(pack["shape"], "packed")
        self.assertEqual(pack["oversize"], False)
        ip = Path(pack["input_path"])
        self.assertTrue(ip.is_file())
        self.assertEqual(pack["bytes"], ip.stat().st_size)
        self.assertNotIn(":", ip.name)  # '::' sanitized out of the filename (NTFS ADS)
        self.assertIn(_safe_fn(pack["cluster_id"]), ip.name)
        merged = json.loads(ip.read_text(encoding="utf-8"))
        self.assertEqual(merged["repo"], str(self.d.resolve()))
        self.assertEqual(merged["pack_id"], pack["cluster_id"])
        self.assertEqual(len(merged["members"]), 2)
        self.assertEqual(len(merged["checkpoints"]), 2)
        by = {c["cluster_id"]: c for c in merged["checkpoints"]}
        for m in pack["members"]:
            self.assertEqual(m["input_path"], str(ip))
            self.assertTrue(Path(m["checkpoint_path"]).is_absolute())
            self.assertTrue(Path(m["done_marker"]).is_absolute())
            self.assertEqual(by[m["cluster_id"]]["checkpoint_path"], m["checkpoint_path"])
            self.assertEqual(by[m["cluster_id"]]["done_marker"], m["done_marker"])
        for rec in merged["members"]:  # sunk payload present; repo sinks once (top level)
            self.assertIn("candidates", rec)
            self.assertNotIn("repo", rec)

    # -- pack pending derives from member markers (cluster level = truth source) --

    def test_partial_done_pack_stays_pending_member_listed(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        m0 = pack["members"][0]
        Path(m0["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(m0["done_marker"]).write_text("", encoding="utf-8")
        _, out2, _ = self._run(p, "--pack-bytes", "100000")
        data = json.loads(out2)
        self.assertEqual(data["total"], 1)                    # pack still ONE unit
        self.assertEqual(data["done"], 0)                     # pack NOT done
        (pack2,) = data["pending"]
        self.assertEqual(pack2["cluster_id"], pack["cluster_id"])  # same pack id
        self.assertEqual(len(pack2["members"]), 2)            # done member still listed
        self.assertEqual(data["cluster_done"], 1)             # cluster-level disclosure

    def test_all_done_pack_disappears_cluster_done_counts(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        for m in pack["members"]:
            Path(m["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
            Path(m["done_marker"]).write_text("", encoding="utf-8")
        _, out2, _ = self._run(p, "--pack-bytes", "100000")
        data = json.loads(out2)
        self.assertEqual(data["pending"], [])                 # pack gone from pending
        self.assertEqual(data["done"], 1)                     # pack counted done
        self.assertEqual(data["cluster_done"], 2)
        self.assertEqual(data["cluster_total"], 2)

    # -- exclusions: oversize/shard units, terminal-failed clusters, failed packs --

    def test_oversize_cluster_shards_independently_never_packed(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        big = {"cluster_id": "crypto::BIG::zz", "category": "crypto", "kind": "other",
               "shape": "centralized", "evidence_files": ["x.java"],
               "usage_sites": ["x.java"],
               "candidate_ids": [f"big-C-{i}" for i in range(6)]}
        big_cands = [{"id": f"big-C-{i}", "file": f"x{i}.java", "line": i,
                      "category": "crypto", "kind": "other", "snippet": "B" * 3000}
                     for i in range(6)]
        p = self._write(clusters + [big], cands + big_cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--max-unit-bytes", "4000")
        data = json.loads(out)
        for it in data["pending"]:
            if it["cluster_id"].startswith("pack::"):
                for m in it["members"]:
                    self.assertNotEqual(m["cluster_id"], "crypto::BIG::zz")
            else:
                self.assertTrue(it["cluster_id"].startswith("crypto::BIG::zz::shard-"))
                self.assertTrue(it["oversize"])
        self.assertEqual(data["total"], 2)  # 1 pack + 1 oversize cluster (sharded)

    def test_failed_cluster_excluded_from_packs_and_counted(self):
        clusters, cands = _pack_clusters(n_per_cat=3, cats=("crypto",))
        p = self._write(clusters, cands)
        self.cp.mkdir(parents=True, exist_ok=True)
        bad = clusters[0]["cluster_id"]
        (self.cp / f"{_safe_fn(bad)}.json.failed").write_text(
            json.dumps({"unit": bad, "reason": "r", "tier": "t1"}), encoding="utf-8")
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--pack-max", "8")
        data = json.loads(out)
        self.assertEqual(data["failed"], 1)
        packed = [m["cluster_id"] for it in data["pending"]
                  for m in it["members"]]
        self.assertEqual(sorted(packed), sorted(c["cluster_id"] for c in clusters[1:]))

    def test_pack_level_failed_marker_is_terminal(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        Path(pack["failed_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(pack["failed_marker"]).write_text(
            json.dumps({"unit": pack["cluster_id"], "reason": "member boom",
                        "tier": "t1"}), encoding="utf-8")
        _, out2, _ = self._run(p, "--pack-bytes", "100000")
        data = json.loads(out2)
        self.assertEqual(data["pending"], [])                 # pack terminal
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["done"], 0)                     # NOT done

    def test_include_failed_relists_failed_pack_canonical(self):
        # --include-failed: the failed pack re-emits as the pack unit (canonical
        # pack id + the same pack-level failed_marker path); failed stays counted
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000")
        (pack,) = json.loads(out)["pending"]
        Path(pack["failed_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(pack["failed_marker"]).write_text(
            json.dumps({"unit": pack["cluster_id"], "reason": "member boom",
                        "tier": "t1"}), encoding="utf-8")
        _, out2, _ = self._run(p, "--pack-bytes", "100000", "--include-failed")
        data = json.loads(out2)
        self.assertEqual([it["cluster_id"] for it in data["pending"]],
                         [pack["cluster_id"]])
        self.assertEqual(data["pending"][0]["failed_marker"], pack["failed_marker"])
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["done"], 0)

    def test_include_failed_overlong_id_keeps_canonical_identity(self):
        # a failed cluster whose sanitized FILENAME stem is truncated still
        # re-enters pending[] under its FULL canonical id — identity comes
        # from the forward derivation, never a stem reverse lookup
        long_id = "crypto::LONG::" + "x" * 200
        clusters = [{"cluster_id": long_id, "category": "crypto", "kind": "other",
                     "shape": "centralized", "evidence_files": ["l.java"],
                     "usage_sites": ["l.java"], "candidate_ids": ["crypto-C-9"]}]
        cands = [{"id": "crypto-C-9", "file": "l.java", "line": 1, "category": "crypto",
                  "kind": "other", "snippet": "S" * 60}]
        p = self._write(clusters, cands)
        _, out, _ = self._run(p)                               # unpacked path
        (item,) = json.loads(out)["pending"]
        self.assertEqual(item["cluster_id"], long_id)
        self.assertLess(len(Path(item["failed_marker"]).stem), len(long_id))
        Path(item["failed_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(item["failed_marker"]).write_text(
            json.dumps({"unit": long_id, "reason": "r", "tier": "t1"}), encoding="utf-8")
        _, out2, _ = self._run(p, "--include-failed")
        data = json.loads(out2)
        (relisted,) = data["pending"]
        self.assertEqual(relisted["cluster_id"], long_id)      # full canonical id
        self.assertEqual(relisted["failed_marker"], item["failed_marker"])
        self.assertEqual(data["failed"], 1)

    # -- pack materialize-failure isolation (batch continues, exit code unchanged) --

    def test_pack_materialize_failure_excludes_pack_exit0(self):
        clusters, cands = _pack_clusters(n_per_cat=2, cats=("crypto",))
        p = self._write(clusters, cands)

        def _boom(inputs_dir, pack_id, merged):
            raise OSError("boom: merged input write failed")

        with mock.patch.object(self.lc, "_write_pack_input", side_effect=_boom):
            code, out, err = self._run(p, "--pack-bytes", "100000")
        self.assertEqual(code, 0)                             # batch continues
        data = json.loads(out)
        self.assertEqual(data["pending"], [])                 # pack excluded from pending
        self.assertIn("materialize failed", err)              # stderr warning names the pack
        self.assertIn("pack::", err)
        self.assertEqual(data["done"], 0)
        self.assertEqual(data["failed"], 0)                   # NOT a cluster failure

    # -- stdout disclosure / off-path byte identity --

    def test_packing_mode_discloses_cluster_counts(self):
        clusters, cands = _pack_clusters(n_per_cat=2)
        p = self._write(clusters, cands)
        code, out, err = self._run(p, "--pack-bytes", "100000")
        data = json.loads(out)
        self.assertEqual(data["cluster_total"], 4)
        self.assertEqual(data["cluster_done"], 0)
        self.assertEqual(code, 0)
        self.assertIn("packing:", err)                        # stderr pack/cluster/avg report

    def test_pack_bytes_zero_is_byte_identical_off_path(self):
        clusters, cands = _pack_clusters(n_per_cat=2)
        p = self._write(clusters, cands)
        _, off_default, _ = self._run(p)
        _, off_zero, _ = self._run(p, "--pack-bytes", "0")
        self.assertEqual(off_default, off_zero)               # explicit 0 == omitted
        data = json.loads(off_zero)
        for forbidden in ("cluster_total", "cluster_done"):
            self.assertNotIn(forbidden, data)
        for it in data["pending"]:
            self.assertNotIn("members", it)
            self.assertNotEqual(it.get("shape"), "packed")

    # -- invalid flag combinations (closed-set rejection, exit 2) --

    def test_pack_max_without_pack_bytes_exit2(self):
        clusters, cands = _pack_clusters(n_per_cat=1)
        p = self._write(clusters, cands)
        code, _, err = self._run(p, "--pack-max", "4")
        self.assertEqual(code, 2)
        self.assertIn("invalid combination", err)

    def test_pack_bytes_requires_materialize_exit2(self):
        clusters, cands = _pack_clusters(n_per_cat=1)
        p = self._write(clusters, cands)
        argv = ["list_clusters.py", "--clusters", str(p),
                "--checkpoints", str(self.cp), "--pack-bytes", "1000"]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 2)
        self.assertIn("--materialize", err.getvalue())

    def test_pack_bytes_negative_exit2(self):
        clusters, cands = _pack_clusters(n_per_cat=1)
        p = self._write(clusters, cands)
        code, _, _ = self._run(p, "--pack-bytes", "-1")
        self.assertEqual(code, 2)

    def test_pack_max_zero_exit2(self):
        clusters, cands = _pack_clusters(n_per_cat=1)
        p = self._write(clusters, cands)
        code, _, err = self._run(p, "--pack-bytes", "1000", "--pack-max", "0")
        self.assertEqual(code, 2)
        self.assertIn("--pack-max must be >= 1", err)

    # -- paging over the packed list --

    def test_paging_and_budget_shrink_over_packs(self):
        clusters, cands = _pack_clusters(n_per_cat=2)
        p = self._write(clusters, cands)
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--offset", "1", "--limit", "1")
        data = json.loads(out)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["pending"]), 1)
        self.assertEqual(data["effective_limit"], 1)
        _, out, _ = self._run(p, "--pack-bytes", "100000", "--orch-budget-bytes", "200")
        data = json.loads(out)
        self.assertTrue(data["shrunk"])  # pack items carry members[] -> heavy items
        self.assertEqual(data["effective_limit"], 1)

if __name__ == "__main__":
    unittest.main(verbosity=2)
