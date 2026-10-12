#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""render_sdr_report.py unit tests (improve-mgh-sdr-report-html-render task 5.1).

The renderer emits three artifacts per run: the self-contained single-file HTML report
at the repo root, `<run-dir>/sdr_report_data.json` (canonical data), and
`sdr_manifest.json`. Assertions are stdlib-only: JSON equality on the two data
carriers, text-level structure markers on the HTML, and `html.parser` where a DOM
shape matters. No browser is launched (the real-browser acceptance pass is the tasks'
manual item).

Covers: .html filename format, data-file <-> embedded-block JSON equivalence, {dimension,
route, file} triple dedup-merge, .failed units do not block rendering + manifest counts,
same-second atomic overwrite idempotency, honesty-boundary entries, self-containment
(no external references; the w3c SVG namespace identifier is a name, not a fetch),
injection escaping (`</script>` inside finding text), P-NN numbering/anchors data, SVG
graph data (branched units only, dashed mapper terminals, † prefix, linear chains
excluded), frontend three-state join, source-link href rules + degradation, manifest
rows[] == data rows[], and --check (ok / counts mismatch / carrier drift / rows drift /
missing markers / non-html report).

Run: py tests/test_render_sdr_report.py
"""
import contextlib
import io
import json
import os
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


def _embed(mod, html_text):
    """The parsed embedded data block (the HTML's single per-run payload)."""
    m = re.search(r'<script type="application/json" id="mgh-data">(.*?)</script>',
                  html_text, re.S)
    assert m, "no embedded data block in HTML"
    return json.loads(m.group(1))


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

    def _render(self):
        code, out, err = self._run("--run-dir", str(self.run_dir),
                                   "--repo", str(self.repo))
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        report = Path(payload["report"]).read_text(encoding="utf-8")
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((self.run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        return payload, report, data, manifest

    F1 = {"dimension": "horizontal-authz", "severity": "high", "route": "/user/detail",
          "file": "UserController.java", "line_hint": "88-102", "risk": "r1",
          "suggestion": "s1", "control_ref": "横向越权规约"}
    F1_DUP = {"dimension": "horizontal-authz", "severity": "medium", "route": "/user/detail",
              "file": "UserController.java", "line_hint": "110", "risk": "dup",
              "suggestion": "-", "control_ref": None}
    F2 = {"dimension": "sql-injection", "severity": "high", "route": "/user/list",
          "file": "UserController.java", "line_hint": "40", "risk": "r2",
          "suggestion": "s2", "control_ref": None}

    # --- 1.2/2.3 report + data carriers -----------------------------------------

    def test_filename_format_and_data_file(self):
        self._draft("u1", [self.F1])
        payload, report, data, manifest = self._render()
        name = Path(payload["report"]).name
        self.assertRegex(name, r"^mgh-sdr-feature-pay-\d{8}_\d{6}\.html$")
        # canonical data file sits beside the manifest, same dict projected into both
        self.assertEqual(Path(payload["data"]).parent, self.run_dir)
        self.assertEqual(data["rows"], manifest["rows"])
        self.assertEqual(data["meta"]["findings_total"],
                         manifest["counts"]["findings"])

    def test_embed_block_equals_data_file(self):
        self._draft("u1", [self.F1])
        _, report, data, _ = self._render()
        self.assertEqual(_embed(self.m, report), data)

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
        self.assertEqual(n1, "mgh-sdr-feature-pay-20260903_143022.html")
        self.assertFalse(list(self.repo.glob("*.tmp")), "tmp leftover on overwrite")
        self.assertFalse(list(self.run_dir.glob("*.tmp")), "tmp leftover in run dir")
        # the second render's carriers are complete (data rewritten, not appended)
        self.assertEqual(_embed(self.m, Path(n2 and (self.repo / n2)).read_text(
            encoding="utf-8")),
            json.loads((self.run_dir / "sdr_report_data.json").read_text(
                encoding="utf-8")))

    def test_never_writes_openspec(self):
        self._draft("u1", [self.F1])
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertFalse((self.repo / "openspec").exists())

    def test_self_contained_no_external_references(self):
        self._draft("u1", [self.F1])
        _, report, _, _ = self._render()
        # the w3c SVG namespace is an XML namespace IDENTIFIER, never fetched — the only
        # allowed http:// occurrence; everything else must be inline
        stripped = report.replace("http://www.w3.org/2000/svg", "")
        self.assertNotIn("http://", stripped)
        self.assertNotIn("https://", stripped)
        for pat in (r"<script\s+src=", r"<link\s", r"@import", r"<img\s",
                    r"<iframe\s", r"url\("):
            self.assertIsNone(re.search(pat, report, re.I),
                              f"external-reference pattern {pat!r} in report")
        # structure markers the in-page navigation and --check rely on
        for marker in ('id="mgh-data"', 'id="sec-overview"', 'id="sec-summary"',
                       'id="sec-findings"', 'id="sec-graphs"', 'id="sec-ok-units"',
                       'id="sec-boundaries"'):
            self.assertIn(marker, report)
        self.assertIn("escapeHtml", report)          # the single escaping entry exists
        self.assertIn("诚实边界", report)

    def test_injection_escaping_in_embed_block(self):
        self._draft("u1", [dict(self.F1, risk='<script>alert(1)</script> "q" & <b>')])
        _, report, data, _ = self._render()
        # `</` inside the data became `<\/` (legal JSON escape, parse-identical), so the
        # block cannot be terminated by finding text; the embed still parses to the data
        self.assertIn("<\\/script>", report)
        self.assertEqual(_embed(self.m, report), data)
        self.assertEqual(data["findings"][0]["risk"],
                         '<script>alert(1)</script> "q" & <b>')

    # --- merge / failed units / boundaries --------------------------------------

    def test_dedup_merge_by_triple(self):
        self._draft("u1", [self.F1])
        self._draft("u2", [self.F1_DUP, self.F2])
        _, _, data, manifest = self._render()
        self.assertEqual(manifest["counts"]["findings"], 2)  # dup merged: 3 raw -> 2
        self.assertEqual(len(data["findings"]), 2)
        f1 = next(f for f in data["findings"] if f["route"] == "/user/detail")
        self.assertIn("110", f1["line_hint"])                # hint unioned from the dup
        self.assertIn("110", f1["loc"]["text"])

    def test_failed_unit_does_not_block(self):
        self._draft("u1", [self.F1])
        (self.run_dir / "markers" / "u9.failed").write_text(
            json.dumps({"unit": "u9", "reason": "path-drift"}), encoding="utf-8")
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertEqual(code, 0)
        payload = json.loads(out)
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((self.run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        self.assertEqual(payload["counts"]["failed_units"], 1)
        self.assertEqual(manifest["failed_units"][0]["unit"], "u9")
        self.assertEqual(len(data["rows"]), 0)   # failed units never become rows
        self.assertTrue(any("1 个评审单元失败" in b for b in data["boundaries"]))

    def test_unparsable_done_draft_counts_failed(self):
        self._draft("u1", [self.F1])
        (self.run_dir / "drafts" / "ubroken.json").write_text("{not json",
                                                              encoding="utf-8")
        (self.run_dir / "markers" / "ubroken.done").write_text("{}", encoding="utf-8")
        code, out, _ = self._run("--run-dir", str(self.run_dir), "--repo", str(self.repo))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["counts"]["failed_units"], 1)

    def test_honesty_boundary_at_least_6(self):
        self._draft("u1", [self.F1])
        _, _, data, manifest = self._render()
        self.assertGreaterEqual(len(manifest["boundaries"]), 6)
        self.assertEqual(manifest["boundaries"], data["boundaries"])

    # --- head / overview / disclosure variants ----------------------------------

    def test_unapproved_boundary_and_head_variant(self):
        # declared-but-unauthorized skip: distinct from not-found — head names 未授权,
        # boundaries carry the unapproved entry with the paths
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["unapproved: D:/xxx/front",
                                 "not-found: D:/xxx/gone"],
            "pending_approval": ["D:\\xxx\\front"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        self._draft("u1", [self.F1])
        _, _, data, manifest = self._render()
        self.assertEqual(data["meta"]["external_headline"],
                         "无(外部仓未授权,前端相关检查面未覆盖)")
        self.assertTrue(any("未经用户确认写入项目配置" in b and "D:/xxx/front" in b
                            for b in manifest["boundaries"]))
        # not-found alone (no unapproved): head stays the unreachable variant
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["not-found: D:/xxx/gone"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        _, _, data, _ = self._render()
        self.assertEqual(data["meta"]["external_headline"],
                         "无(未声明 / 不可达降级,前端相关检查面未覆盖)")
        self.assertFalse(any("外部仓未授权" in b for b in data["boundaries"]))

    def test_check_ok_with_unapproved_boundaries(self):
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "external_skipped": ["unapproved: D:/xxx/front"],
            "pending_approval": ["D:\\xxx\\front"],
            "baseline_truncated": False,
        }, ensure_ascii=False), encoding="utf-8")
        self._draft("u1", [self.F1])
        self._render()
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_grouping_overview_and_exclusion_disclosure(self):
        # grouping.json in the run dir -> meta.overview entries (unit counts + codegraph
        # stats + exclusion counts) + the honesty-boundary exclusion entry; manifest
        # counts.excluded_files passes through.
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
        _, _, data, manifest = self._render()
        overview = {o["k"]: o["v"] for o in data["meta"]["overview"]}
        self.assertIn("interface 2 / standalone 1", overview["单元数"])
        self.assertIn("向上锚定 8", overview["codegraph"])
        self.assertIn("120 个", overview["排除文件"])
        self.assertIn("排除集披露", "".join(data["boundaries"]))
        self.assertIn("test-tree 80", "".join(data["boundaries"]))
        self.assertEqual(manifest["counts"]["excluded_files"], 120)
        code, _, cerr = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, cerr)

    def test_no_grouping_json_renders_without_overview(self):
        # older run layout: no grouping.json -> no overview entries, no rows
        self._draft("u1", [self.F1])
        _, _, data, _ = self._render()
        self.assertEqual(data["meta"]["overview"], [])
        self.assertEqual(data["rows"], [])
        self.assertGreaterEqual(len(data["boundaries"]), 6)

    # --- 简报表 rows + row_links (new report structure) --------------------------

    CHAIN_A = [
        {"fqn_short": "OrderController.submit", "label": "OrderController.submit",
         "file": "src/main/java/com/x/controller/OrderController.java", "line": 42,
         "change": "changed", "route": "/order/submit"},
        {"fqn_short": "OrderServiceImpl.submit", "label": "OrderServiceImpl.submit",
         "file": "src/main/java/com/x/service/OrderServiceImpl.java", "line": 60,
         "change": "changed"},
        {"fqn_short": "OrderDao.insertOrder", "label": "OrderDao.insertOrder",
         "file": "src/main/java/com/x/dao/OrderDao.java", "line": 30, "change": "changed"},
        {"fqn_short": "OrderDaoMapper.xml", "label": "OrderDaoMapper.xml:insertOrder",
         "file": "src/main/resources/mapper/OrderDaoMapper.xml", "line": None,
         "change": "external", "branch_of": 2},
    ]
    CHAIN_B = [
        {"fqn_short": "UserController.list", "label": "UserController.list",
         "file": "src/main/java/com/x/controller/UserController.java", "line": 12,
         "change": "unchanged", "route": "/user/list"},
        {"fqn_short": "UserService.queryUser", "label": "UserService.queryUser",
         "file": "src/main/java/com/x/service/UserService.java", "line": 80,
         "change": "changed"},
        {"fqn_short": "LogDao.insertLog", "label": "LogDao.insertLog",
         "file": "src/main/java/com/x/dao/LogDao.java", "line": 20, "change": "changed"},
        {"fqn_short": "UserDao.findById", "label": "UserDao.findById",
         "file": "src/main/java/com/x/dao/UserDao.java", "line": 25, "change": "changed",
         "branch_of": 1},
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

    def test_summary_rows_sort_and_row_links(self):
        # 2 interface units (routes /order/submit + /user/list) + 1 standalone:
        # rows sorted interface-by-route then standalone; row_links segments de-linkify
        # to the exact plain-text chain; failed unit never becomes a row
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
        _, _, data, manifest = self._render()
        self.assertEqual([r["unit_id"] for r in data["rows"]],
                         ["OrderController_submit", "UserController_list",
                          "utils_Helper"])
        # † unchanged entry + branch marker ride the plain text (CHAIN_B has no mapper
        # terminal — its branch is a java fan-out; ⇢ is covered in ChainSegmentsTest)
        user_row = next(r for r in manifest["rows"]
                        if r["unit_id"] == "UserController_list")
        self.assertTrue(user_row["chain"].startswith("†UserController.list"))
        self.assertIn("⤷", user_row["chain"])
        # row_links: separators stay outside the hrefs; de-linkified join == chain text.
        # interface-row entry is a route string and NEVER links — the 类名.方法名 short
        # forms in the chain cell carry the source links
        by_unit = {rl["unit_id"]: rl for rl in data["row_links"]}
        self.assertIsNone(by_unit["UserController_list"]["entry"]["href"])
        segs = by_unit["UserController_list"]["chain"]
        self.assertEqual("".join(s["sep"] + s["text"] for s in segs),
                         user_row["chain"])
        self.assertEqual(segs[0]["href"],
                         "src/main/java/com/x/controller/UserController.java#L12")
        self.assertFalse(segs[-1]["sep"] and segs[-1]["sep"].strip() == "→",
                         "branch separator must be ⤷, not →")
        self.assertEqual(segs[-1]["sep"], " ⤷")
        # dimension refs: P-NN pure text in rows (machine face), href in row_links (view)
        self.assertEqual(user_row["issue_refs"], ["P-02"])
        self.assertEqual(data["findings"][1]["pnum"], "P-02")
        # standalone row: entry = first-chain-node short form (empty chain -> entry text)
        st = next(r for r in manifest["rows"] if r["unit_id"] == "utils_Helper")
        self.assertEqual(st["entry"], "utils_Helper")

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
        _, _, data, manifest = self._render()
        by_entry = {r["entry"]: r for r in manifest["rows"]}
        self.assertEqual(by_entry["/order/submit"]["frontend_is"], "是")
        self.assertEqual(by_entry["/order/submit"]["frontend_count"], "2 处")
        self.assertEqual(by_entry["/user/list"]["frontend_is"], "否")
        self.assertEqual(by_entry["/user/list"]["frontend_count"], "—")
        self.assertEqual(by_entry["/order/batch"]["frontend_is"], "未知")
        # merged unit's main route /order/batch is undeclared => 未知 despite the
        # secondary segment /order/submit having hits
        self.assertEqual(by_entry["/order/batch(+1)"]["frontend_is"], "未知")
        self.assertEqual(len(manifest["rows"]), 4)
        self.assertEqual(data["rows"], manifest["rows"])

    def test_pnn_anchors_data(self):
        # P-NN global + severity-asc ordering; each table ref maps to exactly one
        # 章节二 entry whose pnum is the in-page anchor id the page JS emits
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
        ])
        self._draft("OrderController_submit", [{
            "dimension": "vertical-authz", "severity": "high", "route": "/order/submit",
            "file": "OrderController.java", "line_hint": "42", "line": 42, "risk": "r",
            "suggestion": "s", "control_ref": None}])
        _, report, data, _ = self._render()
        pnums = [f["pnum"] for f in data["findings"]]
        self.assertEqual(pnums, ["P-01"])
        self.assertEqual(data["rows"][0]["issue_refs"], ["P-01"])
        # the anchor targets are created by the page JS from the data; the template
        # carries the finding container and the link-building code
        self.assertIn('id="sec-findings"', report)
        self.assertIn('setAttribute("id", f.pnum)', report)
        # 调用链两级展示:主链 + 缩进分支子块(视图层分组,段序与字形不变)
        self.assertIn("chain-main", report)
        self.assertIn("chain-sub", report)

    def test_extension_dimension_chinese_label(self):
        # free-text extension dims are sanctioned by the fan-out task; an observed
        # extension shows its curated Chinese label in the column header and finding
        # titles, while the machine face keeps the raw kebab key
        self.assertEqual(self.m._dim_col("architecture-layering"), "架构分层")
        self.assertEqual(self.m._DIMENSION_LABEL["architecture-layering"], "架构分层")
        self.assertEqual(self.m._dim_col("never-seen-dim"), "never-seen-dim")
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
        ])
        self._draft("OrderController_submit", [{
            "dimension": "architecture-layering", "severity": "low",
            "route": "/order/submit", "file": "OrderController.java",
            "line_hint": "42", "risk": "控制器内直拼 DAO 调用",
            "suggestion": "下沉 service 层", "control_ref": None}])
        _, _, data, manifest = self._render()
        self.assertEqual(data["dimension_columns"][-1], "architecture-layering")
        self.assertEqual(data["meta"]["dimension_cols"]["architecture-layering"],
                         "架构分层")
        ext = next(f for f in data["findings"]
                   if f["dimension"] == "architecture-layering")
        self.assertEqual(ext["dimension_label"], "架构分层")
        self.assertEqual(manifest["rows"][0]["issue_refs"], [ext["pnum"]])

    # --- 章节三 SVG graph data ----------------------------------------------------

    def test_svg_graphs_branched_units_only(self):
        # CHAIN_B has a real branch (non-external node with branch_of); CHAIN_A's only
        # branch_of is its ⇢ mapper terminal = a LINEAR direct-dao chain -> NO graph.
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
            {"unit_id": "UserController_list", "kind": "interface",
             "route": "/user/list", "chain": self.CHAIN_B, "status": "done"},
            {"unit_id": "UserController_two", "kind": "interface",
             "route": "/user/two", "chain": self.CHAIN_B[:2], "status": "done"},
        ])
        _, _, data, _ = self._render()
        self.assertEqual([g["unit_id"] for g in data["chain_graphs"]],
                         ["UserController_list"])
        g = data["chain_graphs"][0]
        # layout: main line depth = position; branch node one below its host; viewBox
        # spans all nodes
        self.assertEqual(len(g["nodes"]), 4)
        self.assertEqual(len(g["edges"]), 3)
        by_id = {n["id"]: n for n in g["nodes"]}
        self.assertLess(by_id[0]["x"], by_id[1]["x"])
        self.assertEqual(by_id[3]["x"], by_id[2]["x"])     # depth(host)+1 = host's next column
        self.assertGreater(by_id[3]["y"], by_id[2]["y"])   # own row, no overlap
        # dashed edge into the unchanged? no — dashed only for external terminals; the
        # branch edge here is a normal java fan-out edge
        self.assertEqual([e["dashed"] for e in g["edges"]], [False, False, False])
        # † prefix survives into the graph label (after the entry's route prefix);
        # hover title = file:line
        self.assertEqual(by_id[0]["label"], "/user/list †UserController.list")
        self.assertEqual(by_id[0]["title"],
                         "src/main/java/com/x/controller/UserController.java:12")
        self.assertGreater(g["width"], 0)
        self.assertGreater(g["height"], 0)

    def test_svg_dashed_mapper_terminal_edge(self):
        # a REAL branch whose subtree ends in a mapper terminal: terminal edge is dashed
        branched = list(self.CHAIN_A) + [
            {"fqn_short": "AuditDao.log", "label": "AuditDao.log",
             "file": "src/main/java/com/x/dao/AuditDao.java", "line": 9,
             "change": "changed", "branch_of": 1},
            {"fqn_short": "AuditMapper.xml", "label": "AuditMapper.xml:log",
             "file": "src/main/resources/mapper/AuditMapper.xml", "line": None,
             "change": "external", "branch_of": 4},
        ]
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": branched, "status": "done"},
        ])
        _, _, data, _ = self._render()
        self.assertEqual(len(data["chain_graphs"]), 1)
        g = data["chain_graphs"][0]
        by_id = {n["id"]: n for n in g["nodes"]}
        self.assertEqual(len(g["nodes"]), 6)
        dashed = [e for e in g["edges"] if e["dashed"]]
        self.assertEqual(len(dashed), 2)   # the ⇢ terminal on the main line + branch's ⇢
        for e in dashed:
            self.assertEqual(by_id[e["dst"]]["terminal"], True)
        self.assertFalse(by_id[5]["terminal"] and by_id[4]["terminal"])

    # --- 章节二 findings line / degrade -------------------------------------------

    def test_detail_findings_line_and_degrade(self):
        # draft WITH line -> file:line + #L anchor; draft WITHOUT line -> file(hint)
        # plain (old-draft compatible; never a hard failure)
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
        _, _, data, _ = self._render()
        f1, f2 = data["findings"]
        self.assertEqual(f1["pnum"], "P-01")
        self.assertEqual((f1["dimension_label"], f1["severity_label"]),
                         ("输入校验", "低"))
        self.assertEqual(f1["loc"]["text"], "OrderVO.java:11")
        self.assertEqual(f1["loc"]["href"], "OrderVO.java#L11")
        self.assertEqual(f2["loc"]["text"], "OldVO.java(3-5)")
        self.assertEqual(f2["loc"]["href"], "OldVO.java")   # no anchor on degrade

    # --- manifest rows projection + --check ----------------------------------------

    def test_rows_projection_consistency_and_check(self):
        self._grouping([
            {"unit_id": "OrderController_submit", "kind": "interface",
             "route": "/order/submit", "chain": self.CHAIN_A, "status": "done"},
        ])
        self._draft("OrderController_submit", [{
            "dimension": "vertical-authz", "severity": "high", "route": "/order/submit",
            "file": "OrderController.java", "line_hint": "42", "line": 42, "risk": "r",
            "suggestion": "s", "control_ref": None}])
        _, _, data, manifest = self._render()
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)
        # tamper: drop manifest rows -> manifest rows != data rows -> exit 2
        mp = self.run_dir / "sdr_manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["rows"] = []
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("rows[]", err)

    def test_check_ok_and_counts_mismatch(self):
        self._draft("u1", [self.F1])
        self._render()
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

    def test_check_data_file_tamper_is_carrier_drift(self):
        self._draft("u1", [self.F1])
        self._render()
        dp = self.run_dir / "sdr_report_data.json"
        d = json.loads(dp.read_text(encoding="utf-8"))
        d["boundaries"].append("人为篡改")
        dp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("carrier drift", err)

    def test_check_embed_block_tamper_is_carrier_drift(self):
        self._draft("u1", [self.F1])
        payload, _, _, _ = self._render()
        rp = Path(payload["report"])
        html = rp.read_text(encoding="utf-8")
        self.assertIn('"v": 1', html)
        rp.write_text(html.replace('"v": 1', '"v": 2', 1), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("carrier drift", err)

    def test_check_missing_data_file(self):
        self._draft("u1", [self.F1])
        self._render()
        (self.run_dir / "sdr_report_data.json").unlink()
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("sdr_report_data.json missing", err)

    def test_check_missing_section_marker(self):
        self._draft("u1", [self.F1])
        payload, _, _, _ = self._render()
        rp = Path(payload["report"])
        rp.write_text(rp.read_text(encoding="utf-8")
                      .replace(' id="sec-boundaries"', "", 1), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn('id="sec-boundaries"', err)

    def test_check_rejects_non_html_report(self):
        self._draft("u1", [self.F1])
        payload, _, _, _ = self._render()
        mp = self.run_dir / "sdr_manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        fake = self.repo / "mgh-sdr-feature-pay-old.md"
        fake.write_text("# old md report\n诚实边界\n", encoding="utf-8")
        m["report"] = str(fake)
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("not a .html", err)

    def test_missing_run_dir_exits_1(self):
        code, _, _ = self._run("--run-dir", str(self.tmp / "nope"), "--repo",
                               str(self.repo))
        self.assertEqual(code, 1)


class HrefTest(unittest.TestCase):
    """_href_of unit behaviour: the lexical link rules and every degradation."""

    def setUp(self):
        self.m = _load()
        self.repo = Path(os.path.normcase("C:/dev/repo"))

    def _href(self, file, line=None, repo=None):
        return self.m._href_of(file, line, repo or self.repo)

    def test_relative_path_with_line(self):
        self.assertEqual(self._href("src/main/java/Ctl.java", 42),
                         "src/main/java/Ctl.java#L42")

    def test_no_line_anchor_omitted(self):
        self.assertEqual(self._href("src/mapper/M.xml", None), "src/mapper/M.xml")

    def test_outside_repo_absolute_stays_plain(self):
        self.assertIsNone(self._href("C:/other/place/F.java", 3))
        self.assertIsNone(self._href("D:/dev/repo/F.java", 3))   # other drive

    def test_inside_repo_absolute_case_insensitive_drive(self):
        self.assertEqual(self._href("c:/DEV/repo/src/F.java", 7), "src/F.java#L7")

    def test_empty_and_missing_stay_plain(self):
        for f in ("", "   ", None, 42, ["a"]):
            self.assertIsNone(self._href(f, 1))

    def test_space_and_paren_paths_stay_plain(self):
        self.assertIsNone(self._href("src/my dir/F.java", 1))
        self.assertIsNone(self._href("src/f(1).java", 1))

    def test_backslash_relative_normalized_to_slash(self):
        self.assertEqual(self._href("src\\main\\F.java", 1), "src/main/F.java#L1")

    def test_parent_escape_stays_plain(self):
        self.assertIsNone(self._href("../outside/F.java", 1))
        self.assertIsNone(self._href("src/../../outside/F.java", 1))

    def test_bool_line_is_not_an_anchor(self):
        self.assertEqual(self._href("src/F.java", True), "src/F.java")

    def test_posix_absolute_inside_repo(self):
        if os.name == "nt":
            self.skipTest("POSIX-absolute semantics only exist off Windows")
        self.assertEqual(self._href("/repo/src/F.java", 2, Path("/repo")),
                         "src/F.java#L2")


class ChainSegmentsTest(unittest.TestCase):
    """row_links segments are the SAME walk as the plain-text chain: de-linkified join
    reproduces _render_chain byte-for-byte (manifest rows stay the machine truth)."""

    def setUp(self):
        self.m = _load()
        self.repo = Path(os.path.normcase("C:/dev/repo"))

    def test_branched_chain_join_equals_plain_text(self):
        chain = [
            {"fqn_short": "Ctl.submit", "file": "src/Ctl.java", "line": 10,
             "change": "changed", "route": "/order/submit"},
            {"fqn_short": "Svc.submit", "file": "src/Svc.java", "line": 20,
             "change": "changed"},
            {"fqn_short": "Svc.helper", "file": "src/Svc.java", "line": 25,
             "change": "changed"},
            {"fqn_short": "Dao.ins", "file": "src/Dao.java", "line": 30,
             "change": "changed"},
            {"fqn_short": "DaoMapper.xml", "file": "src/mapper/D.xml", "line": None,
             "change": "external", "branch_of": 3},
            {"fqn_short": "†Shell.run", "file": "src/Shell.java", "line": 5,
             "change": "unchanged", "branch_of": 0},
        ]
        segs = self.m._chain_segments(chain, self.repo)
        plain = self.m._render_chain(chain)
        self.assertEqual("".join(s["sep"] + s["text"] for s in segs), plain)
        # separators never ride the href; † stays inside the text
        self.assertEqual(segs[0]["href"], "src/Ctl.java#L10")
        self.assertEqual(segs[4]["sep"], " ⇢")
        self.assertEqual(segs[5]["sep"], " ⤷")
        self.assertEqual(segs[2]["sep"], " ·")   # same-class continuation
        self.assertEqual(segs[2]["href"], "src/Svc.java#L25")
        for s in segs:
            self.assertNotIn(s["href"] or "", s["sep"])

    def test_empty_chain_gives_no_segments(self):
        self.assertEqual(self.m._chain_segments([], self.repo), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
