#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for merge_memory.py (idempotent fact_key business-memory accumulation)."""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
PY = sys.executable


def run(script, *args, cwd):
    return subprocess.run([PY, str(SCRIPTS / f"{script}.py"), *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def write_answers(td: Path, obj):
    p = td / "answers.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def load_mem(td: Path):
    return json.loads((td / ".mgh-sra" / "business_context.json").read_text(encoding="utf-8"))


class TestMergeMemory(unittest.TestCase):
    def test_first_run_creates_with_version(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mem = td / ".mgh-sra" / "business_context.json"
            ans = write_answers(td, {"refund.roles": "customer"})
            r = run("merge_memory", "--memory", str(mem), "--answers", str(ans), cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["created"])
            m = load_mem(td)
            self.assertEqual(m["version"], 1)
            self.assertEqual(len(m["clarifications"]), 1)
            self.assertEqual(m["clarifications"][0]["source"], "user-asserted")

    def test_fact_key_updates_in_place(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); mem = td / ".mgh-sra" / "business_context.json"
            run("merge_memory", "--memory", str(mem), "--answers",
                str(write_answers(td, {"refund.roles": "customer"})), cwd=td)
            run("merge_memory", "--memory", str(mem), "--answers",
                str(write_answers(td, {"refund.roles": "customer and merchant"})), cwd=td)
            m = load_mem(td)
            vals = [c["value"] for c in m["clarifications"] if c["fact_key"] == "refund.roles"]
            self.assertEqual(vals, ["customer and merchant"])  # updated, not appended
            self.assertEqual(len(m["clarifications"]), 1)      # no duplicate

    def test_rerun_no_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); mem = td / ".mgh-sra" / "business_context.json"
            ans = str(write_answers(td, {"a": "1", "b": "2"}))
            run("merge_memory", "--memory", str(mem), "--answers", ans, cwd=td)
            run("merge_memory", "--memory", str(mem), "--answers", ans, cwd=td)
            self.assertEqual(len(load_mem(td)["clarifications"]), 2)

    def test_check_shape_violation_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); bad = td / "bad.json"
            bad.write_text('{"version": 1, "clarifications": [{"fact_key": "x"}]}', encoding="utf-8")
            r = run("merge_memory", "--check", str(bad), cwd=td)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertFalse(json.loads(r.stdout)["ok"])

    def test_check_fact_key_conflict_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); bad = td / "bad.json"
            bad.write_text(json.dumps({"version": 1, "clarifications": [
                {"fact_key": "x", "value": "1", "source": "user-asserted"},
                {"fact_key": "x", "value": "2", "source": "user-asserted"}]}), encoding="utf-8")
            r = run("merge_memory", "--check", str(bad), cwd=td)
            self.assertEqual(r.returncode, 2, r.stderr)

    def test_check_ok_after_merge(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); mem = td / ".mgh-sra" / "business_context.json"
            run("merge_memory", "--memory", str(mem), "--answers",
                str(write_answers(td, {"x": "1"})), cwd=td)
            r = run("merge_memory", "--check", str(mem), cwd=td)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(json.loads(r.stdout)["ok"])

    def test_writes_under_project_subtree(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td); mem = td / ".mgh-sra" / "business_context.json"
            run("merge_memory", "--memory", str(mem), "--answers",
                str(write_answers(td, {"x": "1"})), cwd=td)
            self.assertTrue(mem.is_file())
            self.assertTrue(mem.resolve().is_relative_to(td.resolve()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
