#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sdr_context.py unit tests (add-mgh-sdr task 6.5).

Covers: baseline projection + priority truncation disclosure; external-repo declaration
hit -> conclusion files (buttonAuth.properties hit + route occurrence count);
unreachable-declaration degradation; sensitive-catalog resolution (default-template
fallback + project reuse + illegal project catalog early-stop exit 2); --dimensions
closed-set misuse gate; --check.

Run: py tests/test_sdr_context.py
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "sdr_context.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _commit_all(repo: Path, msg: str):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def _load():
    spec = importlib.util.spec_from_file_location("sdr_context", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SdrContextTest(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_sdrctx_"))
        self.repo = self.tmp / "repo"
        _init_repo(self.repo)
        (self.repo / "AGENTS.md").write_text(
            "# 项目\n## 安全设计\n- 横向越权:查询须带 brch_no + UserInfo 校验。\n"
            "- SQL 注入:MyBatis 一律 #{} 预编译。\n",
            encoding="utf-8")
        _commit_all(self.repo, "init")
        _git(self.repo, "checkout", "-qb", "feature-pay")
        (self.repo / "src").mkdir(exist_ok=True)
        (self.repo / "src" / "PayController.java").write_text(
            '@RestController\npublic class PayController {\n'
            '    @PostMapping("/pay/quick")\n    public String q() { return "ok"; }\n}\n',
            encoding="utf-8")
        _commit_all(self.repo, "feat")
        self.run_dir = self.repo / ".mgh-sdr" / "runs" / "t1"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args, stdin_text=None):
        old = sys.stdin
        sys.stdin = io.StringIO(stdin_text or "")
        try:
            sys.argv = ["sdr_context.py"] + list(args)
            out, err = io.StringIO(), io.StringIO()
            code = None
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = self.m.main()
                except SystemExit as e:
                    code = e.code
            return code, out.getvalue(), err.getvalue()
        finally:
            sys.stdin = old

    def _base_args(self):
        return ["--repo", str(self.repo), "--run-dir", str(self.run_dir),
                "--base", "master", "--branch", "feature-pay"]

    # --- baseline projection ---
    def test_baseline_projected(self):
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertFalse(d["baseline_truncated"])
        text = Path(d["baseline_path"]).read_text(encoding="utf-8")
        self.assertIn("横向越权", text)
        self.assertIn("SQL", text)

    def test_baseline_truncation_disclosed(self):
        # huge controls file + tiny budget -> truncated:true + truncated bytes > 0
        ctl = self.repo / "docs" / "security-controls"
        ctl.mkdir(parents=True, exist_ok=True)
        (ctl / "big.md").write_text("## 安全设计\n" + ("权限与校验细节行\n" * 500),
                                    encoding="utf-8")
        _commit_all(self.repo, "ctl")
        code, out, _ = self._run(*self._base_args(), "--baseline-budget-bytes", "512")
        d = json.loads(out)
        self.assertTrue(d["baseline_truncated"])
        self.assertGreater(d["baseline_truncated_bytes"], 0)

    # --- external repo retrieval ---
    def _make_front(self, reachable=True):
        front = self.tmp / ("front" if reachable else "gone_front")
        decl_path = front.as_posix() if reachable else (self.tmp / "gone_front").as_posix()
        (self.repo / "docs" / "security-controls").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "security-controls" / "ext.md").write_text(
            f"本地前端项目地址 {decl_path},前端分支名与本项目一致;\n"
            f"垂直越权以 buttonAuth.properties 配置为准,接口不应在前端多处出现。\n",
            encoding="utf-8")
        if not reachable:
            return None
        _init_repo(front)
        (front / "config").mkdir()
        (front / "config" / "buttonAuth.properties").write_text("x=1\n", encoding="utf-8")
        (front / "src").mkdir()
        (front / "src" / "pay.vue").write_text("axios.post('/pay/quick')\n",
                                               encoding="utf-8")
        _commit_all(front, "init")
        _git(front, "checkout", "-qb", "feature-pay")
        (front / "config" / "buttonAuth.properties").write_text(
            "pay/quick=allow,roleA\n", encoding="utf-8")
        _commit_all(front, "branch")
        return front

    def test_external_declaration_hit_materializes_conclusions(self):
        front = self._make_front(reachable=True)
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(len(d["external_repos"]), 1)
        rec = d["external_repos"][0]
        self.assertEqual(rec["path"], str(front))
        self.assertFalse(rec["branch_fallback"])
        hits = Path(rec["summary_path"]).read_text(encoding="utf-8")
        self.assertIn("buttonAuth.properties", hits)
        self.assertIn("pay/quick", hits)
        self.assertIn("pay.vue", hits)           # route occurrence in the frontend
        self.assertEqual(d["external_skipped"], [])

    def test_unreachable_declaration_degrades(self):
        self._make_front(reachable=False)
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["external_repos"], [])
        self.assertTrue(any("not-found" in s for s in d["external_skipped"]))

    # --- sensitive catalog ---
    def test_default_template_fallback(self):
        code, out, _ = self._run(*self._base_args())
        d = json.loads(out)
        self.assertEqual(d["sensitive_catalog_source"], "default-template")
        self.assertEqual(d["sensitive_catalog"]["counts"]["items"], 37)

    def test_project_catalog_reused(self):
        sra = self.repo / ".mgh-sra"
        sra.mkdir(parents=True, exist_ok=True)
        (sra / "sensitive_catalog.json").write_text(json.dumps({
            "version": 1,
            "items": {"financial/card-no": {"label": "银行卡卡号", "mask": "partial",
                                            "rule": "保留后4位"}},
        }), encoding="utf-8")
        code, out, _ = self._run(*self._base_args())
        d = json.loads(out)
        self.assertEqual(d["sensitive_catalog_source"], "project")
        self.assertEqual(d["sensitive_catalog"]["counts"]["items"], 1)

    def test_illegal_project_catalog_exits_2(self):
        sra = self.repo / ".mgh-sra"
        sra.mkdir(parents=True, exist_ok=True)
        (sra / "sensitive_catalog.json").write_text(json.dumps({
            "version": 1,
            "items": {"bogus-cat/x": {"label": "x", "mask": "full", "rule": None}},
        }), encoding="utf-8")
        code, _, err = self._run(*self._base_args())
        self.assertEqual(code, 2)
        self.assertIn("unknown category", err)

    # --- dimensions gate ---
    def test_illegal_dimensions_key_exits_2(self):
        code, _, err = self._run(*self._base_args(),
                                 "--dimensions", '{"dimensions":["crypto audit!"]}')
        self.assertEqual(code, 2)
        self.assertIn("illegal", err.lower())

    def test_valid_dimensions_pass(self):
        code, out, _ = self._run(*self._base_args(),
                                 "--dimensions", '{"dimensions":["sql-injection"]}')
        self.assertEqual(code, 0)

    # --- --check ---
    def test_check_ok(self):
        self._run(*self._base_args())
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_check_missing_run_dir_exits_2(self):
        code, _, _ = self._run("--check", str(self.tmp / "nope"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
