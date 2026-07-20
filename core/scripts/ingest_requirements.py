#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
ingest_requirements — deterministic r1 (input adapter) for /mgh-srr: read a freeform
requirement document (.txt/.md/.csv/.json natively, .docx/.xlsx best-effort via stdlib
zipfile + xml.etree) OR --text / stdin passthrough, and emit a `change_context.json` of
the SAME shape as /mgh-sra's prepare_augment.py, so the reused sra middle engine
(sra-clarify / sra-augment / sra-consistency) consumes it UNMODIFIED. This is the
port-adapter: only the input seam changes, the engine is reused verbatim.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib/zipfile/xml.etree).
Signal extraction + candidate-control derivation are reused from prepare_augment.py
(single source of truth — the sra engine's mechanical extractors), imported as a sibling.

CLI contract (`--help` is the contract surface, R5.1):
  py ingest_requirements.py --doc <path|dir|-> [--text <str>] [--rules <path>]
                            [--focus <inline-json|path>] [--split] [--out <dir>]
                            [--dry-run] [--no-interactive]
  py ingest_requirements.py --text <str> [--rules <path>] [--focus <inline-json|path>]
                            [--out <dir>] [--dry-run]
  py ingest_requirements.py --check <change_context.json>

  --doc <path|dir|->   input: a .txt/.md/.csv/.json/.docx/.xlsx FILE, a DIR (scans
                       supported files), or `-` for stdin
  --text <str>         passthrough: use this text verbatim (no format extraction, no
                       degraded flag). If neither --doc nor --text is given, reads stdin.
  --rules <path>       optional mgh-init controls_inventory.json FILE or its output DIR
                       (e.g. <project>/.mgh-init); reused from sra for candidate-control
                       derivation (category -> dimensions + file overlap)
  --focus <json|path>  optional security-dimension focus (inline JSON beginning with `{`
                       or a path to a JSON file; leading `@` tolerated). Same shape +
                       semantics as /mgh-sra's --focus (see focus_scope). Parsed + closed-
                       set-validated via the shared focus_scope module (reused from sra)
                       BEFORE any LLM; embedded as the `focus` field of change_context.json
                       (object or null). Omit = all 9 dimensions (behavior unchanged). The
                       reused a2/a3 subagents narrow their scan with ZERO new prompts.
                       Invalid → exit 2, no context emitted.
  --sensitive-catalog <json|@path|->
                       optional company masking-policy catalog (inline JSON beginning with
                       `{`, `-` for stdin, or a path to a JSON file; leading `@` tolerated).
                       Same shape + semantics as /mgh-sra's --sensitive-catalog (see
                       sensitive_catalog). Parsed + closed-set-validated via the shared
                       sensitive_catalog module (reused from sra) BEFORE any LLM; embedded
                       as the `sensitive_catalog` field of change_context.json (object or
                       null). Omit = legacy 6 facets only (behavior unchanged). The reused
                       a2/a3 subagents check per-item masking gaps with ZERO new prompts.
                       Invalid → exit 2, no context emitted.
  --split              split by markdown `#`/`##` headings into multiple pending[] units
                       (fan-out = script enumeration; default = one unit = whole doc)
  --out <dir>          output dir (default: <project>/.mgh-srr)
  --dry-run            produce change_context.json + stdout summary only (orchestrator
                       skips the render/memory steps; flag echoed for the orchestrator)
  --no-interactive     clarification uses default guesses (flag echoed for orchestrator)
  --check <path>       intake validation only: validate the change_context.json at <path>
                       is structurally complete (top-level fields + capabilities[]/
                       requirements[]/pending[] + pending paths absolute & under
                       project_root + degraded is a string[] + focus field shape if
                       present + sensitive_catalog field shape if present); exit 2 on
                       violation.

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b): the full
`change_context.json` object (the orchestrator reads `pending[]` / `clarify_path` /
`candidate_controls` / `memory` from it; see core/contracts/srr/intake-report.md).
In --check mode stdout = {"check":"srr-intake","ok":bool,"violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / unreadable / JSON malformed ·
2 misuse (argparse), unsupported input format (--doc), or intake-shape violation (--check).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Self-locate so the sibling import resolves under any cwd (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))
# Reuse sra's mechanical signal extractors + candidate-control derivation verbatim
# (single source of truth for the shared middle engine). See prepare_augment.py.
import prepare_augment as _sra

_TEXT_EXTS = {".txt", ".md", ".csv", ".json"}
_ALL_EXTS = _TEXT_EXTS | {".docx", ".xlsx"}

