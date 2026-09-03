#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""End-to-end self-heal verification for a stuck /mgh-init T1 run
(fix-mgh-init-done-marker-identity, task 7.1).

Reproduces the user's stranded-run disk shape as a fixture: 476 short-id
clusters done + 5 failed + 32 overlong-id clusters each carrying a
truncated-stem `<encoded>.json` record + `<encoded>.json.done` marker whose
body lacks the `unit` field (the pre-fix producer never wrote one). Under the
old glob+stem judgment the 32 were pending forever (done=476, failed=5,
pending=32 frozen); under the forward judgment they are terminal.

Chain verified (zero manual disk operations):
  resume_state.py  -> step=t2 (tier complete: done=508=476+32 overlong, failed=5, total=513)
  list_clusters.py -> pending=0, done=508, failed=5
  --check          -> ok

Subprocess-driven so the CLI contract (exit codes / stdout JSON) is exercised
verbatim. Zero runtime deps (Python >=3.10 stdlib).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run(script: Path, *argv):
    p = subprocess.run([sys.executable, str(SCRIPTS / script), *argv],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout, p.stderr


def _sha12(key: str) -> str:
    import hashlib
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _overlong_cid(i: int) -> str:
    """A 267-char legacy cluster_id (anchor-less centralized candidate shape)."""
    file = "src/" + "deep/" * 27 + f"Overlong{i}SecurityUtil.java"
    key = f"authorization::{file}::{file}"
    return f"{key}::{_sha12(key)}"


class TestStuckRunSelfHeal(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_stuck_"))
        self.init = self.target / ".mgh-init"
        self.cp = self.init / "checkpoints" / "t1"
        self.cp.mkdir(parents=True, exist_ok=True)
        # run_config: no_scout run stuck in T1
        self._w(self.init / "run_config.json",
                {"target": str(self.target), "format": "opencode", "no_scout": True})
        (self.init / ".active").write_text(json.dumps(
            {"domain": "mgh-init", "target": str(self.target), "out_roots": [],
             "v": 1}), encoding="utf-8")

        # clusters.json: 476 short + 5 short (to fail) + 32 overlong ids
        clusters = []
        for i in range(476):
            clusters.append({"cluster_id": f"authorization::C{i}::{i:012d}",
                             "category": "authorization", "kind": "auth"})
        for i in range(5):
            clusters.append({"cluster_id": f"crypto::F{i}::{i:012d}",
                             "category": "crypto", "kind": "other"})
        for i in range(32):
            clusters.append({"cluster_id": _overlong_cid(i),
                             "category": "authorization", "kind": "auth"})
        self._w(self.init / "controls_candidates.json",
                {"repo": str(self.target), "candidates": [], "truncated": False,
                 "unresolved": []})
        self._w(self.init / "clusters.json",
                {"repo": str(self.target), "clusters": clusters, "truncated": False})

        # disk shape as the pre-fix run left it: encoded marker paths, NO `unit`
        # in any record body (the old producer never wrote the field).
        sys_path = sys.path[:]
        sys.path.insert(0, str(SCRIPTS))
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "it_heal", SCRIPTS / "init_tier.py")
            it = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(it)
        finally:
            sys.path = sys_path
        for c in clusters[:476]:
            enc = it.safe_unit_filename(c["cluster_id"])
            (self.cp / f"{enc}.json").write_text(
                json.dumps({"cluster_id": c["cluster_id"], "status": "done"}),
                encoding="utf-8")
            (self.cp / f"{enc}.json.done").write_text("", encoding="utf-8")
        for c in clusters[476:481]:
            enc = it.safe_unit_filename(c["cluster_id"])
            (self.cp / f"{enc}.json.failed").write_text(
                json.dumps({"reason": "evidence parse error", "tier": "t1"}),
                encoding="utf-8")
        for c in clusters[481:]:
            enc = it.safe_unit_filename(c["cluster_id"])
            self.assertTrue(len(enc) <= 200 and enc != c["cluster_id"])  # truncated
            (self.cp / f"{enc}.json").write_text(
                json.dumps({"cluster_id": c["cluster_id"], "status": "done"}),
                encoding="utf-8")
            (self.cp / f"{enc}.json.done").write_text("", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.target, ignore_errors=True)

    def _w(self, path: Path, obj):
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

    def test_stuck_run_self_heals_end_to_end(self):
        # 1. resume_state: the 32 overlong units are terminal under the forward
        #    judgment -> t1 completes on the FIRST call (done=508=476+32,
        #    failed=5, total=513) and the step advances past t1 to t2.
        code, out, err = _run("resume_state.py", "--init-dir", str(self.init))
        self.assertEqual(code, 0, err)
        st = json.loads(out)
        self.assertEqual(st["step"], "t2")
        self.assertEqual(st["tiers"]["t1"]["total"], 513)
        self.assertEqual(st["tiers"]["t1"]["done"], 508)   # 476 short + 32 overlong
        self.assertEqual(st["tiers"]["t1"]["failed"], 5)

        # 2. list_clusters --materialize: pending=0 (the 32 are terminal), no
        #    "could not read unit" warn (old path deleted)
        code, out, err = _run(
            "list_clusters.py", "--clusters", str(self.init / "clusters.json"),
            "--checkpoints", str(self.cp),
            "--candidates", str(self.init / "controls_candidates.json"),
            "--materialize", str(self.init / "inputs" / "t1"))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["total"], 513)
        self.assertEqual(data["done"], 508)
        self.assertEqual(data["failed"], 5)
        self.assertEqual(data["pending"], [])
        self.assertNotIn("could not read unit from", err)
        self.assertNotIn("orphan marker", err)             # all markers are canonical

        # 3. resume_state again: step stable at t2 with a subagent next_action
        code, out, _ = _run("resume_state.py", "--init-dir", str(self.init))
        st = json.loads(out)
        self.assertEqual(st["step"], "t2")
        self.assertEqual(st["next_action"]["kind"], "subagent")  # init-synthesis

        # 4. --check: self-consistent (no violations; sentinel present)
        code, out, _ = _run("resume_state.py", "--init-dir", str(self.init), "--check")
        self.assertEqual(code, 0, out)
        self.assertTrue(json.loads(out)["ok"])

    def test_old_genum_would_have_stranded(self):
        # control: prove the fixture IS the stuck shape — the truncated-stem
        # filenames differ from plain-sanitized ids (the old stem-fallback's
        # blind spot) and the record bodies lack `unit` (the old primary read).
        cid = _overlong_cid(0)
        enc = cid.replace(":", "_").replace("/", "_")
        self.assertFalse((self.cp / f"{enc}.json.done").exists())   # plain-sanitized misses
        rec = json.loads((self.cp / f"{enc[:140]}~{enc[-59:]}.json").read_text(encoding="utf-8"))
        self.assertNotIn("unit", rec)


if __name__ == "__main__":
    unittest.main(verbosity=2)
