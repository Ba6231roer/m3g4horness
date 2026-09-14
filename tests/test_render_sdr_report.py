#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""render_sdr_report.py unit tests (add-mgh-sdr task 6.6).

Covers: report filename format (tool-branch-safe-second-ts), {dimension,route,file}
triple dedup-merge, .failed units do not block rendering + manifest counts, same-name
atomic overwrite idempotency, honesty-boundary >= 6 entries, NEVER writes openspec/,
--check consistency (+ mismatch exit 2).

Run: py tests/test_render_sdr_report.py
"""
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "render_sdr_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("render_sdr_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RenderSdrReportTest(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_sdrrender_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run_dir = self.repo / ".mgh-sdr" / "runs" / "t1"
        (self.run_dir / "markers").mkdir(parents=True)
        (self.run_dir / "drafts").mkdir(parents=True)
        (self.run_dir / "context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "baseline_truncated": False,
        }), encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _draft(self, uid, findings):
        (self.run_dir / "drafts" / f"{uid}.json").write_text(
            json.dumps({"unit": uid, "findings": findings}, ensure_ascii=False),
            encoding="utf-8")
        (self.run_dir / "markers" / f"{uid}.done").write_text("{}", encoding="utf-8")

    def _run(self, *args):
        sys.argv = ["render_sdr_report.py"] + list(args)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    F1 = {"dimension": "horizontal-authz", "severity": "high", "route": "/user/detail",
          "file": "UserController.java", "line_hint": "88-102", "risk": "r1",
          "suggestion": "s1", "control_ref": "横向越权规约"}
    F1_DUP = {"dimension": "horizontal-authz", "severity": "medium", "route": "/user/detail",
              "file": "UserController.java", "line_hint": "110", "risk": "dup",
              "suggestion": "-", "control_ref": None}
    F2 = {"dimension": "sql-injection", "severity": "high", "route": "/user/list",
          "file": "UserController.java", "line_hint": "40", "risk": "r2",
          "suggestion": "s2", "control_ref": None}

    def test_filename_format(self):
        self._draft("u1", [self.F1])
        code, out, err = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        name = Path(d["report"]).name
        self.assertRegex(name, r"^mgh-sdr-feature-pay-\d{8}_\d{6}\.md$")

    def test_dedup_merge_by_triple(self):
        self._draft("u1", [self.F1])
        self._draft("u2", [self.F1_DUP, self.F2])
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        d = json.loads(out)
        self.assertEqual(d["counts"]["findings"], 2)  # dup merged: 3 raw -> 2
        rep = Path(d["report"]).read_text(encoding="utf-8")
        self.assertIn("110", rep)  # line_hint unioned from the dup

    def test_failed_unit_does_not_block(self):
        self._draft("u1", [self.F1])
        (self.run_dir / "markers" / "u9.failed").write_text(
            json.dumps({"unit": "u9", "reason": "path-drift"}), encoding="utf-8")
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["counts"]["failed_units"], 1)
        manifest = json.loads((self.run_dir / "sdr_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["failed_units"][0]["unit"], "u9")
        rep = Path(d["report"]).read_text(encoding="utf-8")
        self.assertIn("1 个评审单元失败", rep)

    def test_unparsable_done_draft_counts_failed(self):
        self._draft("u1", [self.F1])
        (self.run_dir / "drafts" / "ubroken.json").write_text("{not json",
                                                              encoding="utf-8")
        (self.run_dir / "markers" / "ubroken.done").write_text("{}", encoding="utf-8")
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["counts"]["failed_units"], 1)

    def test_honesty_boundary_at_least_6(self):
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        manifest = json.loads((self.run_dir / "sdr_manifest.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest["boundaries"]), 6)

    def test_never_writes_openspec(self):
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertFalse((self.repo / "openspec").exists())

    def test_same_second_overwrite_idempotent(self):
        self._draft("u1", [self.F1])
        # pin datetime to ONE second, render twice -> same report name, atomic overwrite
        real = self.m.datetime

        class _Frozen(real):  # noqa: F821 — subclass of the real datetime
            @classmethod
            def now(cls, tz=None):
                return real(2026, 9, 3, 14, 30, 22).replace(
                    tzinfo=tz) if tz else real(2026, 9, 3, 14, 30, 22)

        try:
            self.m.datetime = _Frozen
            code1, out1, _ = self._run("--run-dir", str(self.run_dir),
                                       "--repo", str(self.repo))
            code2, out2, _ = self._run("--run-dir", str(self.run_dir),
                                       "--repo", str(self.repo))
        finally:
            self.m.datetime = real
        n1 = Path(json.loads(out1)["report"]).name
        n2 = Path(json.loads(out2)["report"]).name
        self.assertEqual(n1, n2)
        self.assertEqual(n1, "mgh-sdr-feature-pay-20260903_143022.md")
        self.assertFalse(list(self.repo.glob("*.tmp")), "tmp leftover on overwrite")

    def test_check_ok_and_mismatch(self):
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)
        # tamper with the manifest count -> --check exit 2
        mp = self.run_dir / "sdr_manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["counts"]["findings"] = 99
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("mismatch", err)

    def test_missing_run_dir_exits_1(self):
        code, _, _ = self._run("--run-dir", str(self.tmp / "nope"), "--repo",
                               str(self.repo))
        self.assertEqual(code, 1)

    # --- external-repo unapproved variant (add-mgh-sdr-read-root-config 3.2) ---
    def test_unapproved_boundary_and_head_variant(self):
        # declared-but-unauthorized skip: distinct from not-found — report head names
        # 未授权, honesty boundary carries the unapproved entry with the paths
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["unapproved: D:/xxx/front",
                                 "not-found: D:/xxx/gone"],
            "pending_approval": ["D:\\xxx\\front"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        self._draft("u1", [self.F1])
        code, out, err = self._run("--run-dir", str(self.run_dir),
                                   "--repo", str(self.repo))
        self.assertEqual(code, 0, err)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("外部仓未授权,前端相关检查面未覆盖", report)
        self.assertIn("未经用户确认写入项目配置", report)
        self.assertIn("D:/xxx/front", report)
        manifest = json.loads((self.run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        self.assertTrue(any("外部仓未授权" in b for b in manifest["boundaries"]))
        # not-found alone (no unapproved): head stays the unreachable variant
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["not-found: D:/xxx/gone"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("未声明 / 不可达降级", report)
        self.assertNotIn("外部仓未授权", report)

    def test_check_ok_with_unapproved_boundaries(self):
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["unapproved: D:/xxx/front"],
            "pending_approval": ["D:\\xxx\\front"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_grouping_overview_and_exclusion_disclosure(self):
        # grouping.json in the run dir -> 分组概览 section (unit counts + codegraph
        # stats) + honesty-boundary entry ⑦ (exclusion-set disclosure w/ per-reason
        # counts); manifest counts.excluded_files passes through.
        (self.run_dir / "grouping.json").write_text(json.dumps({
            "repo": str(self.repo), "base": "master", "branch": "feature-pay",
            "empty": False, "codegraph": True, "total": 3,
            "counts": {"interface": 2, "standalone": 1},
            "excluded": {"count": 120, "by_reason": {"test-tree": 80,
                                                     "build-output": 30,
                                                     "static-asset": 10}},
            "codegraph_stats": {"symbols_queried": 9, "edges_captured": 25,
                                "edges_in_changed_set": 12, "anchors_changed": 2,
                                "anchors_upstream": 8, "chain_merged": 1,
                                "excluded_files": 120},
            "pending": [],
        }, ensure_ascii=False), encoding="utf-8")
        self._draft("u1", [self.F1])
        code, out, err = self._run("--run-dir", str(self.run_dir),
                                   "--repo", str(self.repo))
        self.assertEqual(code, 0, err)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("分组概览", report)
        self.assertIn("interface 2 / standalone 1", report)
        self.assertIn("向上锚定 8", report)
        self.assertIn("排除文件:120 个", report)
        self.assertIn("排除集披露", report)
        self.assertIn("test-tree 80", report)
        m = json.loads((self.run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(m["counts"]["excluded_files"], 120)
        # --check still passes with the extended boundaries/counts
        code, _, cerr = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, cerr)

    def test_no_grouping_json_renders_without_overview(self):
        # older run layout: no grouping.json -> no overview section, boundaries >= 6
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertNotIn("分组概览", report)
        self.assertIn("诚实边界", report)

    # --- new report structure (improve-mgh-sdr-report-structure group 3) ---

    CHAIN_A = [
        {"fqn_short": "OrderController.submit", "label": "OrderController.submit",
         "file": "OrderController.java", "line": 42, "change": "changed",
         "route": "/order/submit"},
        {"fqn_short": "OrderServiceImpl.submit", "label": "OrderServiceImpl.submit",
         "file": "OrderServiceImpl.java", "line": 60, "change": "changed"},
        {"fqn_short": "OrderDao.insertOrder", "label": "OrderDao.insertOrder",
         "file": "OrderDao.java", "line": 30, "change": "changed"},
        {"fqn_short": "OrderDaoMapper.xml", "label": "OrderDaoMapper.xml:insertOrder",
         "file": "resources/mapper/OrderDaoMapper.xml", "line": None, "change": "external",
         "branch_of": 2},
    ]
    CHAIN_B = [
        {"fqn_short": "UserController.list", "label": "UserController.list",
         "file": "UserController.java", "line": 12, "change": "unchanged",
         "route": "/user/list"},
        {"fqn_short": "UserService.queryUser", "label": "UserService.queryUser",
         "file": "UserService.java", "line": 80, "change": "changed"},
        {"fqn_short": "LogDao.insertLog", "label": "LogDao.insertLog",
         "file": "LogDao.java", "line": 20, "change": "changed"},
        {"fqn_short": "UserDao.findById", "label": "UserDao.findById",
         "file": "UserDao.java", "line": 25, "change": "changed", "branch_of": 1},
    ]

    def _grouping(self, units):
        (self.run_dir / "grouping.json").write_text(json.dumps({
            "repo": str(self.repo), "base": "master", "branch": "feature-pay",
            "empty": False, "codegraph": True, "total": len(units),
            "counts": {"interface": sum(1 for u in units if u["kind"] == "interface"),
                       "standalone": sum(1 for u in units if u["kind"] == "standalone")},
            "excluded": {"count": 0, "by_reason": {}},
            "codegraph_stats": {"anchors_changed": 1, "anchors_upstream": 1,
                                "chain_merged": 0, "edges_captured": 5,
                                "edges_in_changed_set": 3},
            "units": units,
            "pending": [],
        }, ensure_ascii=False), encoding="utf-8")

    def test_summary_table_structure_and_sort(self):
        # 2 interface units (routes /order/submit + /user/list) + 1 standalone:
        # rows sorted interface-by-route then standalone; chain text uses the
        # abbreviations; failed unit never becomes a row
        self._grouping([
            {"unit_id": "UserController_list", "kind": "interface",
             "route": "/user/list", "chain": self.CHAIN_B, "status": "done"},
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
            {"unit_id": "utils_Helper", "kind": "standalone", "route": "",
             "chain": [], "status": "done"},
            {"unit_id": "broken_Unit", "kind": "interface", "route": "/aaa/broken",
             "chain": [], "status": "failed"},
        ])
        self._draft("OrderController_submit", [{
            "dimension": "vertical-authz", "severity": "high", "route": "/order/submit",
            "file": "OrderController.java", "line_hint": "40-50", "line": 42,
            "risk": "无权限校验", "suggestion": "补权限注解", "control_ref": None}])
        self._draft("UserController_list", [{
            "dimension": "sql-injection", "severity": "medium", "route": "/user/list",
            "file": "UserDao.java", "line_hint": "20-30", "risk": "拼接SQL",
            "suggestion": "改#{}", "control_ref": "SQL规约"}])
        code, out, err = self._run("--run-dir", str(self.run_dir),
                                   "--repo", str(self.repo))
        self.assertEqual(code, 0, err)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("## 章节一 简报表", report)
        # sorted: /order/submit before /user/list, standalone LAST
        i_order = report.index("POST") if "POST" in report else report.index("/order/submit")
        i_user = report.index("/user/list")
        i_standalone = report.index("utils_Helper")
        self.assertLess(i_order, i_user)
        self.assertGreater(i_standalone, i_user)
        # failed unit absent from rows
        self.assertNotIn("broken_Unit |", report)
        # chain abbreviations: † unchanged entry + mapper terminal + branch
        self.assertIn("†UserController.list", report)
        self.assertIn("⇢", report)
        self.assertIn("⤷", report)
        # dimension cells reference P-NN pure text
        self.assertIn("是 [P-01]", report)
        self.assertNotIn("<a id=", report)
        self.assertNotIn("{#", report)
        self.assertNotIn("](#", report)

    def test_frontend_two_columns_three_states(self):
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template",
            "external_repos": [{"slug": "front", "path": "D:/f",
                                "route_hits": [{"route": "/order/submit", "count": 2},
                                               {"route": "/user/list", "count": 0}]}],
            "baseline_truncated": False,
        }), encoding="utf-8")
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
            {"unit_id": "UserController_list", "kind": "interface",
             "route": "/user/list", "chain": self.CHAIN_B, "status": "done"},
            {"unit_id": "OrderController_batch", "kind": "interface",
             "route": "/order/batch", "chain": [], "status": "done"},
            # merged multi-route unit: join on the MAIN route (first segment) only
            {"unit_id": "OrderController_merged", "kind": "interface",
             "route": "/order/batch;/order/submit", "chain": [], "status": "done"},
        ])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("| 是 | 2 处 |", report)      # /order/submit declared, 2 hits
        self.assertIn("| 否 | — |", report)         # /user/list declared, 0 hits
        self.assertIn("| 未知 | — |", report)       # /order/batch undeclared
        # merged unit's main route /order/batch is undeclared => 未知 despite the
        # secondary segment /order/submit having hits
        self.assertIn("| /order/batch(+1) | ", report)
        m = json.loads((self.run_dir / "sdr_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(m["rows"]), 4)
        by_entry = {r["entry"]: r for r in m["rows"]}
        self.assertEqual(by_entry["/order/submit"]["frontend_is"], "是")
        self.assertEqual(by_entry["/user/list"]["frontend_count"], "—")
        self.assertEqual(by_entry["/order/batch"]["frontend_is"], "未知")

    def test_mermaid_only_for_branch_units(self):
        # direct-dao linear chain whose ONLY branch_of is its ⇢ mapper terminal:
        # D3 encodes the terminal hop as branch_of, but that is not a 真实分支 —
        # the unit stays linear and draws NO diagram.
        LINEAR_DIRECT = self.CHAIN_A
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_B, "status": "done"},
            {"unit_id": "UserCacheController_direct", "kind": "interface",
             "route": "/cache/user/direct", "chain": LINEAR_DIRECT, "status": "done"},
            {"unit_id": "UserController_list", "kind": "interface",
             "route": "/user/list", "chain": [
                 {"fqn_short": "UserController.list",
                  "label": "UserController.list", "file": "UserController.java",
                  "line": 12, "change": "changed", "route": "/user/list"},
                 {"fqn_short": "UserService.queryUser",
                  "label": "UserService.queryUser", "file": "UserService.java",
                  "line": 80, "change": "changed"}], "status": "done"},
        ])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("flowchart LR", report)
        self.assertIn("#### OrderController_submit · /order/submit", report)
        # linear units (incl. ⇢-terminal-only): no mermaid heading
        self.assertNotIn("#### UserController_list", report)
        self.assertNotIn("#### UserCacheController_direct", report)
        self.assertEqual(report.count("```mermaid"), 1)

    def test_detail_section_line_and_degrade(self):
        # draft WITH line -> file:line; draft WITHOUT line -> file(hint) degrade
        self._grouping([
            {"unit_id": "u1", "kind": "interface", "route": "/order/submit",
             "chain": [], "status": "done"},
        ])
        self._draft("u1", [{
            "dimension": "input-validation", "severity": "low", "route": "/order/submit",
            "file": "OrderVO.java", "line_hint": "9-14", "line": 11, "risk": "r",
            "suggestion": "s", "control_ref": None}, {
            "dimension": "sensitive-data", "severity": "info", "route": "/order/submit",
            "file": "OldVO.java", "line_hint": "3-5", "risk": "r2",
            "suggestion": "s2", "control_ref": "掩码规约"}])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        self.assertIn("### P-01 · 输入校验 · /order/submit · 低", report)
        self.assertIn("`OrderVO.java`:11", report)
        self.assertIn("`OldVO.java`(3-5)", report)   # no line -> file(hint)

    def test_rows_projection_consistency_and_check(self):
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
        ])
        self._draft("OrderController_submit", [{
            "dimension": "vertical-authz", "severity": "high", "route": "/order/submit",
            "file": "OrderController.java", "line_hint": "42", "line": 42, "risk": "r",
            "suggestion": "s", "control_ref": None}])
        code, out, _ = self._run("--run-dir", str(self.run_dir),
                                 "--repo", str(self.repo))
        self.assertEqual(code, 0)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)
        # tamper: drop one row -> rows length != table rows -> exit 2
        mp = self.run_dir / "sdr_manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["rows"] = []
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("rows length", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
