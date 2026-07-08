#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cluster formation in discover_controls.py (D8/D12 isolation units)."""
import importlib.util, sys, unittest, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _controller(pkg: str, cls: str):
    return (f"package {pkg};\npublic class {cls} {{\n"
            f"  @PreAuthorize(\"hasRole('USER')\")\n"
            f"  public void m() {{}}\n}}\n")


class TestClusters(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_cl_"))

    def _run(self, scope=None, scope_mode="defined", sample=8):
        import json
        seed, note = (self.d.resolve_seed(self.repo, scope) if scope else (None, "full-repo"))
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(self.repo, seed, 200000, 204800, None)
        out_of_scope = []
        if seed is not None and scope_mode == "defined":
            for c in cands:
                for ep in c["entry_points"]:
                    if ep not in seed and ep not in out_of_scope:
                        out_of_scope.append(ep)
        clusters = self.d.form_clusters(cands, rev, fw, seed, sample)
        return cands, clusters, out_of_scope

    def test_distributed_cluster_groups_annotation(self):
        _write(self.repo, "src/a/A.java", _controller("a", "A"))
        _write(self.repo, "src/b/B.java", _controller("b", "B"))
        cands, clusters, _ = self._run()
        dist = [c for c in clusters if c["shape"] == "distributed"
                and c["category"] == "authorization"]
        self.assertEqual(len(dist), 1, "@PreAuthorize across files → one distributed cluster")
        sites = dist[0]["usage_sites"]
        self.assertIn("src/a/A.java", sites)
        self.assertIn("src/b/B.java", sites)

    def test_sample_cap(self):
        for i in range(6):
            _write(self.repo, f"src/m/M{i}.java", _controller("m", f"M{i}"))
        _, clusters, _ = self._run(sample=3)
        dist = [c for c in clusters if c["shape"] == "distributed"]
        self.assertTrue(dist)
        self.assertLessEqual(len(dist[0]["usage_sites"]), 3, "usage sites capped at sample")

    def test_out_of_scope_cross_module_caller(self):
        # mask util (in scope) called by a controller OUTSIDE scope
        _write(self.repo, "src/util/MaskUtil.java",
               "package util;\npublic class MaskUtil {\n"
               "  public static String mask(String s){return s;}\n}\n")
        _write(self.repo, "src/api/Ctl.java",
               "package api;\nimport util.MaskUtil;\npublic class Ctl {\n"
               "  public void m(){ MaskUtil.mask(\"x\"); }\n}\n")
        seed, _ = self.d.resolve_seed(self.repo, "path:src/util")
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(self.repo, seed, 200000, 204800, None)
        out = []
        for c in cands:
            for ep in c["entry_points"]:
                if ep not in seed and ep not in out:
                    out.append(ep)
        self.assertIn("src/api/Ctl.java", out, "cross-module caller disclosed in out_of_scope")


# ---- list_clusters.py: deterministic T1 work-list (wrapper unwrap + resume) ----
import contextlib, io, json

_LC_CLUSTERS = [
    {"cluster_id": "authorization::A::ab12", "category": "authorization",
     "kind": "auth", "shape": "centralized", "evidence_files": ["a.java"],
     "usage_sites": ["a.java"], "candidate_ids": ["C-1", "C-2"]},
    {"cluster_id": "data-masking::mask::cd34", "category": "data-masking",
     "kind": "other", "shape": "distributed", "evidence_files": ["b.java"],
     "usage_sites": ["b.java"], "candidate_ids": ["C-3"]},
    {"cluster_id": "crypto::Crypt::ef56", "category": "crypto",
     "kind": "other", "shape": "centralized", "evidence_files": ["c.java"],
     "usage_sites": ["c.java"], "candidate_ids": ["C-4", "C-5", "C-6"]},
]


class TestListClusters(unittest.TestCase):
    """list_clusters.py enumerates the wrapper dict correctly (NOT len() of top level)."""

    def setUp(self):
        self.lc = _load("list_clusters")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lc_"))

    def _run(self, clusters_path, checkpoints=None):
        argv = ["list_clusters.py", "--clusters", str(clusters_path)]
        if checkpoints is not None:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _write(self, clusters, truncated=False):
        p = self.d / "clusters.json"
        p.write_text(json.dumps({"repo": str(self.d), "clusters": clusters,
                                 "truncated": truncated}, ensure_ascii=False),
                     encoding="utf-8")
        return p

    def _mark_done(self, cluster_id):
        cp = self.d / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        safe = cluster_id.replace("/", "_").replace(":", "_")
        rec = cp / f"{safe}.json"
        rec.write_text(json.dumps({"unit": cluster_id, "status": "done",
                                   "out": "x", "bytes": 1}), encoding="utf-8")
        rec.with_name(rec.name + ".done").write_text("", encoding="utf-8")

    def test_total_is_cluster_count_not_wrapper_key_count(self):
        # wrapper has 3 top-level keys; with 4 clusters total MUST be 4 (would be 3 if len()'d wrapper)
        p = self._write(_LC_CLUSTERS + [dict(_LC_CLUSTERS[0], cluster_id="x::Y::0001")])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 4)

    def test_pending_done_split_reads_record_unit(self):
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        self._mark_done("authorization::A::ab12")  # sanitized filename, unit=cluster_id
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["done"], 1)
        ids = [c["cluster_id"] for c in data["pending"]]
        self.assertNotIn("authorization::A::ab12", ids)
        self.assertEqual(len(ids), 2)
        # invariant: total == done + len(pending)
        self.assertEqual(data["total"], data["done"] + len(data["pending"]))

    def test_lite_shape_and_candidate_count(self):
        p = self._write(_LC_CLUSTERS)
        code, out, _ = self._run(p)
        by = {c["cluster_id"]: c for c in json.loads(out)["pending"]}
        self.assertEqual(by["crypto::Crypt::ef56"]["candidate_count"], 3)
        self.assertEqual(by["data-masking::mask::cd34"]["evidence_files"], ["b.java"])
        self.assertEqual(by["data-masking::mask::cd34"]["shape"], "distributed")

    def test_pending_emits_absolute_paths(self):
        # FD1: each pending cluster carries an authoritative ABSOLUTE checkpoint_path +
        # done_marker (cluster_id may contain '::' — used verbatim in the filename).
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        for item in json.loads(out)["pending"]:
            cid = item["cluster_id"]
            exp = str((cp / f"{cid}.json").resolve())
            self.assertEqual(item["checkpoint_path"], exp)
            self.assertEqual(item["done_marker"], exp + ".done")
            self.assertTrue(Path(item["checkpoint_path"]).is_absolute())
            self.assertTrue(Path(item["done_marker"]).is_absolute())

    def test_empty_clusters(self):
        p = self._write([])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["done"], 0)

    def test_truncated_passthrough(self):
        p = self._write(_LC_CLUSTERS, truncated=True)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["truncated"])

    def test_missing_checkpoints_dir_all_pending(self):
        p = self._write(_LC_CLUSTERS)
        code, out, _ = self._run(p, self.d / "nonexistent")
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)

    def test_missing_clusters_file_exit1(self):
        code, out, err = self._run(self.d / "nope.json")
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
