#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.00
"""Regression tests for tools/audit_init_run.py (synthetic finished run).

Builds a miniature but complete .mgh-init tree in a temp dir, runs the audit
tool as a subprocess, and asserts the hand-copy stdout numbers + detail JSON.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "audit_init_run.py"


def _w(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class AuditInitRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_audit_"))
        self.target = self.tmp / "repo"
        self.init = self.target / ".mgh-init"
        # source file: 6 lines, class Foo with method bar (line 4)
        _w(self.target / "src/Foo.java",
           "package x;\npublic class Foo {\n  // line3\n  public String bar() {\n"
           "    return sanitize(input);\n  }\n}\n")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _build_run(self):
        cp = self.init / "checkpoints"
        # t1: good record + done; bad json + done; orphan marker whose sha8 tail
        # appears inside the good record (pack-member shape, sanitized names)
        _w(cp / "t1/alpha.json", json.dumps(
            {"unit": "input-validation::Foo::src/Foo.java::deadbeef",
             "members": [], "evidence": ["src/Foo.java:Foo.bar"]}))
        (cp / "t1/alpha.json.done").touch()
        _w(cp / "t1/beta.json", "{not valid json")
        (cp / "t1/beta.json.done").touch()
        _w(cp / "t1/input-validation__X__src_Foo_java__deadbeef.json.done", "")
        # t2: shard record NESTED one level (regression for recursion) + the
        # marker-only synthesis marker (absent content file is by design)
        _w(cp / "t2/parts/part-1.json", json.dumps({"summary": "ok"}))
        (cp / "t2/parts/part-1.json.done").touch()
        _w(cp / "t2/synthesis.json.done", "")
        # t3: one category record + one artifact-attached marker (base NOT
        # .json — native rule-file marker shape -> orphan_other, not missing)
        _w(cp / "t3/input-validation.json", json.dumps({"category": "input-validation"}))
        (cp / "t3/input-validation.json.done").touch()
        _w(cp / "t3/input-validation.opencode.md.done", "")
        # t4: consistency record + marker
        _w(cp / "t4/consistency.json", json.dumps({"changes": [], "flags": []}))
        (cp / "t4/consistency.json.done").touch()
        # inventory: 2 controls — single-colon symbol evidence (T1 contract
        # format) and a missing-file anchor
        _w(self.init / "controls_inventory.json", json.dumps({
            "controls": [
                {"name": "Foo sanitizer", "category": "input-validation",
                 "evidence": ["src/Foo.java:Foo.bar"]},
                {"name": "Ghost limiter", "category": "rate-limiting",
                 "evidence": ["src/Missing.java:5"]},
            ]}))
        # rules: only input-validation exists (rate-limiting file missing)
        _w(self.target / "docs/security-controls/input-validation.md",
           "# 输入校验 安全控制\n\n- 复用 `src/Foo.java::Foo.bar` 的净化逻辑。\n")
        _w(self.target / "AGENTS.md",
           "<!-- security-controls:begin -->\n"
           "- 输入校验 → @docs/security-controls/input-validation.md\n"
           "<!-- security-controls:end -->\n")
        # health artifacts
        _w(self.init / "init_manifest.json", json.dumps(
            {"boundaries": ["b1", "b2"],
             "failures": {"t1": {"done": 2, "failed": 0, "total": 2}}}))
        _w(self.init / "report.md", "# 报告\n边界披露样例\n")
        _w(self.init / "run_config.json", json.dumps({"format": "opencode"}))

    def _run(self, *extra):
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--target", str(self.target)] + list(extra),
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        return proc

    def _stdout_map(self, proc):
        """Line label -> '{label}:{key}' to keep cross-line keys distinct."""
        out = {}
        for ln in proc.stdout.splitlines():
            toks = ln.split()
            if not toks or "=" in toks[0]:
                continue
            label = toks[0]
            for tok in toks[1:]:
                if "=" in tok:
                    k, v = tok.split("=", 1)
                    out["%s:%s" % (label, k)] = v
        return out

    def test_full_synthetic_run(self):
        self._build_run()
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._stdout_map(proc)
        # markers: only tiers with a checkpoints dir appear; scout absent here
        self.assertNotIn("markers:scout", m)
        self.assertEqual(m["markers:t1"], "3/0")
        self.assertEqual(m["markers:t2"], "2/0")
        self.assertEqual(m["markers:t3"], "2/0")
        # records: t1=2; t2=1 via ONE-LEVEL RECURSION (parts/part-1.json);
        # files_total includes markers themselves
        self.assertEqual(m["records:t1"], "2(files=5)")
        self.assertEqual(m["records:t2"], "1(files=3)")
        self.assertEqual(m["json_bad:total"], "1")
        self.assertEqual(m["json_bad:t1"], "1")
        # orphan json marker (sanitized name) matches record content via sha8
        self.assertEqual(m["orphan_json:t1"], "1(sha_hit=1)")
        self.assertEqual(m["orphan_json:rec_no_total"], "0")
        # non-json marker base → artifact-attached (native design), not a
        # missing record
        self.assertEqual(m["orphan_json:other_marker"], "1")
        # synthesis.json content absent by design, not an orphan
        self.assertEqual(m["t2:synthesis"], "absent")
        self.assertEqual(m["t2:shards"], "1")
        self.assertEqual(m["t4:consistency"], "ok")
        self.assertEqual(m["t4:post_t4_lint"], "skipped")
        # anchors: inv[0] single-colon symbol evidence ok (parses to path +
        # symbol, file + class + method all present); inv[1] file missing;
        # rule-file :: anchor ok → total=3 ok=2 bad_file=1
        self.assertEqual(m["anchors:total"], "3")
        self.assertEqual(m["anchors:ok"], "2")
        self.assertEqual(m["anchors:bad_file"], "1")
        self.assertEqual(m["anchors:bad_symbol"], "0")
        self.assertEqual(m["inv:controls"], "2")
        self.assertEqual(m["inv:cats"], "2")
        self.assertEqual(m["inv:files"], "1")
        self.assertEqual(m["inv:missing_files"], "1")
        # control 1 represented (its evidence PATH appears in rule text after
        # single-colon parsing strips the symbol), control 2 missing
        self.assertEqual(m["cover:represented"], "1")
        self.assertEqual(m["cover:missing"], "1")
        self.assertEqual(m["index:links"], "1")
        self.assertEqual(m["index:files"], "1")
        self.assertEqual(m["manifest:boundaries"], "2")
        self.assertEqual(m["manifest:failures"], "0")
        self.assertEqual(m["manifest:cfg_scout"], "on")
        detail_path = self.init / "audit_report.json"
        self.assertTrue(detail_path.is_file())
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        self.assertEqual(detail["reconciliation"]["missing_files"], ["rate-limiting"])
        self.assertEqual(detail["reconciliation"]["missing_controls"][0]["name"],
                         "Ghost limiter")

    def test_bad_json_line_and_symbol(self):
        self._build_run()
        # make the rule anchor point at an absent method (symbol drift) and the
        # inventory line anchor out of range
        _w(self.target / "docs/security-controls/input-validation.md",
           "# 输入校验 安全控制\n\n- 复用 `src/Foo.java::Foo.nope`。\n")
        _w(self.init / "controls_inventory.json", json.dumps({
            "controls": [
                {"name": "Foo sanitizer", "category": "input-validation",
                 "evidence": ["src/Foo.java:999"]},
                {"name": "Ghost limiter", "category": "rate-limiting",
                 "evidence": ["src/Foo.java:2"]},
            ]}))
        proc = self._run()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        m = self._stdout_map(proc)
        self.assertEqual(m["anchors:total"], "3")
        self.assertEqual(m["anchors:ok"], "1")
        self.assertEqual(m["anchors:bad_line"], "1")
        self.assertEqual(m["anchors:bad_symbol"], "1")

    def test_usage_error_exit_2(self):
        proc = self._run()
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