# OOXML namespaces.
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

_HEADING_RX = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_SPLIT_RX = re.compile(r"^(#{1,2})\s+(.+?)\s*$", re.MULTILINE)
_SAFE_NAME_RX = re.compile(r"[^A-Za-z0-9_-]+")


def _find_project_root(start: Path):
    """Walk up for an `openspec/` dir (shares sra's project root so business memory
    accumulates in the SAME file); fall back to cwd (srr works without openspec)."""
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "openspec").is_dir():
            return cand
    return p


# ── format readers ──────────────────────────────────────────────────────────────

def _extract_docx(path: Path):
    """Best-effort .docx text via stdlib zipfile + xml.etree. Joins all <w:t> within
    each <w:p> (handles <w:tab/>/<w:br/>) so cross-run text never token-fragments.
    Returns (text, degraded[])."""
    degraded = ["docx-best-effort"]
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        print(f"error: not a readable .docx (missing/corrupt word/document.xml): {path}: {e}",
              file=sys.stderr)
        sys.exit(1)
    raw = xml.decode("utf-8", "ignore")
    if "<w:numPr" in raw:
        degraded.append("list-markers-lost")
    if "txbxContent" in raw or "AlternateContent" in raw:
        degraded.append("textboxes-skipped")
    if "<w:object" in raw or "<w:drawing" in raw or "<w:pict" in raw:
        degraded.append("embedded-objects-skipped")
    if "<w:tbl" in raw:
        degraded.append("tables-flattened")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        print(f"error: corrupt word/document.xml in {path}: {e}", file=sys.stderr)
        sys.exit(1)
    paras = []
    for p in root.iter(f"{_W}p"):
        buf = []
        for node in p.iter():
            if node.tag == f"{_W}t":
                buf.append(node.text or "")
            elif node.tag == f"{_W}tab":
                buf.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                buf.append("\n")
        paras.append("".join(buf))
    text = "\n".join(p for p in paras if p != "")
    return text, degraded


