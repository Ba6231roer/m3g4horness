#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for merge_scout.py robustness (fix-mgh-init-scout-merge-robustness).

Covers the `--check` boundary gate (missing `category` / malformed JSON -> exit 2 with
line:col diagnostics; well-formed -> exit 0) and `main()` fold-in defense (malformed JSON
-> structured stdout error + exit 1, NO traceback; missing-required-field (category/file)
candidate -> skip + warn naming the field + `skipped` count; well-formed scout+regex+audit fold-in preserves counts and
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

    def test_scout_missing_file_skipped_warned_no_traceback(self):  # 2.1 missing file
        # Before the fix, _normalize direct-indexed c["file"] -> KeyError abort. Now the
        # candidate is skipped + warned and the merge completes (exit 0, NO traceback).
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "crypto", "evidence_snippet": "ok"},   # well-formed (folded)
            {"line": 9, "source": "scout",
             "category": "authn", "evidence_snippet": "x"}]})   # index 1: no file -> skip
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(self.d / "sc.json"),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)                                # NOT a KeyError abort
        self.assertNotIn("Traceback", err)
        self.assertNotIn("KeyError", err)
        self.assertIn("missing required field(s): file", err)    # warn names the field
        data = json.loads(out)
        self.assertGreaterEqual(data["skipped"], 1)
        self.assertEqual(data["scout_candidates_added"], 1)      # only the well-formed one

    def test_scout_missing_category_warns_category(self):  # 2.2 missing category (unchanged)
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "b.java", "line": 9, "source": "scout",
             "evidence_snippet": "x"}]})  # no category
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(self.d / "sc.json"),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)
        self.assertIn("missing required field(s): category", err)
        data = json.loads(out)
        self.assertGreaterEqual(data["skipped"], 1)
        self.assertEqual(data["scout_candidates_added"], 0)

    def test_scout_missing_both_fields_warns_once_lists_both(self):  # 2.2 missing both
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"line": 9, "source": "scout", "evidence_snippet": "x"}]})  # no file, no category
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(self.d / "sc.json"),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)
        self.assertNotIn("Traceback", err)
        self.assertIn("missing required field(s)", err)
        self.assertIn("category", err)   # both fields named
        self.assertIn("file", err)
        self.assertEqual(err.count("scout candidate #"), 1)  # single skip, no double warn
        data = json.loads(out)
        self.assertEqual(data["skipped"], 1)
        self.assertEqual(data["scout_candidates_added"], 0)

    def test_well_formed_scout_no_warn(self):  # 2.2 well-formed unaffected
        self._base()
        _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "crypto", "evidence_snippet": "ok"}]})
        code, out, err = _run(["--candidates", str(self.d / "cc.json"),
                               "--scout", str(self.d / "sc.json"),
                               "--clusters", str(self.d / "cl.json")])
        self.assertEqual(code, 0)
        self.assertNotIn("warn", err)
        self.assertNotIn("missing required field", err)
        data = json.loads(out)
        self.assertEqual(data["scout_candidates_added"], 1)
        self.assertEqual(data["skipped"], 0)


# ---- D3: fold-in boundary category normalization (fix-mgh-init-scout-stranding) ----


