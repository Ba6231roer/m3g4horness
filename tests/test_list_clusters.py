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


if __name__ == "__main__":
    unittest.main(verbosity=2)
