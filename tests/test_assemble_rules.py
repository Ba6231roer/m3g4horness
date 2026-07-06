#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for assemble_rules.py: opencode assembly + purity lint (R5.7 closed loop).

Runs the script as a REAL subprocess from a NON-script cwd (FD2 family robustness —
also covers task 7.2: import/cwd self-containment). Run: py -3 tests/test_assemble_rules.py
"""
import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "assemble_rules.py"
PY = sys.executable  # real interpreter when launched via `py -3`


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestAssembleOpencode(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_asm_"))
        self.parts = self.target / ".mgh-init" / "rules-parts"
        self.agents = self.target / "AGENTS.md"
        self.cwd = self.target  # NON-script cwd (task 7.2)

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPT), "--target", str(self.target), *args],
                              cwd=str(self.cwd), capture_output=True, text=True, encoding="utf-8")

    def _seed(self):
        _write(self.parts / "audit-logging.md",
               "### 审计日志\n- **AuditFilter**: 登记每次请求。锚点: src/A.java::A.b\n")
        _write(self.parts / "authorization.md",
               "### 鉴权\n- **方法级安全**: @PreAuthorize。锚点: src/C.java::C.d\n")

    def test_assembles_single_neutral_block(self):
        self._seed()
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(body.count("<!-- security-controls:end -->"), 1)
        self.assertIn("## 安全设计 — 复用,勿重造", body)
        self.assertIn("### 审计日志", body)
        self.assertIn("### 鉴权", body)
        summ = json.loads(r.stdout)
        self.assertEqual(summ["categories"], ["audit-logging", "authorization"])
        self.assertEqual(summ["block"], "security-controls")
        self.assertTrue(summ["lint"]["ok"])

    def test_idempotent_two_runs_one_block(self):
        self._seed()
        self._run("--format", "opencode")
        self._run("--format", "opencode")
        body = self.agents.read_text(encoding="utf-8")
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(body.count("<!-- security-controls:end -->"), 1)

    def test_legacy_branded_block_migrated(self):
        _write(self.agents,
               "# Proj\n\n用户内容。\n\n"
               "<!-- mgh-init:begin:audit-logging -->\n### 旧\n- 旧内容\n"
               "<!-- mgh-init:end:audit-logging -->\n\n尾部。\n")
        self._seed()
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertNotIn("mgh-init:begin", body)          # legacy swept
        self.assertIn("用户内容。", body)                  # user content kept
        self.assertIn("尾部。", body)
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(json.loads(r.stdout)["migrated_legacy_blocks"], 1)

    def test_user_content_preserved_when_block_appended(self):
        _write(self.agents, "# My Proj\n\n一些手写说明。\n")
        self._seed()
        self._run("--format", "opencode")
        body = self.agents.read_text(encoding="utf-8")
        self.assertIn("# My Proj", body)
        self.assertIn("一些手写说明。", body)

    def test_check_fails_loud_on_leaked_script_name(self):
        _write(self.parts / "crypto.md",
               "### 加密\n- 由 discover_controls.py 发现。锚点: src/X.java::X.y\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 2)
        summ = json.loads(r.stdout)
        self.assertFalse(summ["lint"]["ok"])
        self.assertTrue(any(v["token"] == "discover_controls.py"
                            for v in summ["lint"]["violations"]))
        # and a non-check (write) run must NOT persist a polluted block
        r2 = self._run("--format", "opencode")
        self.assertEqual(r2.returncode, 2)
        body = self.agents.read_text(encoding="utf-8") if self.agents.exists() else ""
        self.assertNotIn("security-controls:begin", body)

    def test_bare_tier_token_not_flagged(self):
        _write(self.parts / "input-validation.md",
               "### 输入校验\n- **Sanitizer**: 复用。锚点: src/T1LineParser.java::T1LineParser.parse\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertTrue(json.loads(r.stdout)["lint"]["ok"])


class TestLintClaude(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_cl_"))

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPT), "--target", str(self.target), *args],
                              capture_output=True, text=True, encoding="utf-8")

    def test_claude_check_fails_on_leak(self):
        _write(self.target / ".claude" / "rules" / "security-crypto.md",
               "---\npaths: [\"src/**\"]\n---\n# 安全\n- 经 chunk_sources.py 切片发现。\n")
        r = self._run("--format", "claude", "--check")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["lint"]["ok"])

    def test_claude_check_clean(self):
        _write(self.target / ".claude" / "rules" / "security-crypto.md",
               "---\npaths: [\"src/**\"]\n---\n# 安全\n- **CipherUtil**: AES 封装。锚点: src/C.java::C.b\n")
        r = self._run("--format", "claude", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
