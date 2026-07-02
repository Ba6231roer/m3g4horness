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


if __name__ == "__main__":
    unittest.main()