def _xlsx_shared(z: zipfile.ZipFile):
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        try:
            sroot = ET.fromstring(z.read("xl/sharedStrings.xml"))
        except ET.ParseError:
            return shared
        for si in sroot.iter(f"{_S}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
    return shared


def _xlsx_sheet_names(z: zipfile.ZipFile):
    names = []
    if "xl/workbook.xml" in z.namelist():
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
        except ET.ParseError:
            return names
        for s in wb.iter(f"{_S}sheet"):
            n = s.get("name")
            if n:
                names.append(n)
    return names


def _xlsx_sheet_text(sheet_xml: bytes, shared: list):
    try:
        root = ET.fromstring(sheet_xml)
    except ET.ParseError:
        return ""
    rows_out = []
    for row in root.iter(f"{_S}row"):
        cells = []
        for c in row.iter(f"{_S}c"):
            t = c.get("t")
            v = c.find(f"{_S}v")
            val = ""
            if t == "s" and v is not None and (v.text or "").lstrip("-").isdigit():
                idx = int(v.text)
                val = shared[idx] if 0 <= idx < len(shared) else ""
            elif t == "inlineStr":
                isn = c.find(f"{_S}is")
                if isn is not None:
                    val = "".join(tt.text or "" for tt in isn.iter(f"{_S}t"))
            elif t == "str" and v is not None:
                val = v.text or ""
            elif t == "b" and v is not None:
                val = "TRUE" if v.text == "1" else "FALSE"
            elif v is not None:
                val = v.text or ""  # numeric (may be a date serial we cannot resolve)
            cells.append(val)
        rows_out.append("\t".join(cells))
    return "\n".join(rows_out)


def _extract_xlsx(path: Path):
    """Best-effort .xlsx text via stdlib zipfile + xml.etree. Resolves sharedStrings +
    raw cell values (t=s/inlineStr/str/b/numeric). Returns (text, degraded[])."""
    degraded = ["xlsx-best-effort", "numeric-formats-unresolved"]
    try:
        with zipfile.ZipFile(path) as z:
            sheet_files = sorted(
                n for n in z.namelist()
                if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            shared = _xlsx_shared(z)
            sheet_names = _xlsx_sheet_names(z)
            has_merge = any(b"<mergeCell" in z.read(sf) for sf in sheet_files)
            if has_merge:
                degraded.append("merged-cells")
            parts = []
            for i, sf in enumerate(sheet_files):
                name = sheet_names[i] if i < len(sheet_names) else f"Sheet{i + 1}"
                body = _xlsx_sheet_text(z.read(sf), shared)
                parts.append(f"## {name}\n{body}" if body.strip() else f"## {name}")
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        print(f"error: not a readable .xlsx: {path}: {e}", file=sys.stderr)
        sys.exit(1)
    return "\n\n".join(parts), degraded


def _read_one_file(path: Path):
    """Return (text, doc_name, degraded[], mode) for a single supported file."""
    ext = path.suffix.lower()
    if ext in _TEXT_EXTS:
        return path.read_text(encoding="utf-8"), path.name, [], "text-native"
    if ext == ".docx":
        text, deg = _extract_docx(path)
        return text, path.name, deg, "docx-best-effort"
    if ext == ".xlsx":
        text, deg = _extract_xlsx(path)
        return text, path.name, deg, "xlsx-best-effort"
    print(
        "error: unsupported input format. .doc / .xls / scanned PDF / password-protected "
        "files are NOT supported (would yield only fragments).\n"
        "  recipe: re-save as .docx (Word: File > Save As .docx), export the sheet to "
        ".csv, or paste the text into a .txt — then re-run with that file, or use --text.",
        file=sys.stderr)
    sys.exit(2)


def _read_dir(path: Path):
    """Scan a dir for supported files (sorted), concatenate. Unsupported files are
    warned + skipped (never fail the whole dir). Returns (text, name, degraded[], mode)."""
    texts, degraded = [], []
    found = []
    for f in sorted(path.rglob("*")):
        if f.is_file() and f.suffix.lower() in _ALL_EXTS:
            found.append(f)
    if not found:
        print(f"error: no supported requirement files under dir: {path}", file=sys.stderr)
        sys.exit(1)
    for f in found:
        text, _name, deg, _mode = _read_one_file(f)
        texts.append(f"--- {f.relative_to(path).as_posix()} ---\n{text}")
        degraded.extend(deg)
    body = "\n\n".join(texts)
    return body, f"{path.name}(dir)", degraded, ("mixed" if len(found) > 1 else "text-native")


def _acquire_text(args):
    """Return (text, doc_name, degraded[], mode). --text > --doc (- = stdin) > --doc
    path (file/dir) > stdin passthrough."""
    if args.text is not None:
        return args.text, "freeform-text", [], "passthrough"
    if args.doc is not None and args.doc != "-":
        p = Path(args.doc)
        if not p.exists():
            print(f"error: input not found: {p}", file=sys.stderr)
            sys.exit(1)
        if p.is_dir():
            return _read_dir(p)
        return _read_one_file(p)
    # no --doc (or --doc -): stdin passthrough
    if sys.stdin.isatty():
        print("error: no input — pass --doc <path|dir|->, --text <str>, or pipe text on stdin",
              file=sys.stderr)
        sys.exit(2)
    return sys.stdin.read(), "stdin", [], "passthrough"


# ── heading → requirement anchors / split units ─────────────────────────────────

def _requirements_from_headings(text: str, doc_name: str):
    """All markdown headings as (heading, body-to-next-heading). Text before the first
    heading folds in as a leading '引言' anchor; no headings at all -> one fallback
    requirement carrying the whole text as body (so the subagent reads it semantically)."""
    matches = list(_HEADING_RX.finditer(text))
    if not matches:
        return [(doc_name or "全文", text.strip())]
    reqs = []
    pre = text[:matches[0].start()].strip()
    if pre:
        reqs.append(("引言", pre))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        reqs.append((m.group(2).strip(), text[start:end].strip()))
    return reqs


def _cap_name(heading: str, idx: int, seen: dict) -> str:
    base = _SAFE_NAME_RX.sub("-", heading).strip("-")[:40]
    if not base:
        base = "section"
    name = f"s{idx:02d}-{base}"
    n = 2
    while name in seen:
        name = f"s{idx:02d}-{base}-{n}"
        n += 1
    seen[name] = True
    return name


def _units_from_text(text: str, doc_name: str, split: bool):
    """Return [(cap_name, [(heading, body), ...]), ...]. Default = one 'freeform-review'
    unit over the whole doc; --split = one unit per top-level (# / ##) heading section."""
    if not split:
        return [("freeform-review", _requirements_from_headings(text, doc_name))]
    matches = list(_SPLIT_RX.finditer(text))
    if not matches:
        return [("freeform-review", _requirements_from_headings(text, doc_name))]
    units, seen = [], {}
    pre = text[:matches[0].start()].strip()
    if pre:
        cap = _cap_name(doc_name or "preamble", 0, seen)
        units.append((cap, [(doc_name or "引言", pre)]))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = m.group(2).strip()
        body = text[start:end].strip()
        cap = _cap_name(heading, i + 1, seen)
        units.append((cap, [(heading, body)]))
    return units


# ── change_context emit + check ─────────────────────────────────────────────────

def _candidate_controls(args, files):
    """Reuse sra's signal-1 candidate-control derivation when --rules is given."""
    if not args.rules:
        return [], "none"
    rules_path = Path(args.rules)
    try:
        inv_path, inv = _sra._resolve_rules(rules_path)
    except (OSError, ValueError) as e:
        print(f"error: could not read --rules {rules_path}: {e}", file=sys.stderr)
        sys.exit(1)
    if inv is None:
        print(f"error: --rules not a controls_inventory.json file or .mgh-init dir: {rules_path}",
              file=sys.stderr)
        sys.exit(1)
    ok, violations, _ = _sra._check_inventory(inv)
    if not ok:
        print("error: --rules inventory malformed; details: " + str(violations[:3]),
              file=sys.stderr)
        sys.exit(2)
    return _sra._candidate_controls(inv, files), str(inv_path)


def _emit_change_context(args, text, doc_name, degraded):
    project_root = _find_project_root(Path.cwd())
    out_dir = Path(args.out).resolve() if args.out else (project_root / ".mgh-srr")
    drafts_dir = out_dir / "drafts"

    units = _units_from_text(text, doc_name, args.split)
    capabilities, requirements, pending = [], [], []
    for cap_name, reqs in units:
        capabilities.append({"name": cap_name, "requirements": [h for h, _ in reqs]})
        for h, body in reqs:
            requirements.append({"capability": cap_name, "heading": h, "body": body})
        draft_path = (drafts_dir / f"{_SAFE_NAME_RX.sub('-', cap_name).strip('-') or 'unit'}.md").resolve()
        pending.append({
            "capability": cap_name,
            "draft_path": str(draft_path),
            "done_marker": str(draft_path.with_name(draft_path.name + ".done")),
        })

    # non-load-bearing hints (reused sra mechanical extractor)
    sens, roles, files, endpoints = _sra._extract_signals(text)
    candidate_controls, rules_source = _candidate_controls(args, files)

    # focus (dimension narrowing; reused sra resolver, closed-set-validated before any LLM)
    focus = _sra._resolve_focus(args)
    # sensitive-catalog (company masking policy; reused sra resolver, same shape as sra)
    catalog = _sra._resolve_sensitive_catalog(args)

    # shared cross-tool business memory (same file as sra)
    memory_path = project_root / ".mgh-sra" / "business_context.json"
    memory = None
    if memory_path.is_file():
        try:
            m = json.loads(memory_path.read_text(encoding="utf-8"))
            memory = m if isinstance(m, dict) else None
        except (OSError, ValueError):
            memory = None

    change_context = {
        "change": doc_name,
        "change_root": str(out_dir),
        "project_root": str(project_root),
        "capabilities": capabilities,
        "requirements": requirements,
        "tasks": [],
        "mentioned_files": files,
        "endpoints": endpoints,
        "data_fields": sens,
        "role_hints": roles,
        "candidate_controls": candidate_controls,
        "clarify_path": str((out_dir / "clarifications.json").resolve()),
        "pending": pending,
        "memory": memory,
        "rules_source": rules_source,
        "memory_source": str(memory_path) if memory is not None else "none",
        "dry_run": bool(args.dry_run),
        "truncated": False,
        "degraded": degraded,
        "focus": focus,
        "sensitive_catalog": catalog,
    }

    # structural invariant: pending draft paths under the project subtree (hook判树)
    bad = [p["draft_path"] for p in pending
           if not Path(p["draft_path"]).resolve().is_relative_to(project_root.resolve())]
    if bad:
        print(f"error: draft path drifted outside the project subtree: {bad}", file=sys.stderr)
        sys.exit(2)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "change_context.json").write_text(
        json.dumps(change_context, ensure_ascii=False, indent=2), encoding="utf-8")

    focus_desc = ("all9" if focus is None
                  else f"narrowed({len(focus['dimensions'])}d"
                       + (f",{sum(len(v) for v in focus['facets'].values())}f)"
                          if focus['facets'] else ")"))
    catalog_desc = ("none" if catalog is None
                    else f"{catalog['counts']['items']}items({catalog['counts']['categories']}cat)")
    print(f"[ingest_requirements] doc={doc_name} units={len(units)} reqs={len(requirements)} "
          f"endpoints={len(endpoints)} sens_fields={len(sens)} candidate_controls="
          f"{len(candidate_controls)} memory={'yes' if memory else 'no'} "
          f"focus={focus_desc} catalog={catalog_desc} degraded={degraded or 'no'} "
          f"-> {out_dir / 'change_context.json'}", file=sys.stderr)
    return change_context


def _run_check(path_arg: str):
    p = Path(path_arg)
    if not p.is_file():
        print(f"error: change_context.json not found: {p}", file=sys.stderr)
        return 1
    try:
        ctx = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: change_context.json malformed: {e}", file=sys.stderr)
        return 1
    violations = []
    if not isinstance(ctx, dict):
        violations.append("top-level JSON is not an object")
    else:
        for f in ("change", "change_root", "project_root", "capabilities",
                  "requirements", "pending", "clarify_path"):
            if f not in ctx:
                violations.append(f"missing top-level field: {f}")
        pr = ctx.get("project_root")
        pending = ctx.get("pending")
        if not isinstance(pending, list):
            violations.append("pending is not a list")
        else:
            for item in pending:
                if not isinstance(item, dict):
                    violations.append("pending item is not an object")
                    continue
                dp = item.get("draft_path")
                if not dp:
                    violations.append("pending item missing draft_path")
                    continue
                try:
                    rp = Path(dp).resolve()
                    if not rp.is_absolute():
                        violations.append(f"draft_path not absolute: {dp}")
                    elif pr and not rp.is_relative_to(Path(pr).resolve()):
                        violations.append(f"draft_path outside project subtree: {dp}")
                except (OSError, ValueError):
                    violations.append(f"draft_path unresolvable: {dp}")
        deg = ctx.get("degraded", [])
        if not isinstance(deg, list) or not all(isinstance(x, str) for x in deg):
            violations.append("degraded must be a list of strings")
        if "focus" in ctx:
            violations.extend(_sra.focus_scope.validate_resolved(ctx.get("focus")))
        if "sensitive_catalog" in ctx:
            violations.extend(_sra.sensitive_catalog.validate_resolved(ctx.get("sensitive_catalog")))
    ok = not violations
    summary = {"check": "srr-intake", "ok": ok, "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[ingest_requirements] --check {p}: ok={ok} violations={len(violations)}",
          file=sys.stderr)
    return 0 if ok else 2


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="r1 input adapter for /mgh-srr: freeform requirement doc -> "
                    "sra-shape change_context.json (reused middle engine)")
    ap.add_argument("--doc", metavar="PATH|DIR|-",
                    help="input file (.txt/.md/.csv/.json/.docx/.xlsx), DIR, or - for stdin")
    ap.add_argument("--text", default=None,
                    help="passthrough text used verbatim (no extraction, no degraded flag)")
    ap.add_argument("--rules", help="optional mgh-init controls_inventory.json FILE or output DIR")
    ap.add_argument("--focus", default=None,
                    help="optional security-dimension focus (inline JSON beginning with `{` or a "
                         "JSON file path; leading `@` tolerated) — same shape/semantics as /mgh-sra; "
                         "narrows the per-dimension scan. Omit = all 9 dimensions")
    ap.add_argument("--sensitive-catalog", default=None, metavar="INLINE-JSON|@PATH|-",
                    help="optional company masking-policy catalog (inline JSON beginning with `{`, "
                         "`-` for stdin, or a JSON file path; leading `@` tolerated) — same "
                         "shape/semantics as /mgh-sra; declares field types that MUST be masked. "
                         "Omit = legacy 6 facets only")
    ap.add_argument("--split", action="store_true",
                    help="split by markdown # / ## headings into multiple pending[] units")
    ap.add_argument("--out", help="output dir (default: <project>/.mgh-srr)")
    ap.add_argument("--dry-run", action="store_true",
                    help="produce change_context.json + summary only (orchestrator skips render/memory)")
    ap.add_argument("--no-interactive", action="store_true",
                    help="clarification uses default guesses (flag echoed for orchestrator)")
    ap.add_argument("--check", metavar="PATH", default=None,
                    help="intake validation only: validate change_context.json at PATH")
    args = ap.parse_args()

    if args.check is not None:
        if not args.check.strip():
            print("error: --check needs a change_context.json path", file=sys.stderr)
            return 2
        return _run_check(args.check.strip())

    text, doc_name, degraded, _mode = _acquire_text(args)
    ctx = _emit_change_context(args, text, doc_name, degraded)
    print(json.dumps(ctx, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
