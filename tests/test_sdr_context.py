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
    def _make_front(self, reachable=True, configured=True, name="front"):
        """Create a declared external repo. configured=False leaves the project config
        untouched => the authorization gate must skip it (zero reads)."""
        front = self.tmp / name
        decl_path = front.as_posix() if reachable else (self.tmp / f"gone_{name}").as_posix()
        (self.repo / "docs" / "security-controls").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "security-controls" / f"ext-{name}.md").write_text(
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
        if configured:
            self._approve(front)
        return front

    def _approve(self, *roots):
        """Write the project read-roots config (what read_roots_config.py produces)."""
        cfg = self.repo / ".mgh" / "read-roots.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if cfg.is_file():
            existing = json.loads(cfg.read_text(encoding="utf-8")).get("read_roots", [])
        for r in roots:
            if str(r) not in existing:
                existing.append(str(r))
        cfg.write_text(json.dumps({"v": 1, "read_roots": existing}, ensure_ascii=False),
                       encoding="utf-8")

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
        self.assertEqual(d["pending_approval"], [])

    # --- authorization gate (add-mgh-sdr-read-root-config 2.1) ---
    def test_unapproved_declaration_skipped_and_pending(self):
        front = self._make_front(reachable=True, configured=False)
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["external_repos"], [])          # zero retrieval
        self.assertFalse((self.run_dir / "external").exists())   # ZERO reads
        self.assertTrue(any(s.startswith(f"unapproved: ")
                            and str(front) in s for s in d["external_skipped"]))
        self.assertEqual(d["pending_approval"], [str(front)])
        ctx = json.loads((self.run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx["pending_approval"], [str(front)])

    def test_mixed_declarations_one_configured_one_not(self):
        front = self._make_front(reachable=True, configured=True)
        front2 = self._make_front(reachable=True, configured=False, name="front2")
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual([e["path"] for e in d["external_repos"]], [str(front)])
        self.assertEqual(d["pending_approval"], [str(front2)])
        self.assertTrue(any("unapproved" in s and str(front2) in s
                            for s in d["external_skipped"]))

    def test_check_pending_shape_violation(self):
        self._make_front(reachable=True, configured=False)
        self._run(*self._base_args())
        ctx_path = self.run_dir / "context.json"
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        ctx["pending_approval"] = "not-a-list"
        ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("pending_approval", err)

    def test_check_skip_pending_consistency(self):
        # unapproved skip WITHOUT its pending_approval counterpart => --check exit 2
        self._make_front(reachable=True, configured=False)
        self._run(*self._base_args())
        ctx_path = self.run_dir / "context.json"
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        ctx["pending_approval"] = []
        ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("missing from pending_approval", err)

    # --- @RequestMapping family + class base-route join (improve-mgh-sdr-report-structure 2.1) ---
    def test_new_routes_requestmapping_family_and_base_route(self):
        _git(self.repo, "checkout", "-q", "master")
        _git(self.repo, "checkout", "-qb", "feat-rm")
        src = self.repo / "src"
        src.mkdir(parents=True, exist_ok=True)
        (src / "OrderController.java").write_text(
            '@RestController\n'
            '@RequestMapping("/order")\n'
            'public class OrderController {\n'
            '    @PostMapping("/submit")\n'
            '    public String submit() { return "ok"; }\n'
            '\n'
            '    @RequestMapping("/list")\n'
            '    public String list() { return "ok"; }\n'
            '}\n', encoding="utf-8")
        (src / "QController.java").write_text(
            '@RestController\n'
            'public class QController {\n'
            '    @RequestMapping("/q")\n'
            '    public String q() { return "ok"; }\n'
            '}\n', encoding="utf-8")
        _commit_all(self.repo, "rm")
        routes = self.m._new_routes(self.repo, "master", "feat-rm")
        # @PostMapping joined with class base; method-level @RequestMapping WITH class
        # context joins the base too; one without a base route stays as-is
        self.assertEqual(routes, ["/order/list", "/order/submit", "/q"])

    # --- route_hits[] materialization (improve-mgh-sdr-report-structure 2.2) ---
    def test_route_hits_materialized_in_record_and_context(self):
        self._make_front(reachable=True)
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        rec = d["external_repos"][0]
        self.assertEqual(rec["route_hits"], [{"route": "/pay/quick", "count": 1}])
        ctx = json.loads((self.run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx["external_repos"][0]["route_hits"],
                         [{"route": "/pay/quick", "count": 1}])
        # hits.md text still carries the per-route count section
        self.assertIn("出现计数", Path(rec["summary_path"]).read_text(encoding="utf-8"))

    def test_route_hits_absent_without_routes(self):
        # no java diff between base and branch -> no routes -> route_hits == []
        _git(self.repo, "checkout", "-qb", "feat-empty")
        (self.repo / "notes.txt").write_text("no java changes\n", encoding="utf-8")
        _commit_all(self.repo, "txt")
        code, out, err = self._run(*self._base_args())
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["external_repos"], [])   # no declaration in this fixture
        for rec in d["external_repos"]:
            self.assertEqual(rec["route_hits"], [])

    # --- --check route_hits[] shape (improve-mgh-sdr-report-structure 2.3) ---
    def test_check_route_hits_shape_violation(self):
        self._make_front(reachable=True)
        self._run(*self._base_args())
        ctx_path = self.run_dir / "context.json"
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        ctx["external_repos"][0]["route_hits"] = [{"route": "/pay/quick"}]  # count missing
        ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("route_hits", err)

    def test_check_old_context_without_route_hits_ok(self):
        self._make_front(reachable=True)
        self._run(*self._base_args())
        ctx_path = self.run_dir / "context.json"
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        for e in ctx["external_repos"]:
            e.pop("route_hits", None)               # incremental field: absence = OK
        ctx_path.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

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
