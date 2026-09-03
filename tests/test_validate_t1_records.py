#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for validate_t1_records.py — T1→T2 boundary shape gate.

Covers the spec scenarios: conforming record passes; nested controls[] drift is
rejected; missing/empty/non-list evidence and non-string anchors are rejected;
non-canonical category / non-vvah kind / category->kind mismatch are rejected;
BOM is advisory under --check and losslessly stripped + idempotent under
--strip-bom; empty dir is ok (records:0); missing dir exits 1; the validator
runs under any cwd (R5.3a import-robustness).

Subprocess-driven so exit codes / stdout JSON / stderr diagnostics are exercised
exactly as the CLI contract. Zero runtime deps (Python >=3.10 stdlib).
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "validate_t1_records.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
_BOM = b"\xef\xbb\xbf"


def _run(argv):
    p = subprocess.run([sys.executable, str(SCRIPT), *argv],
                       capture_output=True, text=True, encoding="utf-8", env=ENV)
    return p.returncode, p.stdout, p.stderr


def _w(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return path


def _wb(path: Path, raw: bytes):
    path.write_bytes(raw)
    return path


def _conforming(cluster_id="authorization::Sec::ab12cd34", **over):
    rec = {"cluster_id": cluster_id,
           "unit": over.pop("unit", cluster_id),   # identity double-cover: unit == cluster_id
           "name": "spring-method-security",
           "category": "authorization", "kind": "auth",
           "evidence": ["src/Sec.java:Sec:check"], "entry_points": ["src/Sec.java"],
           "confidence": 0.8}
    rec.update(over)
    return rec


class TestCheckShape(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_t1_chk_"))
        self.cp = self.d / "t1"
        self.cp.mkdir()

    def _check(self):
        return _run(["--check", "--checkpoints", str(self.cp)])

    def test_conforming_passes(self):  # 2.1
        _w(self.cp / "ok.json", _conforming())
        code, out, _ = self._check()
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["records"], 1)
        self.assertEqual(data["violations"], [])
        self.assertEqual(data["bom"], [])

    def test_each_canonical_category_kind_pair_passes(self):  # 2.1 (8 cats)
        pairs = [("input-validation", "input-validation"),
                 ("authentication", "auth"), ("authorization", "auth"),
                 ("data-masking", "other"), ("crypto", "other"),
                 ("csrf", "other"), ("rate-limiting", "other"),
                 ("audit-logging", "other")]
        for i, (cat, kind) in enumerate(pairs):
            _w(self.cp / f"c{i}.json", _conforming(
                cluster_id=f"{cat}::X::{i}", category=cat, kind=kind))
        code, out, _ = self._check()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["records"], 8)

    def test_nested_controls_drift_rejected(self):  # 2.2
        _w(self.cp / "drift.json", {
            "cluster_id": "authorization::Auth::ef", "name": "x",
            "category": "authorization",
            "controls": [{"anchor_file": "a.java", "confidence": 0.5}]})
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        issues = [(v["file"].replace("\\", "/").rsplit("/", 1)[-1], v["issue"])
                  for v in data["violations"]]
        self.assertIn(("drift.json", "nested controls[] drift"), issues)
        # cluster_id surfaced for orchestrator re-spawn routing
        self.assertTrue(any(v["cluster_id"] == "authorization::Auth::ef"
                            for v in data["violations"]))

    def test_evidence_forms_rejected(self):  # 2.3
        cases = {
            "missing.json": {"cluster_id": "crypto::C::1", "name": "n",
                             "category": "crypto", "kind": "other",
                             "entry_points": [], "confidence": 0.1},
            "empty.json": {"cluster_id": "crypto::C::2", "name": "n",
                           "category": "crypto", "kind": "other",
                           "evidence": [], "entry_points": [], "confidence": 0.1},
            "notlist.json": {"cluster_id": "crypto::C::3", "name": "n",
                             "category": "crypto", "kind": "other",
                             "evidence": "x.java", "entry_points": [],
                             "confidence": 0.1},
            "nonstr.json": {"cluster_id": "crypto::C::4", "name": "n",
                            "category": "crypto", "kind": "other",
                            "evidence": [5], "entry_points": [], "confidence": 0.1},
            "emptyanchor.json": {"cluster_id": "crypto::C::5", "name": "n",
                                 "category": "crypto", "kind": "other",
                                 "evidence": ["  "], "entry_points": [],
                                 "confidence": 0.1},
        }
        for fn, rec in cases.items():
            _w(self.cp / fn, rec)
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        # each case yields its evidence violation + (these raw fixtures carry no
        # `unit` and no marker →) the missing-unit violation
        self.assertEqual(len(json.loads(out)["violations"]), 2 * len(cases))

    def test_category_kind_enum_and_mapping_rejected(self):  # 2.4
        _w(self.cp / "badcat.json", _conforming(cluster_id="x::a::1",
            category="access-control"))  # not canonical (pre-alias raw form)
        _w(self.cp / "badkind.json", _conforming(cluster_id="x::b::2",
            kind="encryption"))  # not in vvah 6-enum
        _w(self.cp / "mismatch.json", _conforming(cluster_id="x::c::3",
            category="authentication", kind="sandbox"))  # auth->auth, got sandbox
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        issues = {v["issue"] for v in json.loads(out)["violations"]}
        self.assertTrue(any("not in init 8" in i for i in issues))
        self.assertTrue(any("not in vvah 6-enum" in i for i in issues))
        self.assertTrue(any("maps to kind" in i for i in issues))

    def test_missing_and_nonobject_entrypoints_confidence_rejected(self):
        for fn, over in (("noep.json", {"entry_points": None}),
                         ("noconf.json", {"confidence": None}),
                         ("confbool.json", {"confidence": True}),
                         ("nocluster.json", {"cluster_id": ""}),
                         ("noname.json", {"name": ""})):
            _w(self.cp / fn, _conforming(**over))
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        self.assertGreaterEqual(len(json.loads(out)["violations"]), 5)

    def test_empty_dir_ok(self):  # 2.6
        code, out, _ = self._check()
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["records"], 0)
        self.assertEqual(data["violations"], [])

    def test_missing_dir_exits_1(self):  # 2.6
        code, _, err = _run(["--check", "--checkpoints",
                             str(self.d / "nope")])
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_malformed_json_is_violation_not_crash(self):
        (self.cp / "bad.json").write_text('{"cluster_id":', encoding="utf-8")
        code, out, err = self._check()
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", err)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertTrue(any("malformed JSON" in v["issue"]
                            for v in data["violations"]))


