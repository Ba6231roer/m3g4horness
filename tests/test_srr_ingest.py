#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ingest_requirements.py regression (r1 input adapter for /mgh-srr).

Covers: text-native (.txt/.md/.csv/.json) perfect extraction with no degraded flag;
.docx best-effort (cross-<w:r> run join so text never token-fragments + degraded flags);
.xlsx best-effort (sharedStrings / numeric / inlineStr + degraded flags); --text / stdin
passthrough (verbatim, no degraded); unsupported format exits 2 with a recipe; --split
enumerates multiple pending[] units; default = single unit; produced change_context.json
matches the sra shape (pending paths absolute + under project_root, degraded is a string[]);
--check accepts a valid context and rejects malformed ones (exit 2). Run from any cwd.
Run: py tests/test_srr_ingest.py
"""
import json, subprocess, sys, tempfile, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "ingest_requirements.py"
PY = sys.executable
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def run(args, cwd, stdin=None):
    r = subprocess.run([PY, str(SCRIPT), *args], cwd=str(cwd), capture_output=True,
                       input=stdin, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def make_project():
    """A throwaway project with an openspec/ dir (so project_root resolves to it)."""
    d = Path(tempfile.mkdtemp(prefix="mgh_srr_"))
    (d / "openspec").mkdir()
    return d


def ctx_of(project, out=".mgh-srr"):
    return json.loads((project / out / "change_context.json").read_text(encoding="utf-8"))


def write_docx(path, paras, numpr=False, table=False, textbox=False):
    """Build a minimal .docx; paras is a list of (runs, tab?, br?)."""
    body = []
    for runs in paras:
        p = "<w:p>"
        if numpr:
            p += "<w:pPr><w:numPr><w:ilvl w:val=\"0\"/><w:numId w:val=\"1\"/></w:numPr></w:pPr>"
        for r in runs:
            p += f"<w:r><w:t>{r}</w:t></w:r>"
        p += "</w:p>"
        body.append(p)
    extra = ""
    if table:
        extra += "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
    if textbox:
        extra += "<w:p><w:r><w:t>box</w:t></w:r></w:p>"
    doc = (f'<?xml version="1.0"?><w:document xmlns:w="{_W}"><w:body>'
           f"{''.join(body)}{extra}</w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType="text/xml"/>'
                   "</Types>")
        z.writestr("word/document.xml", doc)


def write_xlsx(path, rows, shared=None, merge=False):
    """rows = list of list of (kind, val): ('s', idx) | ('n', num) | ('is', str)."""
    sd = "".join(
        "<row>" + "".join(
            f'<c t="s"><v>{v}</v></c>' if k == "s" else
            f'<c t="inlineStr"><is><t>{v}</t></is></c>' if k == "is" else
            f"<c><v>{v}</v></c>"
            for k, v in row) + "</row>"
        for row in rows)
    merge_xml = '<mergeCells count="1"><mergeCell ref="A1:A2"/></mergeCells>' if merge else ""
    sheet = (f'<?xml version="1.0"?><worksheet xmlns="{_S}"><sheetData>{sd}</sheetData>'
             f"{merge_xml}</worksheet>")
    ss = ""
    if shared:
        ss = '<sst xmlns="%s">%s</sst>' % (
            _S, "".join(f"<si><t>{s}</t></si>" for s in shared))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Default Extension="xml" ContentType="text/xml"/>'
                   "</Types>")
        z.writestr("xl/workbook.xml",
                   f'<?xml version="1.0"?><workbook xmlns="{_S}"><sheets>'
                   f'<sheet name="Sheet1" sheetId="1" r:id="rId1" '
                   f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
                   f"</sheets></workbook>")
        if shared:
            z.writestr("xl/sharedStrings.xml", ss)
        z.writestr("xl/worksheets/sheet1.xml", sheet)


import unittest


class TestTextNative(unittest.TestCase):
    def test_md_native_no_degraded(self):
        p = make_project()
        (p / "req.md").write_text(
            "# 转账\n发起 POST /api/transfer,字段 bankCardNo。\n## 退款\nPOST /api/refund。\n",
            encoding="utf-8")
        rc, out, err = run(["--doc", "req.md", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual([r["heading"] for r in d["requirements"]], ["转账", "退款"])
        self.assertEqual(d["endpoints"], ["POST /api/transfer", "POST /api/refund"])
        self.assertEqual(d["data_fields"], ["bankCardNo"])
        self.assertEqual(d["degraded"], [])
        self.assertEqual(d["tasks"], [])

    def test_csv_native(self):
        p = make_project()
        (p / "req.csv").write_text("接口,方法\n转账,POST /api/transfer\n", encoding="utf-8")
        rc, out, _ = run(["--doc", "req.csv", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertIn("POST /api/transfer", d["requirements"][0]["body"])
        self.assertEqual(d["degraded"], [])

    def test_json_native(self):
        p = make_project()
        (p / "req.json").write_text('{"req": "POST /api/x with bankCardNo"}', encoding="utf-8")
        rc, out, _ = run(["--doc", "req.json", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(d["endpoints"], ["POST /api/x"])
        self.assertEqual(d["degraded"], [])


class TestDocx(unittest.TestCase):
    def test_cross_run_join_no_fragmentation(self):
        p = make_project()
        write_docx(p / "req.docx", [[("转"), ("账"), ("接口")]])
        rc, out, _ = run(["--doc", "req.docx", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        body = d["requirements"][0]["body"]
        self.assertIn("转账接口", body)            # runs joined, not fragmented
        self.assertIn("docx-best-effort", d["degraded"])

    def test_degraded_flags(self):
        p = make_project()
        write_docx(p / "req.docx", [[("a")]], numpr=True, table=True, textbox=True)
        rc, out, _ = run(["--doc", "req.docx", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        deg = json.loads(out)["degraded"]
        self.assertIn("list-markers-lost", deg)
        self.assertIn("tables-flattened", deg)


class TestXlsx(unittest.TestCase):
    def test_sharedstrings_numeric(self):
        p = make_project()
        write_xlsx(p / "req.xlsx",
                   rows=[[("s", 0), ("n", 45000)]],
                   shared=["bankCardNo"])
        rc, out, _ = run(["--doc", "req.xlsx", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        body = d["requirements"][0]["body"]
        self.assertIn("bankCardNo", body)          # sharedString resolved
        self.assertIn("45000", body)               # numeric preserved
        self.assertIn("xlsx-best-effort", d["degraded"])
        self.assertIn("numeric-formats-unresolved", d["degraded"])

    def test_merged_cells_flag(self):
        p = make_project()
        write_xlsx(p / "req.xlsx", rows=[[("n", 1)]], merge=True)
        rc, out, _ = run(["--doc", "req.xlsx", "--out", ".mgh-srr"], cwd=p)
        self.assertIn("merged-cells", json.loads(out)["degraded"])


class TestPassthrough(unittest.TestCase):
    def test_text_passthrough_no_degraded(self):
        p = make_project()
        rc, out, _ = run(["--text", "# x\nPOST /api/y", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(d["change"], "freeform-text")
        self.assertEqual(d["degraded"], [])
        self.assertIn("POST /api/y", d["requirements"][0]["body"])

    def test_stdin_passthrough(self):
        p = make_project()
        rc, out, _ = run(["--doc", "-", "--out", ".mgh-srr"], cwd=p, stdin="plain stdin text")
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(d["change"], "stdin")
        self.assertEqual(d["degraded"], [])


class TestUnsupported(unittest.TestCase):
    def test_doc_exits2_with_recipe(self):
        p = make_project()
        (p / "bad.doc").write_text("x", encoding="utf-8")
        rc, out, err = run(["--doc", "bad.doc", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 2)
        self.assertIn("recipe", err)
        self.assertFalse((p / ".mgh-srr" / "change_context.json").exists(),
                         "must not emit a partial context")


class TestFanout(unittest.TestCase):
    def test_default_single_unit(self):
        p = make_project()
        rc, out, _ = run(["--text", "# A\nx\n# B\ny\n", "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(len(d["pending"]), 1)
        self.assertEqual(len(d["capabilities"]), 1)
        self.assertEqual(d["capabilities"][0]["name"], "freeform-review")

    def test_split_enumerates_units(self):
        p = make_project()
        rc, out, _ = run(["--text", "# A\nx\n# B\ny\n# C\nz\n", "--split", "--out", ".mgh-srr"],
                         cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(len(d["pending"]), 3)
        self.assertEqual(len(d["capabilities"]), 3)
        self.assertEqual(len(d["requirements"]), 3)

    def test_pending_paths_absolute_in_subtree(self):
        p = make_project()
        rc, out, _ = run(["--text", "# A\nx\n", "--split", "--out", ".mgh-srr"], cwd=p)
        d = json.loads(out)
        for item in d["pending"]:
            self.assertTrue(Path(item["draft_path"]).is_absolute())
            self.assertTrue(Path(item["draft_path"]).resolve()
                            .is_relative_to(Path(d["project_root"]).resolve()))
            self.assertTrue(item["draft_path"].endswith(".md"))
            self.assertTrue(item["done_marker"].endswith(".md.done"))


class TestShapeParity(unittest.TestCase):
    def test_sra_top_level_fields_present(self):
        p = make_project()
        rc, out, _ = run(["--text", "POST /api/x bankCardNo", "--out", ".mgh-srr"], cwd=p)
        d = json.loads(out)
        for f in ("change", "change_root", "project_root", "capabilities", "requirements",
                  "tasks", "mentioned_files", "endpoints", "data_fields", "role_hints",
                  "candidate_controls", "clarify_path", "pending", "memory", "rules_source",
                  "memory_source", "dry_run", "truncated", "degraded"):
            self.assertIn(f, d, f"missing sra-shape field: {f}")
        self.assertIn("clarify_path", d)
        self.assertEqual(d["rules_source"], "none")

    def test_rules_candidate_controls(self):
        p = make_project()
        (p / ".mgh-init").mkdir()
        (p / ".mgh-init" / "controls_inventory.json").write_text(json.dumps({
            "controls": [{"name": "AuthzFilter", "category": "authorization",
                          "evidence": ["src/Authz.java"], "entry_points": ["src/payment.py"]}]
        }, ensure_ascii=False), encoding="utf-8")
        rc, out, _ = run(["--text", "POST /api/transfer on src/payment.py", "--rules", ".mgh-init",
                          "--out", ".mgh-srr"], cwd=p)
        self.assertEqual(rc, 0)
        d = json.loads(out)
        self.assertEqual(len(d["candidate_controls"]), 1)
        self.assertEqual(d["candidate_controls"][0]["name"], "AuthzFilter")
        self.assertEqual(d["candidate_controls"][0]["dimensions"],
                         ["horizontal-authz", "vertical-authz"])  # category -> dimensions (sra)


class TestCheck(unittest.TestCase):
    def test_check_ok(self):
        p = make_project()
        run(["--text", "POST /api/x", "--out", ".mgh-srr"], cwd=p)
        rc, out, _ = run(["--check", ".mgh-srr/change_context.json"], cwd=p)
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_check_rejects_out_of_subtree(self):
        p = make_project()
        run(["--text", "POST /api/x", "--out", ".mgh-srr"], cwd=p)
        d = ctx_of(p)
        d["pending"][0]["draft_path"] = "D:/outside.md"  # absolute but outside project
        (p / ".mgh-srr" / "change_context.json").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")
        rc, out, _ = run(["--check", ".mgh-srr/change_context.json"], cwd=p)
        self.assertEqual(rc, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_check_rejects_missing_field(self):
        p = make_project()
        run(["--text", "POST /api/x", "--out", ".mgh-srr"], cwd=p)
        d = ctx_of(p)
        del d["clarify_path"]
        d["degraded"] = "not-a-list"
        (p / ".mgh-srr" / "change_context.json").write_text(
            json.dumps(d, ensure_ascii=False), encoding="utf-8")
        rc, out, _ = run(["--check", ".mgh-srr/change_context.json"], cwd=p)
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
