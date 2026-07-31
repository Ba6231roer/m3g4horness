#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_verify_jobs.py (s6 fan-out enumeration).

Mirrors list_chunks.py / list_scout_batches.py (resume-aware pending work-list). The s5
product is prefilter output {kept[], dropped[], stats} — findings live under `kept[]`.
finding_id PREFERS the canonical Finding `id`, else DERIVES a filename-safe id from
{file, line_start, vuln_class} with positional collision disambiguation. Asserts:
  - total = real kept count, NOT wrapper key count;
  - finding_id stable (prefer id; derive otherwise; -2/-3 on collision);
  - line projected from line_start;
  - pending excludes done findings; total == done + len(pending).
"""
import contextlib, importlib.util, io, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _kept(*findings):
    return {"kept": list(findings), "dropped": [], "stats": {}}


class TestListVerifyJobs(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_verify_jobs")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lv_"))

    def _write(self, wrapper):
        p = self.d / "s5_filtered.json"
        p.write_text(json.dumps(wrapper, ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, findings_path, checkpoints=None):
        argv = ["list_verify_jobs.py", "--findings", str(findings_path)]
        if checkpoints:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _mark_done(self, fid):
        cp = self.d / "s6"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{fid}.json.done").write_text("", encoding="utf-8")

    def test_total_is_kept_count(self):
        code, out, _ = self._run(self._write(_kept(
            {"id": "F-001", "file": "a.java", "line_start": 10, "vuln_class": "injection",
             "source_ref": "a.java:10", "sink_ref": "b.java:1"},
            {"id": "F-002", "file": "c.java", "line_start": 20, "vuln_class": "xss",
             "source_ref": "c.java:20", "sink_ref": "d.java:2"})))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 2)

    def test_finding_id_prefers_id_field(self):
        code, out, _ = self._run(self._write(_kept(
            {"id": "F-001", "file": "a.java", "line_start": 10, "vuln_class": "injection"})))
        self.assertEqual(json.loads(out)["pending"][0]["finding_id"], "F-001")

    def test_finding_id_derived_when_absent(self):
        code, out, _ = self._run(self._write(_kept(
            {"file": "src/x.java", "line_start": 71, "vuln_class": "injection"})))
        fid = json.loads(out)["pending"][0]["finding_id"]
        self.assertEqual(fid, "src-x.java-71-injection")

    def test_finding_id_collision_disambiguation(self):
        # two findings with no id, same file/line/vuln_class -> base + -2
        code, out, _ = self._run(self._write(_kept(
            {"file": "x.java", "line_start": 5, "vuln_class": "sqli"},
            {"file": "x.java", "line_start": 5, "vuln_class": "sqli"})))
        ids = [p["finding_id"] for p in json.loads(out)["pending"]]
        self.assertEqual(sorted(ids), ["x.java-5-sqli", "x.java-5-sqli-2"])

    def test_line_projected_from_line_start(self):
        code, out, _ = self._run(self._write(_kept(
            {"id": "F-1", "file": "a.java", "line_start": 42, "vuln_class": "xss",
             "source_ref": "a.java:42", "sink_ref": "b.java:1"})))
        lite = json.loads(out)["pending"][0]
        self.assertEqual(lite["line"], 42)
        self.assertEqual(lite["vuln_class"], "xss")

    def test_resume_pending_excludes_done(self):
        p = self._write(_kept(
            {"id": "F-001", "file": "a.java", "line_start": 1, "vuln_class": "x"},
            {"id": "F-002", "file": "b.java", "line_start": 2, "vuln_class": "y"}))
        cp = self.d / "s6"
        self._mark_done("F-001")
        code, out, _ = self._run(p, cp)
        data = json.loads(out)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["done"], 1)
        self.assertEqual([j["finding_id"] for j in data["pending"]], ["F-002"])
        self.assertEqual(data["total"], data["done"] + len(data["pending"]))

    def test_empty_kept(self):
        code, out, _ = self._run(self._write(_kept()))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pending"], [])

    def test_findings_key_wrapper_accepted(self):
        p = self._write({"findings": [
            {"id": "F-1", "file": "a.java", "line_start": 1, "vuln_class": "x"}]})
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 1)

    def test_missing_file_exit1(self):
        code, _, _ = self._run(self.d / "nope.json")
        self.assertEqual(code, 1)


# ---- list_verify_jobs.py: per-unit materialization + paging (request-context-budget) ----

_VERIFY_FINDINGS = [
    {"id": "F-001", "file": "a.java", "line_start": 10, "vuln_class": "injection",
     "source_ref": "a.java:10", "sink_ref": "b.java:1", "snippet": "rs.exec(sql)"},
    {"id": "F-002", "file": "c.java", "line_start": 20, "vuln_class": "xss",
     "source_ref": "c.java:20", "sink_ref": "d.java:2"},
]


class TestListVerifyJobsMaterialize(unittest.TestCase):
    """--materialize: slim envelope + per-finding input files + paging + oversize (no slice)."""

    def setUp(self):
        self.m = _load("list_verify_jobs")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lvm_"))
        self.inputs = self.d / "inputs" / "s6"
        self.cp = self.d / "checkpoints" / "s6"

    def _write(self, findings):
        p = self.d / "s5_filtered.json"
        p.write_text(json.dumps({"kept": findings, "dropped": [], "stats": {}},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, findings_path, *extra):
        argv = ["list_verify_jobs.py", "--findings", str(findings_path),
                "--checkpoints", str(self.cp),
                "--materialize", str(self.inputs)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_slim_envelope_sinks_source_sink(self):
        p = self._write(_VERIFY_FINDINGS)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        for k in ("offset", "limit", "effective_limit", "shrunk"):
            self.assertIn(k, data)
        it = data["pending"][0]
        # slim: NO source_ref/sink_ref; HAS input_path/bytes/oversize
        self.assertNotIn("source_ref", it)
        self.assertNotIn("sink_ref", it)
        for k in ("input_path", "bytes", "oversize", "checkpoint_path", "done_marker"):
            self.assertIn(k, it)
        # input file carries the full record (source_ref/sink_ref sunk in)
        ip = Path(it["input_path"])
        self.assertTrue(ip.is_file())
        self.assertEqual(it["bytes"], ip.stat().st_size)
        inp = json.loads(ip.read_text(encoding="utf-8"))
        self.assertEqual(inp["source_ref"], "a.java:10")
        self.assertEqual(inp["sink_ref"], "b.java:1")
        self.assertEqual(inp["snippet"], "rs.exec(sql)")

    def test_paging_offset_limit(self):
        p = self._write(_VERIFY_FINDINGS)
        _, out, _ = self._run(p, "--offset", "1", "--limit", "1")
        data = json.loads(out)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["pending"]), 1)

    def test_page_shrinks_to_orch_budget(self):
        p = self._write(_VERIFY_FINDINGS)
        _, out, _ = self._run(p, "--orch-budget-bytes", "200")
        data = json.loads(out)
        self.assertTrue(data["shrunk"])
        page_bytes = len(json.dumps(data["pending"]).encode("utf-8"))
        self.assertTrue(page_bytes <= 200 or data["effective_limit"] == 1)

    def test_oversize_flagged_not_sliced(self):
        # tiny budget -> oversize flagged, but the finding is NOT sharded (atomic s6 unit)
        p = self._write(_VERIFY_FINDINGS)
        _, out, _ = self._run(p, "--max-unit-bytes", "50")
        data = json.loads(out)
        self.assertEqual(len(data["pending"]), 2)   # both findings still present
        self.assertTrue(all(it["oversize"] for it in data["pending"]))

    def test_resume_skips_done_unit(self):
        p = self._write(_VERIFY_FINDINGS)
        self._run(p)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "F-001.json.done").write_text("", encoding="utf-8")
        _, out, _ = self._run(p)
        data = json.loads(out)
        ids = [it["finding_id"] for it in data["pending"]]
        self.assertNotIn("F-001", ids)
        self.assertEqual(data["done"], 1)

    def test_bad_budget_exit2(self):
        p = self._write(_VERIFY_FINDINGS)
        code, _, _ = self._run(p, "--orch-budget-bytes", "-1")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
