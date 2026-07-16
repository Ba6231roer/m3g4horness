#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""render_report.py regression (r2 output adapter for /mgh-srr).

Covers: report + manifest rendered with complete shape; counts taken verbatim from the
finalized drafts (gaps / augmented_requirements / referenced_controls / call_path_*); the
6 honesty boundaries incl. the SRR-specific input-completeness one; report sections in
Simplified Chinese; NEVER touches openspec/ (out-dir under openspec/ exits 2; report must
not reference openspec/); --check accepts a good render and rejects shape violations.
Run: py tests/test_srr_report.py
"""
import json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "render_report.py"
PY = sys.executable


def run(args, cwd):
    r = subprocess.run([PY, str(SCRIPT), *args], cwd=str(cwd), capture_output=True,
                       text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def make_project():
    d = Path(tempfile.mkdtemp(prefix="mgh_srr_r_"))
    (d / "openspec").mkdir()
    return d


def write_run(p, drafts, ctx_extra=None, clarifications=None):
    """Build <p>/.mgh-srr with change_context.json + drafts + clarifications, then render."""
    out = p / ".mgh-srr"
    (out / "drafts").mkdir(parents=True, exist_ok=True)
    ctx = {
        "change": "req.docx", "change_root": str(out.resolve()),
        "project_root": str(p.resolve()),
        "capabilities": [{"name": d["capability"], "requirements": []} for d in drafts],
        "requirements": [], "tasks": [], "mentioned_files": [], "endpoints": [],
        "data_fields": [], "role_hints": [], "candidate_controls": [],
        "clarify_path": str((out / "clarifications.json").resolve()),
        "pending": [{"capability": d["capability"],
                     "draft_path": str((out / "drafts" / f"{d['capability']}.md").resolve()),
                     "done_marker": "x.done"} for d in drafts],
        "memory": None, "rules_source": ".mgh-init/controls_inventory.json",
        "memory_source": "none", "dry_run": False, "truncated": False, "degraded": [],
    }
    if ctx_extra:
        ctx.update(ctx_extra)
    (out / "change_context.json").write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
    for d in drafts:
        (out / "drafts" / f"{d['capability']}.md").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if clarifications is not None:
        (out / "clarifications.json").write_text(
            json.dumps({"clarifications": clarifications}, ensure_ascii=False), encoding="utf-8")
    return out


import unittest


class TestRender(unittest.TestCase):
    def test_renders_report_and_manifest(self):
        p = make_project()
        drafts = [{"capability": "freeform-review", "gaps": [
            {"dimension": "horizontal-authz",
             "anchor": {"requirement": "发起转账", "endpoint": "POST /api/transfer"},
             "risk": "未校验越权",
             "recommended_control": {"name": "AuthzFilter", "reason": "业务域相似",
                "call_path": {"confirmed": True, "path": [], "source": "codegraph", "note": "x"}}},
            {"dimension": "sensitive-data", "anchor": {"field": "bankCardNo"},
             "risk": "未脱敏", "recommended_control": None},
        ], "security_requirements": [{"heading": "Requirement: 越权校验", "body": "复用 AuthzFilter"}],
            "security_tasks": []}]
        out = write_run(p, drafts)
        rc, sout, err = run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        self.assertEqual(rc, 0, err)
        m = json.loads((out / "srr_manifest.json").read_text(encoding="utf-8"))
        rep = (out / "security_review_report.md").read_text(encoding="utf-8")
        # manifest shape
        for f in ("doc", "rules_source", "memory_source", "counts", "boundaries"):
            self.assertIn(f, m)
        # counts from drafts
        self.assertEqual(m["counts"]["gaps"], 2)
        self.assertEqual(m["counts"]["augmented_requirements"], 1)
        self.assertEqual(m["counts"]["referenced_controls"], 1)
        self.assertEqual(m["counts"]["call_path_confirmed"], 1)
        self.assertEqual(m["counts"]["call_path_residual"], 0)
        # boundaries: 6, SRR-specific present
        self.assertGreaterEqual(len(m["boundaries"]), 6)
        self.assertTrue(any("输入完整度" in b or "尽力而为" in b for b in m["boundaries"]))
        # report simplified-chinese sections + reuse suggestion
        for needle in ("安全需求评审报告", "缺口", "建议复用", "AuthzFilter", "诚实边界"):
            self.assertIn(needle, rep)
        self.assertNotIn("openspec/", rep)

    def test_call_path_residual(self):
        p = make_project()
        drafts = [{"capability": "freeform-review", "gaps": [
            {"dimension": "horizontal-authz", "anchor": {"endpoint": "POST /api/x"},
             "risk": "r", "recommended_control": {"name": "C1",
                "call_path": {"confirmed": False, "path": [], "source": "codegraph", "note": ""}}},
            {"dimension": "audit", "anchor": {"endpoint": "POST /api/y"}, "risk": "r",
             "recommended_control": {"name": "C2",
                "call_path": {"confirmed": None, "path": [], "source": "codegraph", "note": ""}}},
        ], "security_requirements": [], "security_tasks": []}]
        out = write_run(p, drafts)
        run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        m = json.loads((out / "srr_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["counts"]["call_path_confirmed"], 0)
        self.assertEqual(m["counts"]["call_path_residual"], 2)

    def test_unconfirmed_defaults_from_memory(self):
        p = make_project()
        drafts = [{"capability": "freeform-review", "gaps": [], "security_requirements": [],
                   "security_tasks": []}]
        cl = [{"fact_key": "a", "question": "Q1"}, {"fact_key": "b", "question": "Q2"}]
        out = write_run(p, drafts, clarifications=cl)
        run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        m = json.loads((out / "srr_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["counts"]["clarifications_asked"], 2)
        self.assertEqual(m["counts"]["unconfirmed_defaults"], 2)  # neither in memory

    def test_empty_drafts_renders(self):
        p = make_project()
        out = write_run(p, drafts=[])
        rc, _, err = run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        self.assertEqual(rc, 0, err)
        m = json.loads((out / "srr_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["counts"]["gaps"], 0)


class TestNeverOpenspec(unittest.TestCase):
    def test_out_under_openspec_exits2(self):
        p = make_project()
        bad = p / "openspec" / "changes" / "c" / ".mgh-srr"
        bad.mkdir(parents=True)
        rc, _, err = run(["--out", str(bad)], cwd=p)
        self.assertEqual(rc, 2)
        self.assertIn("openspec", err)


class TestCheck(unittest.TestCase):
    def test_check_ok(self):
        p = make_project()
        out = write_run(p, [{"capability": "freeform-review", "gaps": [
            {"dimension": "sensitive-data", "anchor": {"field": "x"}, "risk": "r"}],
            "security_requirements": [], "security_tasks": []}])
        run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        rc, sout, _ = run(["--check", str(out)], cwd=p)
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(sout)["ok"])

    def test_check_rejects_missing_manifest(self):
        p = make_project()
        out = p / ".mgh-srr"
        out.mkdir()
        (out / "security_review_report.md").write_text("# x", encoding="utf-8")
        rc, sout, _ = run(["--check", str(out)], cwd=p)
        self.assertEqual(rc, 2)

    def test_check_rejects_openspec_in_report(self):
        p = make_project()
        out = write_run(p, [{"capability": "freeform-review", "gaps": [],
                             "security_requirements": [], "security_tasks": []}])
        run(["--drafts-dir", str(out / "drafts"), "--out", str(out)], cwd=p)
        # tamper: inject an openspec/ reference into the report
        rep = out / "security_review_report.md"
        rep.write_text(rep.read_text(encoding="utf-8") + "\nsee openspec/changes/x", encoding="utf-8")
        rc, sout, _ = run(["--check", str(out)], cwd=p)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