class TestFoldInNormalize(unittest.TestCase):
    """init_tier.normalize_category maps non-canonical scout categories at fold-in so T2
    only sees the canonical 8; an UNMAPPED category is skipped + warned, never passed."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_msc_norm_"))
        _w(self.d / "cc.json", {"repo": "r", "candidates": [
            {"id": "R-1", "file": "x.java", "line": 1, "source": "regex",
             "category": "crypto", "pattern": "@Enc", "anchor": {"class": "X"}}]})
        _w(self.d / "cl.json", {"repo": "r", "clusters": [
            {"cluster_id": "crypto::X::regex1", "category": "crypto",
             "usage_sites": ["x.java"], "evidence_files": ["x.java"],
             "candidate_ids": ["R-1"]}], "truncated": False})

    def _fold(self, scout_cands):
        _w(self.d / "sc.json", {"repo": "r", "candidates": scout_cands})
        return _run(["--candidates", str(self.d / "cc.json"),
                     "--scout", str(self.d / "sc.json"),
                     "--clusters", str(self.d / "cl.json")])

    def test_alias_normalization_hits(self):
        # drifted "access-control" folds in as canonical "authorization"
        code, out, err = self._fold([
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "access-control", "evidence_snippet": "ok",
             "anchor": {"class": "Authz"}}])
        self.assertEqual(code, 0)
        self.assertNotIn("warn", err)
        self.assertEqual(json.loads(out)["scout_candidates_added"], 1)
        cc = json.loads((self.d / "cc.json").read_text(encoding="utf-8"))
        scout = next(c for c in cc["candidates"] if c["source"] == "scout")
        self.assertEqual(scout["category"], "authorization")
        cl = json.loads((self.d / "cl.json").read_text(encoding="utf-8"))
        self.assertTrue(any(c["category"] == "authorization" for c in cl["clusters"]))

    def test_unmapped_category_skipped_warned(self):
        # "runtime-guard" is not canonical and not aliased → skip + warn, NOT folded
        code, out, err = self._fold([
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "runtime-guard", "evidence_snippet": "ok",
             "anchor": {"class": "Guard"}}])
        self.assertEqual(code, 0)
        self.assertIn("not in the 8 canonical categories", err)
        data = json.loads(out)
        self.assertEqual(data["scout_candidates_added"], 0)
        self.assertEqual(data["skipped"], 1)

    def test_check_rejects_noncanonical_exit2(self):
        sc = _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "runtime-guard"}]})
        code, out, _ = _run(["--check", str(sc)])
        self.assertEqual(code, 2)
        issues = {v["issue"] for v in json.loads(out)["violations"]}
        self.assertTrue(any("canonical" in i for i in issues), issues)

    def test_check_passes_canonical_and_alias_exit0(self):
        # canonical + aliased (access-control → authorization) both pass --check
        sc = _w(self.d / "sc.json", {"repo": "r", "candidates": [
            {"file": "a.java", "line": 3, "source": "scout", "category": "authorization"},
            {"file": "b.java", "line": 5, "source": "scout", "category": "access-control"}]})
        code, out, _ = _run(["--check", str(sc)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])


# ---- D2: fold-in cascade invalidation of downstream aggregate .done ----

_CASCADE_CLUSTERS = [
    {"cluster_id": "crypto::X::regex1", "category": "crypto",
     "usage_sites": ["x.java"], "evidence_files": ["x.java"], "candidate_ids": ["R-1"]}]


class TestFoldInCascade(unittest.TestCase):
    """fold-in with scout_candidates_added > 0 cascade-invalidates t2/t3/t4 aggregate
    .done (stale credentials from regex-only input); added == 0 leaves them intact."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_msc_cas_"))
        _w(self.d / "cc.json", {"repo": "r", "candidates": [
            {"id": "R-1", "file": "x.java", "line": 1, "source": "regex",
             "category": "crypto", "pattern": "@Enc", "anchor": {"class": "X"}}]})
        _w(self.d / "cl.json", {"repo": "r", "clusters": _CASCADE_CLUSTERS,
                                "truncated": False})

    def _markers(self):
        cp = self.d / "checkpoints"
        rels = ("t2/synthesis.json.done",
                "t3/authorization.opencode.json.done",
                "t4/consistency.json.done")
        out = []
        for rel in rels:
            p = cp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8")
            out.append(p)
        return out

    def _fold(self, scout_cands):
        _w(self.d / "sc.json", {"repo": "r", "candidates": scout_cands})
        return _run(["--candidates", str(self.d / "cc.json"),
                     "--scout", str(self.d / "sc.json"),
                     "--clusters", str(self.d / "cl.json")])

    def test_foldin_added_gt0_invalidates_downstream(self):
        markers = self._markers()
        code, out, _ = self._fold([
            {"file": "a.java", "line": 3, "source": "scout",
             "category": "authorization", "evidence_snippet": "ok",
             "anchor": {"class": "Authz"}}])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertGreaterEqual(data["scout_candidates_added"], 1)
        self.assertEqual(data["invalidated_tiers"], ["t2", "t3", "t4"])
        for m in markers:
            self.assertFalse(m.exists(), f"{m} should be cascade-invalidated")

    def test_foldin_added_eq0_keeps_downstream(self):
        markers = self._markers()
        # scout candidate duplicates the regex candidate (same file/anchor/category) →
        # dedup removes it → added == 0 → input unchanged → markers stay valid
        code, out, _ = self._fold([
            {"file": "x.java", "line": 1, "source": "scout",
             "category": "crypto", "evidence_snippet": "ok",
             "anchor": {"class": "X"}}])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["scout_candidates_added"], 0)
        self.assertEqual(data["invalidated_tiers"], [])
        for m in markers:
            self.assertTrue(m.exists(), f"{m} must survive when added == 0")


if __name__ == "__main__":
    unittest.main()
