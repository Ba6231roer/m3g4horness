#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for merge_scout.py robustness (fix-mgh-init-scout-merge-robustness).

Covers the `--check` boundary gate (missing `category` / malformed JSON -> exit 2 with
line:col diagnostics; well-formed -> exit 0) and `main()` fold-in defense (malformed JSON
-> structured stdout error + exit 1, NO traceback; missing-category audit candidate ->
skip + warn + `skipped` count; well-formed scout+regex+audit fold-in preserves counts and
appends scout clusters without touching the regex cluster / usage_sites).

Subprocess-driven so exit codes / stdout JSON / stderr diagnostics / "no Traceback" are
exercised exactly as the CLI contract (R5.3b). Zero runtime deps (Python >=3.10 stdlib).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "merge_scout.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

# A JSON string value left unterminated: `..."evidence_snippet":"a\"b}]`
# (`\"` is a valid escaped quote INSIDE the string, then `}` with no closing `"`).
MALFORMED = ('{"repo":"r","candidates":[{"file":"a.java","line":3,'
             '"source":"scout","category":"crypto","evidence_snippet":"a\\"b}]}')


def _run(argv):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout, p.stderr


def _w(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


class TestCheckGate(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_msc_chk_"))

    def test_rejects_missing_category(self):  # 3.1
        sc = _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout", "category": "crypto"},
            {"file": "b.java", "line": 9, "source": "scout"}]})  # index 1: no category
        code, out, _ = _run(["--check", str(sc)])
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        issues = {(v["index"], v["issue"]) for v in data["violations"]}
        self.assertIn((1, "missing category"), issues)

    def test_rejects_malformed_json_exit2_with_linecol(self):  # 3.2
        sc = self.d / "sc.json"
        sc.write_text(MALFORMED, encoding="utf-8")
        code, out, err = _run(["--check", str(sc)])
        self.assertEqual(code, 2)  # NOT 1
        self.assertNotIn("Traceback", err)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "malformed JSON")
        for k in ("lineno", "colno", "msg"):
            self.assertIn(k, data)
        self.assertGreater(data["lineno"], 0)

    def test_well_formed_passes(self):  # 3.3
        sc = _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout", "category": "crypto"}]})
        code, out, _ = _run(["--check", str(sc)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])


class TestMainFoldIn(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_msc_main_"))

    def _base(self):
        # one regex candidate + one regex cluster (both must survive the scout fold-in)
        _w(self.d / "cc.json", {"repo": "r", "candidates": [
            {"id": "R-1", "file": "x.java", "line": 1, "source": "regex",
             "category": "crypto", "pattern": "@Enc", "anchor": {"class": "X"}}]})
        _w(self.d / "cl.json", {"repo": "r", "clusters": [
            {"cluster_id": "crypto::X::regex1", "category": "crypto",
             "usage_sites": ["x.java"], "evidence_files": ["x.java"],
             "candidate_ids": ["R-1"]}], "truncated": False})

    def test_malformed_scout_json_structured_error_no_traceback(self):  # 3.4
        self._base()
        sc = self.d / "sc.json"
        sc.write_text(MALFORMED, encoding="utf-8")
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(sc),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 1)
        self.assertNotIn("Traceback", err)
        data = json.loads(out)
        self.assertEqual(data["status"], "error")
        for k in ("error", "file", "lineno", "colno"):
            self.assertIn(k, data)

    def test_audit_missing_category_skipped_warned_counted(self):  # 3.5
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "crypto", "evidence_snippet": "ok"}]})
        _w(self.d / "au.json", {"audited": 2, "audit_found": [
            {"file": "b.java", "line": 9, "source": "scout", "evidence_snippet": "x"},  # no category
            {"file": "c.java", "line": 5, "source": "scout",
             "category": "audit-logging", "evidence_snippet": "y"}]})
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(self.d / "sc.json"),
                               "--audit", str(self.d / "au.json"),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)
        self.assertIn("skipped", err.lower())
        self.assertIn("b.java", err)  # warn names the dropped candidate
        data = json.loads(out)
        self.assertGreaterEqual(data["skipped"], 1)
        # legal scout (a.java) + legal audit (c.java) folded in = 2
        self.assertEqual(data["scout_candidates_added"], 2)

    def test_well_formed_foldin_preserves_counts_and_clusters(self):  # 3.6
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "authentication", "evidence_snippet": "ok",
             "anchor": {"class": "Login"}}]})
        code, out, _ = _run(["--candidates", str(self.d / "cc.json"),
                             "--scout", str(self.d / "sc.json"),
                             "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["scout_candidates_added"], 1)
        self.assertGreaterEqual(data["scout_clusters_added"], 1)
        # clusters.json: regex cluster preserved (id + usage_sites) + scout cluster appended
        cl = json.loads((self.d / "cl.json").read_text(encoding="utf-8"))
        regex_cluster = next(c for c in cl["clusters"]
                             if c["cluster_id"] == "crypto::X::regex1")
        self.assertEqual(regex_cluster["usage_sites"], ["x.java"])  # untouched
        self.assertGreater(len(cl["clusters"]), 1)  # scout cluster appended
        # controls_candidates.json: regex candidate preserved + scout appended
        cc = json.loads((self.d / "cc.json").read_text(encoding="utf-8"))
        self.assertEqual(len(cc["candidates"]), 2)  # 1 regex + 1 scout
        self.assertEqual(cc["candidates"][0]["source"], "regex")
        self.assertEqual(cc["candidates"][1]["source"], "scout")
        self.assertEqual(cc["provenance"]["scout_merged"], 1)


if __name__ == "__main__":
    unittest.main()