class TestUnitDoubleCover(unittest.TestCase):
    """`unit` field (identity double-cover, fix-mgh-init-done-marker-identity):
    new-form record with unit passes; unit != cluster_id → violation; no unit +
    forward marker exists → WARNING (historical form, 无需处理); no unit + no
    marker → violation (new record MUST carry it)."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_t1_unit_"))
        self.cp = self.d / "t1"
        self.cp.mkdir()

    def _check(self):
        return _run(["--check", "--checkpoints", str(self.cp)])

    def test_new_form_record_with_unit_passes(self):
        _w(self.cp / "new.json", _conforming(cluster_id="crypto::N::1",
                                             unit="crypto::N::1"))
        code, out, _ = self._check()
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["warnings"], [])
        self.assertIn("warnings", data)                   # field恒在 (shape stable)

    def test_shard_unit_matches_cluster_id_passes(self):
        # shard unit: cluster_id AND unit both carry the `::shard-<n>` form.
        cid = "crypto::S::2::shard-0"
        _w(self.cp / "shard.json", _conforming(cluster_id=cid))
        code, out, _ = self._check()
        self.assertEqual(code, 0)

    def test_unit_mismatch_cluster_id_is_violation(self):
        _w(self.cp / "drift.json", _conforming(cluster_id="crypto::D::3",
                                               unit="crypto::OTHER::9"))
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        issues = {v["issue"] for v in json.loads(out)["violations"]}
        self.assertTrue(any("unit" in i and "!= cluster_id" in i for i in issues), issues)

    def test_missing_unit_without_marker_is_violation(self):
        _w(self.cp / "fresh.json", _conforming(cluster_id="crypto::F::4", unit=None))
        code, out, _ = self._check()
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("missing/empty unit" in v["issue"] for v in violations))
        self.assertEqual(json.loads(out)["warnings"], [])

    def test_missing_unit_with_marker_is_warning_not_violation(self):
        # historical form: pre-fix record (no unit) whose forward marker exists →
        # warning only, exit 0 (done judgment is forward marker-path; `unit` not
        # load-bearing; re-spawning would re-burn finished work — unacceptable).
        cid = "crypto::H::5"
        _w(self.cp / f"{cid.replace('::', '__')}.json",
           _conforming(cluster_id=cid, unit=None))
        (self.cp / f"{cid.replace('::', '__')}.json.done").write_text("", encoding="utf-8")
        code, out, _ = self._check()
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("historical", data["warnings"][0]["issue"])
        self.assertIn("no action needed", data["warnings"][0]["issue"])


class TestBomAdvisory(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_t1_bom_"))
        self.cp = self.d / "t1"
        self.cp.mkdir()

    def test_check_reports_bom_advisory_not_violation(self):  # 2.5
        payload = json.dumps(_conforming(), ensure_ascii=False).encode("utf-8")
        _wb(self.cp / "bom.json", _BOM + payload)
        code, out, _ = _run(["--check", "--checkpoints", str(self.cp)])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["bom"]), 1)
        self.assertEqual(data["violations"], [])


class TestStripBom(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mgh_t1_strip_"))
        self.cp = self.d / "t1"
        self.cp.mkdir()

    def test_strip_removes_bom_losslessly(self):  # 2.5
        payload = json.dumps(_conforming(), ensure_ascii=False).encode("utf-8")
        f = _wb(self.cp / "bom.json", _BOM + payload)
        code, out, _ = _run(["--strip-bom", "--checkpoints", str(self.cp)])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data["stripped"]), 1)
        self.assertEqual(f.read_bytes(), payload)  # only BOM gone, rest identical

    def test_no_bom_file_byte_identical(self):  # 2.5
        payload = json.dumps(_conforming(), ensure_ascii=False).encode("utf-8")
        f = _wb(self.cp / "plain.json", payload)
        before = f.read_bytes()
        code, out, _ = _run(["--strip-bom", "--checkpoints", str(self.cp)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stripped"], [])
        self.assertEqual(f.read_bytes(), before)

    def test_strip_idempotent(self):  # 2.5
        payload = json.dumps(_conforming(), ensure_ascii=False).encode("utf-8")
        _wb(self.cp / "bom.json", _BOM + payload)
        _run(["--strip-bom", "--checkpoints", str(self.cp)])
        code, out, _ = _run(["--strip-bom", "--checkpoints", str(self.cp)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["stripped"], [])

    def test_strip_then_check_ok(self):
        payload = json.dumps(_conforming(), ensure_ascii=False).encode("utf-8")
        _wb(self.cp / "bom.json", _BOM + payload)
        _run(["--strip-bom", "--checkpoints", str(self.cp)])
        code, out, _ = _run(["--check", "--checkpoints", str(self.cp)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["bom"], [])


class TestAnyCwd(unittest.TestCase):
    def test_runs_from_non_script_cwd(self):  # 2.7 (R5.3a import robustness)
        d = Path(tempfile.mkdtemp(prefix="mgh_t1_cwd_"))
        cp = d / "t1"
        cp.mkdir()
        _w(cp / "ok.json", _conforming())
        # cwd is a temp dir NOT the scripts dir; sibling import must still resolve
        p = subprocess.run([sys.executable, str(SCRIPT), "--check",
                            "--checkpoints", str(cp)],
                           capture_output=True, text=True, encoding="utf-8",
                           env=ENV, cwd=str(d))
        self.assertEqual(p.returncode, 0, msg=p.stderr)
        self.assertTrue(json.loads(p.stdout)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
