#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Runtime robustness tests for the new /mgh-sast leaf scripts (FD2 family).

Exercises list_chunks.py / list_verify_jobs.py as REAL SUBPROCESSES from a NON-script
cwd — proving the self-locate sys.path guard + zero-dep import work without the test
harness masking them — and that `--help` is the CLI contract surface. Complements the
in-process tests in test_list_chunks.py / test_list_verify_jobs.py.
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
LIST_CHUNKS = SCRIPTS / "list_chunks.py"
LIST_VERIFY = SCRIPTS / "list_verify_jobs.py"
PY = sys.executable


class TestSastEnumerationStandalone(unittest.TestCase):
    """New sast enumeration scripts run as subprocesses from a NON-script cwd."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp(prefix="mgh_sast_rt_"))

    def _run(self, script, *args):
        return subprocess.run([PY, str(script), *args], cwd=str(self.cwd),
                              capture_output=True, text=True, encoding="utf-8")

    def test_list_chunks_runs_from_non_script_cwd(self):
        s3 = self.cwd / "s3_chunks.json"
        s3.write_text(json.dumps({"rationale": "r", "chunks": [
            {"id": "chunk-01", "files": ["a.c"], "threat_id": "T1", "hypothesis": "h"},
            {"id": "chunk-02", "files": ["b.c"], "threat_id": "T2", "hypothesis": "h"},
        ]}, ensure_ascii=False), encoding="utf-8")
        r = self._run(LIST_CHUNKS, "--chunks", str(s3))
        self.assertEqual(r.returncode, 0,
                         f"list_chunks failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["pending"]), 2)

    def test_list_chunks_help_is_contract(self):
        r = self._run(LIST_CHUNKS, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--chunks", r.stdout)
        self.assertIn("--checkpoints", r.stdout)

    def test_list_verify_jobs_runs_from_non_script_cwd(self):
        s5 = self.cwd / "s5_filtered.json"
        s5.write_text(json.dumps({"kept": [
            {"id": "F-1", "file": "a.java", "line_start": 10, "vuln_class": "injection",
             "source_ref": "a.java:10", "sink_ref": "b.java:1"},
        ], "dropped": [], "stats": {}}, ensure_ascii=False), encoding="utf-8")
        r = self._run(LIST_VERIFY, "--findings", str(s5))
        self.assertEqual(r.returncode, 0,
                         f"list_verify_jobs failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        data = json.loads(r.stdout)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["pending"][0]["finding_id"], "F-1")

    def test_list_verify_jobs_help_is_contract(self):
        r = self._run(LIST_VERIFY, "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--findings", r.stdout)
        self.assertIn("--checkpoints", r.stdout)

    def test_sast_check_scripts_help_is_contract(self):
        # the three deterministic stages gained --check; --help must advertise it
        for s in ("prefilter.py", "dedup.py", "emit_sarif.py"):
            r = self._run(SCRIPTS / s, "--help")
            self.assertEqual(r.returncode, 0, f"{s} --help failed: {r.stderr}")
            self.assertIn("--check", r.stdout, f"{s} --help lacks --check")


if __name__ == "__main__":
    unittest.main()
