#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for merge_augment.py (a5: idempotent non-destructive managed block)."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
PY = sys.executable

BEGIN, END = "<!-- mgh-sra:begin -->", "<!-- mgh-sra:end -->"

USER_SPEC = """\
## ADDED Requirements

### Requirement: Initiate transfer
The system SHALL move funds. hasRole('CUSTOMER').
"""
DRAFT = {"capability": "payment-api",
         "gaps": [{"dimension": "horizontal-authz",
                   "anchor": {"requirement": "Initiate transfer", "endpoint": "POST /api/transfer"},
                   "risk": "未校验归属",
                   "recommended_control": {"name": "spring-method-security",
                                           "evidence": "src/api/OrderController.java:42",
                                           "rule_path": ".claude/rules/security-authorization.md"},
                   "matched_signals": {"dimension_fit": True, "business_domain": True,
                                       "business_fact": True}}],
         "security_requirements": [{"heading": "转账归属校验",
                                    "body": "复用 spring-method-security,勿另起。锚点:src/api/OrderController.java:42"}],
         "security_tasks": ["- [ ] 转账接口接入归属校验(复用既有鉴权)"]}


def run(script, *args, cwd):
    return subprocess.run([PY, str(SCRIPTS / f"{script}.py"), *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def build(td: Path, cap="payment-api", spec_text=USER_SPEC):
    ch = td / "openspec" / "changes" / "demo-change"
    (ch / "specs" / cap).mkdir(parents=True)
    (ch / "proposal.md").write_text("# demo\n", encoding="utf-8")
    (ch / "tasks.md").write_text("## Tasks\n- [ ] existing user task\n", encoding="utf-8")
    (ch / "specs" / cap / "spec.md").write_text(spec_text, encoding="utf-8")
    return ch


def write_draft(td, draft):
    d = td / "openspec" / "changes" / "demo-change" / ".mgh-sra" / "drafts"
    d.mkdir(parents=True)
    (d / f"{draft['capability']}.md").write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")


class TestMergeAugment(unittest.TestCase):
    def test_user_requirement_bytes_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); build(td); write_draft(td, DRAFT)
            r = run("merge_augment", "--change", "demo-change", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            spec = (td / "openspec/changes/demo-change/specs/payment-api/spec.md").read_text(encoding="utf-8")
            self.assertIn(BEGIN, spec) and self.assertIn(END, spec)
            # the user requirement heading + body remain byte-for-byte
            self.assertIn("### Requirement: Initiate transfer", spec)
            self.assertIn("The system SHALL move funds. hasRole('CUSTOMER').", spec)

    def test_second_merge_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); build(td); write_draft(td, DRAFT)
            run("merge_augment", "--change", "demo-change", cwd=td)
            once = (td / "openspec/changes/demo-change/specs/payment-api/spec.md").read_text(encoding="utf-8")
            run("merge_augment", "--change", "demo-change", cwd=td)
            twice = (td / "openspec/changes/demo-change/specs/payment-api/spec.md").read_text(encoding="utf-8")
            self.assertEqual(once, twice)  # no duplicate block, identical bytes
            self.assertEqual(twice.count(BEGIN), 1)

    def test_check_ok_then_drift_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); build(td); write_draft(td, DRAFT)
            run("merge_augment", "--change", "demo-change", cwd=td)
            self.assertEqual(run("merge_augment", "--check", "demo-change", cwd=td).returncode, 0)
            # corrupt content OUTSIDE the managed block
            spec = td / "openspec/changes/demo-change/specs/payment-api/spec.md"
            spec.write_text("VANDALIZED\n" + spec.read_text(encoding="utf-8"), encoding="utf-8")
            r = run("merge_augment", "--check", "demo-change", cwd=td)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(json.loads(r.stdout)["ok"])

    def test_fallback_spec_when_no_capability_specs(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ch = td / "openspec" / "changes" / "bare-change"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text("# bare\n", encoding="utf-8")
            (ch / "tasks.md").write_text("## Tasks\n- [ ] x\n", encoding="utf-8")
            d = ch / ".mgh-sra" / "drafts"; d.mkdir(parents=True)
            (d / "security-augmentation.md").write_text(
                json.dumps({"capability": "security-augmentation", "gaps": [],
                            "security_requirements": [{"heading": "安全属性", "body": "x"}],
                            "security_tasks": []}, ensure_ascii=False), encoding="utf-8")
            r = run("merge_augment", "--change", "bare-change", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            fb = td / "openspec/changes/bare-change/specs/security-augmentation/spec.md"
            self.assertTrue(fb.is_file())
            self.assertIn(BEGIN, fb.read_text(encoding="utf-8"))

    def test_merge_writes_only_under_project_subtree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); build(td); write_draft(td, DRAFT)
            run("merge_augment", "--change", "demo-change", cwd=td)
            # every written file is under the project root
            for p in (td / "openspec/changes/demo-change").rglob("*"):
                if p.is_file():
                    self.assertTrue(p.resolve().is_relative_to(td.resolve()), str(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
