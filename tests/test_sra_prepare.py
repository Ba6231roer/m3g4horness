#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for prepare_augment.py (a1: parse change -> change_context + signal-1)."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
PY = sys.executable

PROPOSAL = """\
# payment-change
Add POST /api/transfer and POST /refund. Touches src/api/TransferController.java.
Sensitive fields: bankCardNo, idCardNo.
"""
TASKS = """\
## Tasks
- [ ] implement POST /api/transfer
- [ ] mask bankCardNo in response
"""
SPEC = """\
## ADDED Requirements

### Requirement: Initiate transfer
The system SHALL move funds between accounts.

### Requirement: Refund
The system SHALL refund an order by id.
"""
INVENTORY = {"repo": "PROJECT", "format": "claude", "controls": [
    {"name": "spring-method-security", "kind": "auth", "category": "authorization",
     "description": "方法级鉴权", "usage": "@PreAuthorize",
     "evidence": ["src/api/OrderController.java:42"],
     "entry_points": ["src/api/OrderController.java"], "protects": ["src/api/**"], "gaps": []},
    {"name": "card-masking", "kind": "other", "category": "data-masking",
     "description": "卡号脱敏", "usage": "MaskUtil.mask",
     "evidence": ["src/util/MaskUtil.java:8"],
     "entry_points": ["src/util/MaskUtil.java"], "protects": [], "gaps": []},
]}
MEMORY = {"version": 1, "roles": [], "domains": [], "sensitive_fields": [],
          "interface_authz": [], "business_rules": [],
          "clarifications": [{"fact_key": "refund.roles", "value": "customer",
                              "source": "user-asserted", "updated_at": None}]}


def run(script, *args, cwd):
    r = subprocess.run([PY, str(SCRIPTS / f"{script}.py"), *args], cwd=str(cwd),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r


def build_project(td: Path, with_rules=True, with_memory=False):
    ch = td / "openspec" / "changes" / "payment-change"
    (ch / "specs" / "payment-api").mkdir(parents=True)
    (ch / "proposal.md").write_text(PROPOSAL, encoding="utf-8")
    (ch / "tasks.md").write_text(TASKS, encoding="utf-8")
    (ch / "specs" / "payment-api" / "spec.md").write_text(SPEC, encoding="utf-8")
    if with_rules:
        (td / ".mgh-init").mkdir(parents=True, exist_ok=True)
        (td / ".mgh-init" / "controls_inventory.json").write_text(
            json.dumps(INVENTORY), encoding="utf-8")
    if with_memory:
        (td / ".mgh-sra").mkdir(parents=True, exist_ok=True)
        (td / ".mgh-sra" / "business_context.json").write_text(
            json.dumps(MEMORY), encoding="utf-8")
    return ch


class TestPrepareAugment(unittest.TestCase):
    def test_extracts_capabilities_requirements_endpoints_fields(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td, with_rules=True, with_memory=True)
            r = run("prepare_augment", "--change", "payment-change", "--rules", ".mgh-init", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            ctx = json.loads(r.stdout)
            caps = [c["name"] for c in ctx["capabilities"]]
            self.assertIn("payment-api", caps)
            self.assertEqual(len(ctx["capabilities"][0]["requirements"]), 2)
            self.assertTrue(any("POST /api/transfer" in e for e in ctx["endpoints"]))
            self.assertIn("bankCardNo", ctx["data_fields"])

    def test_candidate_control_dimensions_and_overlap(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td)
            r = run("prepare_augment", "--change", "payment-change", "--rules", ".mgh-init", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            cc = json.loads(r.stdout)["candidate_controls"]
            by_name = {c["name"]: c for c in cc}
            # authorization -> [horizontal-authz, vertical-authz]; data-masking -> [sensitive-data]
            self.assertEqual(by_name["spring-method-security"]["dimensions"],
                             ["horizontal-authz", "vertical-authz"])
            self.assertEqual(by_name["card-masking"]["dimensions"], ["sensitive-data"])
            # OrderController overlaps mentioned src/api/TransferController.java? No -> False.
            self.assertFalse(by_name["spring-method-security"]["file_overlap"])

    def test_file_overlap_true_on_shared_entry_point(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            # inventory control guards the SAME file the change mentions
            inv = json.loads(json.dumps(INVENTORY))
            inv["controls"][0]["entry_points"] = ["src/api/TransferController.java"]
            (td / ".mgh-init").mkdir(parents=True)
            (td / ".mgh-init" / "controls_inventory.json").write_text(json.dumps(inv), encoding="utf-8")
            build_project(td, with_rules=False)
            r = run("prepare_augment", "--change", "payment-change", "--rules", ".mgh-init", cwd=td)
            cc = {c["name"]: c for c in json.loads(r.stdout)["candidate_controls"]}
            self.assertTrue(cc["spring-method-security"]["file_overlap"])

    def test_pending_draft_paths_absolute_and_in_subtree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td)
            r = run("prepare_augment", "--change", "payment-change", "--rules", ".mgh-init", cwd=td)
            ctx = json.loads(r.stdout)
            self.assertEqual(len(ctx["pending"]), 1)
            dp = Path(ctx["pending"][0]["draft_path"])
            self.assertTrue(dp.is_absolute())
            self.assertTrue(dp.resolve().is_relative_to(td.resolve()))
            self.assertEqual(ctx["pending"][0]["capability"], "payment-api")

    def test_memory_loaded_when_present(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td, with_rules=True, with_memory=True)
            ctx = json.loads(run("prepare_augment", "--change", "payment-change",
                                 "--rules", ".mgh-init", cwd=td).stdout)
            self.assertIsNotNone(ctx["memory"])
            self.assertEqual(ctx["memory"]["clarifications"][0]["fact_key"], "refund.roles")

    def test_no_rules_empty_candidate_controls(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td, with_rules=False)
            ctx = json.loads(run("prepare_augment", "--change", "payment-change", cwd=td).stdout)
            self.assertEqual(ctx["candidate_controls"], [])
            self.assertEqual(ctx["rules_source"], "none")

    def test_no_capability_specs_fallback_pending(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            ch = td / "openspec" / "changes" / "bare-change"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text("bare change POST /api/ping\n", encoding="utf-8")
            (ch / "tasks.md").write_text("- [ ] do thing\n", encoding="utf-8")
            ctx = json.loads(run("prepare_augment", "--change", "bare-change", cwd=td).stdout)
            self.assertEqual(ctx["capabilities"], [])
            self.assertEqual(ctx["pending"][0]["capability"], "security-augmentation")

    def test_check_malformed_inventory_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inv = {"controls": [{"name": "", "category": "authorization", "evidence": []}]}
            (td / "controls_inventory.json").write_text(json.dumps(inv), encoding="utf-8")
            r = run("prepare_augment", "--check", "controls_inventory.json", cwd=td)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(json.loads(r.stdout)["ok"])

    def test_check_dir_autodiscover_ok(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build_project(td)
            r = run("prepare_augment", "--check", ".mgh-init", cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
