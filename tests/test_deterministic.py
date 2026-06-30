#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the deterministic stage scripts (stdlib unittest)."""
import importlib.util, sys, unittest, json, os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestPrefilter(unittest.TestCase):
    def setUp(self):
        self.pf = _load("prefilter")

    def test_drops_missing_refs(self):
        kept, drop = self.pf.run([{"id": "A", "confidence": 0.9,
                                    "source_ref": "", "sink_ref": ""}], 0.4, None)
        self.assertEqual(kept, [])
        self.assertIn("source_ref", drop[0]["dropped_reason"])

    def test_drops_low_confidence(self):
        f = {"id": "B", "confidence": 0.1, "file": "src/a.java",
             "source_ref": "src/a.java:1", "sink_ref": "src/a.java:2"}
        kept, _ = self.pf.run([f], 0.4, None)
        self.assertEqual(kept, [])

    def test_drops_test_path(self):
        f = {"id": "C", "confidence": 0.9, "file": "test/x.java",
             "source_ref": "test/x.java:1", "sink_ref": "test/x.java:2"}
        kept, drop = self.pf.run([f], 0.4, None)
        self.assertEqual(kept, [])
        self.assertIn("test", drop[0]["dropped_reason"])

    def test_determinism(self):
        fs = [{"id": "D", "confidence": 0.9, "file": "src/a.java",
               "source_ref": "src/a.java:1", "sink_ref": "src/a.java:2"}]
        self.assertEqual(self.pf.run(fs, 0.4, None), self.pf.run(fs, 0.4, None))


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.dd = _load("dedup")

    def test_merges_same_loc_cwe(self):
        fs = [
            {"id": "1", "title": "SQL Injection login", "cwe": "CWE-89",
             "file": "src/L.java", "line_start": 71, "confidence": 0.9},
            {"id": "2", "title": "sqli login", "cwe": "CWE-89",
             "file": "src/L.java", "line_start": 73, "confidence": 0.7},
        ]
        canon, dups = self.dd.run(fs, window=5, title_thresh=0.4)
        self.assertEqual(len(canon), 1)
        self.assertEqual(len(dups), 1)
        self.assertEqual(canon[0]["id"], "1")  # higher confidence wins


class TestSarif(unittest.TestCase):
    def setUp(self):
        self.s = _load("emit_sarif")

    def test_cvss_full_vector_is_98(self):
        score = self.s.cvss_base(self.s.parse_vector(
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"))
        self.assertAlmostEqual(score, 9.8, places=1)
        self.assertEqual(self.s.severity_band(score), "Critical")

    def test_cvss_scope_changed(self):
        score = self.s.cvss_base(self.s.parse_vector(
            "CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:C/C:H/I:H/A:N"))
        self.assertGreater(score, 8.0)

    def test_severity_band(self):
        self.assertEqual(self.s.severity_band(None), "Info")
        self.assertEqual(self.s.severity_band(0.0), "Info")
        self.assertEqual(self.s.severity_band(3.5), "Low")
        self.assertEqual(self.s.severity_band(5.0), "Medium")
        self.assertEqual(self.s.severity_band(8.0), "High")
        self.assertEqual(self.s.severity_band(9.5), "Critical")

    def test_enrich_consistency(self):
        fs = [{"cwe": "CWE-89", "cvss_vector":
               "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}]
        out = self.s.enrich(fs)[0]
        self.assertEqual(out["severity"], "Critical")
        self.assertAlmostEqual(out["cvss_score"], 9.8, places=1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
