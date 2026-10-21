#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
r"""
render_sdr_report — deterministic summary renderer for /mgh-sdr: collect the fan-out
units' draft JSONs (.done + parseable), dedup-merge findings by {dimension, route, file},
and render the human-facing Simplified-Chinese report as a SELF-CONTAINED single-file
HTML at the project root, plus `sdr_report_data.json` (canonical machine-facing data)
and `sdr_manifest.json` in the run dir.

One data assembly, two carriers: the renderer builds the whole report content into ONE
dict — ① it is written atomically as `<run-dir>/sdr_report_data.json` (the interface
downstream deterministic consumers read), ② the SAME dict is embedded into the HTML as
a `<script type="application/json">` block and rendered into the DOM by the page's own
inline JS. JSON-equivalence between the two carriers holds by construction; `--check`
parses and compares them, so the human page and the machine file can never drift.

Readability (human-face output discipline): every render also writes
`<run-dir>/readability_text_bundle.json` — the single text bundle (every merged
finding's human-face text fields) a best-effort readability-review subagent reads.
When `<run-dir>/readability_advisories.json` exists and parses (written by that
review after the first render, before an idempotent re-render), its normalized list
rides the data as `readability[]` and the report gains a default-collapsed 可读性自检
section; absent/unparsable/empty -> both omitted + a stderr note, exit code unchanged.
`--check` additionally scans the LLM-produced human-face field text (risk/suggestion/
repro/fix_diff) against the closed-set vocabulary (single source: sibling
`human_face_vocab.py`) — a hit prints a stderr count warning (field name + term) and
NEVER changes the exit code (soft quality; the deterministic-copy counterpart is
enforced by the regression suite, not here).

The HTML is fully self-contained: styles, scripts and data are all INLINE — zero
external references (no CDN, no web fonts, no images, no network), double-click opens
it in any modern browser over file://. Page interactions are plain vanilla JS:
severity/dimension table filters (view state only — the data files are NEVER
rewritten), P-NN in-page anchor jumps to the finding sections, and wheel-zoom /
drag-pan on the embedded SVG chain diagrams.

Findings merge: same {dimension, route, file} triple => ONE entry (line_hint union;
risk/suggestion/control_ref from the first occurrence — duplicates across units carry no
new information). `.failed` units do NOT block rendering: they are counted in
`counts.failed_units` + listed in `failed_units[]` (unit id + reason), and the report's
honesty-boundary section discloses "N review units failed; their coverage is unreviewed".
An unparsable draft of a .done unit takes the same path (failed_units, not a crash).

Report name: `mgh-sdr-<branch-safe>-<YYYYMMDD_HHMMSS>.html` at --repo root (tool name
fixed `mgh-sdr`; branch name filesystem-safe; second-resolution local timestamp). A same-
name report (re-run within the same second) is ATOMICALLY overwritten (idempotent);
across seconds both reports coexist (history is the user's to manage). Historical `.md`
reports are neither migrated nor rewritten.

Injection safety (finding text and slice text come from an LLM and quote target-repo
source — a real injection surface): the HTML skeleton is a static template with NO
per-run interpolation; all dynamic text reaches the DOM through textContent /
setAttribute (never string-concatenated into innerHTML), and the embedded JSON block
escapes `</` to `<\/` and `<!--` to `<\u0021--` (both legal JSON string escapes,
parse-identical) so finding text can neither terminate the block (`</script>`) nor
flip the HTML parser into the script-data-double-escaped state (which would swallow
the page's own render JS).

Source links: the 入口/调用链/位置 points render as links to repo-relative source files
(`<a href="rel/path#Lline">`, anchor omitted when no line); a path that cannot be
resolved inside the repo (outside it, empty/missing, leading `..`, spaces or parens)
degrades to the plain-text form — never a broken link. Resolution is purely lexical
(NEVER stats the target), so the report is reproducible across checkout states. Manifest
`rows[]` and data-file `rows[]` keep the PLAIN-TEXT short forms (no link syntax) — the
table links are a render projection of the same data.

Exit codes: 0 ok · 1 input error (run dir/drafts missing) · 2 misuse (argparse) or
--check violation (data file missing/unparsable, embedded-block drift, manifest/data
inconsistency).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/re/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import human_face_vocab  # sibling single source: closed-set vocabulary + scanner
import env_profile  # sibling: native-dispatch disclosure basis (form resolution)

TOOL_NAME = "mgh-sdr"
DATA_FILE = "sdr_report_data.json"
BUNDLE_FILE = "readability_text_bundle.json"
ADVISORIES_FILE = "readability_advisories.json"

# Default closed-set dimension keys (the report groups by whatever the drafts actually
# carry; free-text extension dimensions render under their own name).
DEFAULT_DIMENSIONS = ["vertical-authz", "horizontal-authz", "other-authz",
                      "sql-injection", "sensitive-data", "input-validation"]
_DIMENSION_LABEL = {
    "vertical-authz": "垂直越权",
    "horizontal-authz": "横向越权",
    "other-authz": "其他权限问题",
    "sql-injection": "SQL 注入",
    "sensitive-data": "敏感信息屏蔽",
    "input-validation": "输入校验",
    # free-text extension dimensions observed in real runs — display label ONLY; the
    # raw kebab key stays the machine join in data files/manifest, and an unseen
    # extension falls through to the raw key (never guess a translation)
    "architecture-layering": "架构分层",
}
_SEVERITY_LABEL = {"high": "高", "medium": "中", "low": "低", "info": "提示"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}

_DIMENSION_COL = {
    "vertical-authz": "垂直越权",
    "horizontal-authz": "横向越权",
    "other-authz": "其他权限",
    "sql-injection": "SQL注入",
    "sensitive-data": "敏感屏蔽",
    "input-validation": "输入校验",
    "architecture-layering": "架构分层",
}


def _dim_col(d: str) -> str:
    return _DIMENSION_COL.get(d, d)


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(s: str) -> str:
    return re.sub(r"[/\\:*?\"<>|]", "_", s).strip("_") or "branch"


def _load_drafts(run_dir: Path):
    """(drafts, failed_units). A unit counts as done iff its .done marker exists in
    markers/; a failed unit = .failed marker present (reason read from the marker body
    when parsable) OR a .done unit whose draft is missing/unparsable."""
    markers = run_dir / "markers"
    drafts_dir = run_dir / "drafts"
    drafts, failed = [], []
    done_ids, failed_ids = set(), {}
    if markers.is_dir():
        for p in sorted(markers.glob("*.done")):
            done_ids.add(p.name[:-len(".done")])
        for p in sorted(markers.glob("*.failed")):
            uid = p.name[:-len(".failed")]
            try:
                body = json.loads(p.read_text(encoding="utf-8"))
                reason = body.get("reason") or "unknown"
            except (OSError, ValueError, AttributeError):
                reason = "unknown"
            failed_ids[uid] = reason
    for uid in sorted(done_ids):
        dp = drafts_dir / f"{uid}.json"
        try:
            draft = json.loads(dp.read_text(encoding="utf-8"))
            if not isinstance(draft, dict):
                raise ValueError("draft not an object")
        except (OSError, ValueError) as e:
            failed.append({"unit": uid, "reason": f"draft unparsable: {e}"})
            continue
        findings = draft.get("findings", [])
        if not isinstance(findings, list):
            failed.append({"unit": uid, "reason": "findings field not a list"})
            continue
        drafts.append({"unit": uid, "findings": findings})
    for uid, reason in sorted(failed_ids.items()):
        failed.append({"unit": uid, "reason": reason})
    return drafts, failed


def _clean_repro(v):
    """`repro` is ONE plain string (how to call + with what passed + what happens);
    anything else (absent / blank / drifted shape) degrades to None — optional field,
    old drafts never hard-fail."""
    if isinstance(v, str) and v.strip():
        return v
    return None


def _clean_fix_diff(v):
    """`fix_diff` is 1-2 {before, after} pairs of non-empty strings (before copied
    verbatim from the slice, after the fixed form). Malformed pairs are dropped (not a
    crash); more than two pairs are cut; an all-malformed field degrades to None."""
    if not isinstance(v, list):
        return None
    out = []
    for item in v:
        if not isinstance(item, dict):
            continue
        b, a = item.get("before"), item.get("after")
        if isinstance(b, str) and b.strip() and isinstance(a, str) and a.strip():
            out.append({"before": b, "after": a})
        if len(out) == 2:
            break
    return out or None


def _merge_findings(drafts: list) -> dict:
    """Dedup-merge by {dimension, route, file}; line_hint union; first-writer-wins for
    the text fields (repro/fix_diff fall back to the first duplicate that carries them
    — structured evidence, more beats less). Returns {dimension: [finding...]}
    severity-sorted."""
    merged: dict[tuple, dict] = {}
    warned_sev = False
    for d in drafts:
        for f in d["findings"]:
            if not isinstance(f, dict):
                continue
            key = (str(f.get("dimension", "")), str(f.get("route", "")),
                   str(f.get("file", "")))
            hint = str(f.get("line_hint", "") or "")
            if key in merged:
                prev = merged[key]
                if hint and hint not in prev["line_hint"]:
                    prev["line_hint"] = ", ".join(x for x in (prev["line_hint"], hint) if x)
                if prev.get("repro") is None:
                    prev["repro"] = _clean_repro(f.get("repro"))
                if prev.get("fix_diff") is None:
                    prev["fix_diff"] = _clean_fix_diff(f.get("fix_diff"))
                continue
            sev = f.get("severity")
            if not (isinstance(sev, str) and sev in _SEVERITY_ORDER):
                if not isinstance(sev, str) and not warned_sev:
                    _eprint(f"[render_sdr_report] warning: non-string severity "
                            f"({type(sev).__name__}) in a finding degraded to 'medium'")
                    warned_sev = True
                sev = "medium"
            merged[key] = {
                "dimension": key[0], "route": key[1], "file": key[2],
                "severity": sev,
                "line_hint": hint,
                # anchor line (int, optional; old drafts lack it — degrade to file only)
                "line": f.get("line") if isinstance(f.get("line"), int)
                        and not isinstance(f.get("line"), bool) else None,
                "risk": str(f.get("risk", "") or ""),
                "suggestion": str(f.get("suggestion", "") or ""),
                "repro": _clean_repro(f.get("repro")),
                "fix_diff": _clean_fix_diff(f.get("fix_diff")),
                "control_ref": f.get("control_ref"),
            }
    by_dim: dict[str, list] = {}
    for (dim, _r, _f), rec in merged.items():
        by_dim.setdefault(dim, []).append(rec)
    for lst in by_dim.values():
        lst.sort(key=lambda r: (_SEVERITY_ORDER.get(r["severity"], 9), r["route"], r["file"]))
    return by_dim


def _render_chain(chain: list) -> str:
    """chain[] -> abbreviated one-cell chain text: `·` same-class continuation,
    `⤷` branch (branch_of host), `⇢` mapper XML terminal, `†` unchanged node. A linear
    chain reads as A → B → C → ⇢terminal; branch nodes are appended flat after the main
    line. Returns "" for an empty/absent chain (the row falls back to the entry form).
    This is the PLAIN-TEXT short form (manifest/data rows[]); the linked table cell is
    the same walk rendered as segments (`_chain_segments`)."""
    if not chain:
        return ""
    main = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is None]
    branches = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is not None]
    parts: list[str] = []
    prev_class = None
    for pos, (i, n) in enumerate(main):
        if pos == 0:
            parts.append(_node_text(n))
        elif n.get("change") == "external":
            parts.append(" ⇢" + _node_text(n))   # mapper XML terminal (XML not a graph node)
        elif n.get("file") and n.get("file") == prev_class:
            parts.append(" ·" + _node_text(n))   # same-class continuation
        else:
            parts.append(" → " + _node_text(n))
        prev_class = n.get("file")
    for _i, n in branches:
        sep = " ⇢" if n.get("change") == "external" else " ⤷"
        parts.append(sep + _node_text(n))
    return "".join(parts)


def _node_text(n: dict) -> str:
    txt = str(n.get("fqn_short", ""))
    if n.get("change") == "unchanged":
        txt = "†" + txt
    return txt


_ABS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_ABS_UNC = re.compile(r"^\\\\[^\\]")


def _href_of(file, line, repo: Path) -> str | None:
    """Repo-relative href for a source-file link (`rel#L<line>`, anchor omitted when
    line is absent), or None when the plain-text form is required. PURELY LEXICAL
    (NEVER stats the filesystem — the diff branch's files may not be checked out):
    an absolute path is rebased onto `repo` and only linked when inside its subtree;
    a relative path is taken as repo-root-relative; empty/missing, subtree-outside,
    leading `..`, paths with spaces or parentheses, and first-segment colons degrade
    to plain text — the error direction is "fewer links", never a broken one. A
    colon in the first segment (a scheme payload like `javascript:…` or a
    drive-relative form like `C:foo`) has no legitimate repo-relative meaning, and
    the check runs BOTH on the raw input and on the final normalized rel — normpath
    folds `//` to `/` and WHATWG URL parsing tolerates a single slash for special
    schemes, so normalization must not revive a scheme payload."""
    if not isinstance(file, str) or not file.strip():
        return None
    f = file.strip()
    if _ABS_DRIVE.match(f) or _ABS_UNC.match(f) or f.startswith("/"):
        nf = os.path.normpath(f)
        nr = os.path.normpath(str(repo))
        if os.path.normcase(nf) == os.path.normcase(nr):
            rel = "."
        else:
            try:
                rel = os.path.relpath(nf, nr)
            except ValueError:      # different drive (Windows) = outside the repo
                return None
        rel = rel.replace("\\", "/")
    else:
        if ":" in f.split("/")[0]:
            return None
        rel = os.path.normpath(f.replace("\\", "/")).replace("\\", "/")
    if not rel or rel == "." or rel.startswith(".."):
        return None
    if ":" in rel.split("/")[0]:
        return None
    if " " in rel or "(" in rel or ")" in rel:
        return None
    anchor = f"#L{line}" if isinstance(line, int) and not isinstance(line, bool) else ""
    return rel + anchor


def _seg(sep: str, n: dict, repo: Path) -> dict:
    """One chain-cell segment: the separator BEFORE the node (outside the link) plus the
    node's short text and its resolved link target. De-linkified join of all segments
    reproduces `_render_chain` byte-for-byte."""
    line = n.get("line")
    return {
        "sep": sep,
        "text": _node_text(n),
        "href": _href_of(n.get("file"), line, repo),
        "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
    }


def _chain_segments(chain: list, repo: Path) -> list[dict]:
    """chain[] -> linked table-cell segments (same walk as `_render_chain`; the `†`
    prefix stays inside the text, separators stay outside)."""
    if not chain:
        return []
    main = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is None]
    branches = [(i, n) for i, n in enumerate(chain) if n.get("branch_of") is not None]
    segs: list[dict] = []
    prev_class = None
    for pos, (i, n) in enumerate(main):
        if pos == 0:
            sep = ""
        elif n.get("change") == "external":
            sep = " ⇢"
        elif n.get("file") and n.get("file") == prev_class:
            sep = " ·"
        else:
            sep = " → "
        segs.append(_seg(sep, n, repo))
        prev_class = n.get("file")
    for _i, n in branches:
        sep = " ⇢" if n.get("change") == "external" else " ⤷"
        segs.append(_seg(sep, n, repo))
    return segs


# --- 章节三 SVG chain-graph layout (deterministic layered; JS draws + zooms) ---------

_GRAPH_NODE_W = 260
_GRAPH_NODE_H = 40
_GRAPH_GAP_X = 60
_GRAPH_GAP_Y = 26
_GRAPH_PAD = 12


def _layout_graph(unit: dict, route: str) -> dict | None:
    """章节三 data for ONE branched unit. Deterministic layered layout over chain[]:
    the entry sits at depth 0, a main-line node's depth = its position on the line,
    a branch/mapper-terminal node hangs off its host (branch_of index, fallback the
    previous array node — the dispatcher's encoding never nests) at depth(host)+1.
    Same-depth nodes stack vertically in first-appearance order — a conflict yields a
    row of its own, never an overlap. Coordinates feed the SVG viewBox; zoom/pan is the
    page JS's job. Mapper terminals (change=external) ride dashed edges."""
    chain = unit.get("chain") or []
    if not chain:
        return None
    main_idx = [i for i, n in enumerate(chain) if n.get("branch_of") is None]
    depth: dict[int, int] = {}
    for pos, i in enumerate(main_idx):
        depth[i] = pos
    edges: list[dict] = []
    for pos in range(1, len(main_idx)):
        dst = main_idx[pos]
        edges.append({"src": main_idx[pos - 1], "dst": dst,
                      "dashed": chain[dst].get("change") == "external"})
    for i, n in enumerate(chain):
        if n.get("branch_of") is None:
            continue
        bo = n.get("branch_of")
        src = bo if isinstance(bo, int) and 0 <= bo < len(chain) else i - 1
        edges.append({"src": src, "dst": i, "dashed": n.get("change") == "external"})
        depth[i] = depth.get(src, 0) + 1
    by_depth: dict[int, list[int]] = {}
    for i in sorted(depth):            # array order = first appearance
        by_depth.setdefault(depth[i], []).append(i)
    n_cols = len(by_depth)
    max_rows = max((len(v) for v in by_depth.values()), default=1)
    width = _GRAPH_PAD * 2 + n_cols * _GRAPH_NODE_W + max(0, n_cols - 1) * _GRAPH_GAP_X
    height = _GRAPH_PAD * 2 + max_rows * _GRAPH_NODE_H + max(0, max_rows - 1) * _GRAPH_GAP_Y
    entry = main_idx[0] if main_idx else -1
    nodes = []
    for d in sorted(by_depth):
        for row, i in enumerate(by_depth[d]):
            n = chain[i]
            label = str(n.get("label") or n.get("fqn_short", ""))
            if n.get("change") == "unchanged":
                label = "†" + label
            if i == entry:
                prefix = str(n.get("route") or route or "")
                if prefix:
                    label = prefix + " " + label
            f = n.get("file") if isinstance(n.get("file"), str) else ""
            line = n.get("line")
            title = ""
            if f:
                title = f"{f}:{line}" if isinstance(line, int) \
                        and not isinstance(line, bool) else f
            nodes.append({
                "id": i,
                "x": _GRAPH_PAD + d * (_GRAPH_NODE_W + _GRAPH_GAP_X),
                "y": _GRAPH_PAD + row * (_GRAPH_NODE_H + _GRAPH_GAP_Y),
                "w": _GRAPH_NODE_W, "h": _GRAPH_NODE_H,
                "label": label,
                "title": title,
                "terminal": n.get("change") == "external",
            })
    routes = str(unit.get("route", "")).split(";")
    return {"unit_id": unit.get("unit_id", ""), "route": routes[0] if routes else "",
            "width": width, "height": height, "nodes": nodes, "edges": edges}


def _sorted_units(units: list) -> list:
    """简报表 row order: interface by route asc (first route for merged units),
    standalone after by unit_id."""
    def key(u):
        routes = [r for r in str(u.get("route", "")).split(";") if r]
        return (0 if u.get("kind") == "interface" else 1,
                routes[0] if routes else "￿",
                str(u.get("unit_id", "")))
    return sorted(units, key=key)


def _is_failed(u: dict) -> bool:
    """The ONE 'skip failed units' predicate for the 简报表: a failed unit never
    becomes a row and never enters the frontend-column join. One named predicate,
    both consumers — rows built skipping failed units, then zipped against the
    FULL unit list, is exactly how the frontend columns ever misaligned."""
    return u.get("status") == "failed"


def _frontend_pair(route: str, exts: list) -> tuple[str, str]:
    """(是否前端接口, 前端使用) three-state by route join over route_hits[]:
    declared ∧ count>0 = 是/N 处; declared ∧ 0 = 否/—; route not in any route_hits[]
    (or no declared repo) = 未知/—. The join is EXACT string equality — route_hits
    are counted per exact route, so nested prefix routes (`/api/user` vs
    `/api/user/list`) must never cross-count. Multi-route units join on the MAIN
    route only (first ';'-segment, per spec; the entry column shows the others as
    `(+N)`)."""
    main = str(route).split(";")[0]
    if not main or not exts:
        return "未知", "—"
    found = False
    best = 0
    for e in exts:
        for rh in e.get("route_hits") or []:
            if not isinstance(rh, dict):
                continue
            rt = rh.get("route", "")
            if rt and rt == main:
                found = True
                best = max(best, rh.get("count", 0) or 0)
    if not found:
        return "未知", "—"
    if best > 0:
        return "是", f"{best} 处"
    return "否", "—"


def _row_dimensions(dims, rows) -> list:
    """Column set for the 简报表: default closed-set order first, then any free-text
    extension dimension found in the run face (each extension gets one column)."""
    seen = {d for r in rows for d in r["dim_refs"]}
    return [d for d in DEFAULT_DIMENSIONS if d in dims or d in seen] + \
        sorted(d for d in seen if d not in DEFAULT_DIMENSIONS and d in dims) + \
        sorted(d for d in seen if d not in DEFAULT_DIMENSIONS and d not in dims)


def _standalone_entry(u: dict, repo: Path) -> tuple[str, str | None]:
    """Entry for a no-route unit: the unit's own method-def short form (first chain
    node, else the unit_id stem). Returns (text, href) — the route-string entry never
    links, so only this path produces a linked entry."""
    chain = u.get("chain") or []
    if chain:
        n = chain[0]
        return _node_text(n), _href_of(n.get("file"), n.get("line"), repo)
    stem = str(u.get("unit_id", ""))
    return stem, None


def _build_rows(g_units: list, by_dim: dict, unit_refs: dict,
                external: list, repo: Path) -> tuple[list, list, list]:
    """简报表 data rows from grouping.json units[] (the renderer's row truth). Failed
    units NEVER become rows (their coverage is unreviewed — the honesty boundary
    discloses them instead). Returns (internal_rows, manifest_rows, row_links):
    manifest_rows = the plain-text projection (identical list in sdr_manifest.json and
    sdr_report_data.json), row_links = the per-row link projection the page JS renders
    (same data, same walk — never a second truth)."""
    rows, links = [], []
    for u in _sorted_units(g_units):
        if _is_failed(u):
            continue
        routes = [r for r in str(u.get("route", "")).split(";") if r]
        chain = u.get("chain") or []
        chain_txt = _render_chain(chain)
        segs = _chain_segments(chain, repo)
        if routes:
            entry_txt = routes[0] if len(routes) == 1 else routes[0] + f"(+{len(routes) - 1})"
            entry_rec = {"text": entry_txt, "href": None, "line": None}
            if not chain_txt:
                chain_txt = entry_txt
                segs = [{"sep": "", "text": entry_txt, "href": None, "line": None}]
        else:
            txt, href = _standalone_entry(u, repo)
            entry_rec = {"text": txt, "href": href, "line": None}
            if not chain_txt:
                chain_txt = txt
                segs = [{"sep": "", "text": txt, "href": href, "line": None}]
        uid = u.get("unit_id", "")
        refs = unit_refs.get(uid, set())
        dim_refs: dict[str, set] = {}
        for ref in refs:
            for dim, lst in by_dim.items():
                if any(f["pnum"] == ref for f in lst):
                    dim_refs.setdefault(dim, set()).add(ref)
        rows.append({
            "unit_id": uid,
            "kind": u.get("kind", ""),
            "entry": entry_txt if routes else entry_rec["text"],
            "chain": chain_txt,
            "frontend_is": "—",
            "frontend_count": "—",
            "dim_refs": dim_refs,
            "all_refs": refs,
        })
        links.append({"unit_id": uid, "entry": entry_rec, "chain": segs})
    # frontend two columns need the row route: fill after rows exist, pairing each
    # row with its OWN unit — the same failed filter the row walk used (_is_failed;
    # zipping against the full unit list shifts every row after a failed unit and
    # writes one unit's frontend values into another unit's row)
    for r, u in zip(rows, [u for u in _sorted_units(g_units) if not _is_failed(u)]):
        fis, fcnt = _frontend_pair(str(u.get("route", "")), external)
        r["frontend_is"], r["frontend_count"] = fis, fcnt
    manifest_rows = [{
        "unit_id": r["unit_id"], "entry": r["entry"], "chain": r["chain"],
        "frontend_is": r["frontend_is"], "frontend_count": r["frontend_count"],
        "issue_refs": sorted(r["all_refs"]),
    } for r in rows]
    return rows, manifest_rows, links


def _boundaries(by_dim, failed, catalog_source, external, dims, baseline_truncated,
                excluded=None, skipped=None, slimmed=None, dispatch=None):
    sk = [s for s in (skipped or []) if isinstance(s, str)]
    unapproved = [s[len("unapproved: "):].strip() for s in sk
                  if s.startswith("unapproved: ")]
    b = [
        "发现是 LLM 生成的待复核候选,不是已确认漏洞;每次运行非确定性,需人工复核后再处置。",
        "接口分组是注解启发式(Spring/JAX-RS/Servlet 常用注解):未识别的接口或调用链退入"
        "按目录归堆的兜底单元(分析粒度粗但覆盖不丢);非 java web 项目整体退化为按目录归堆"
        "的兜底分组。",
        "引用存量安全控制仅断言其「存在」,不断言其「有效」;控制有效性须另行验证。",
        "外部仓结论是检索时点快照,不保证前端分支已同步;同名分支缺失时回退其默认分支检索。",
        "存量设计参考按优先级截断后提供给评审(优先保留:接口授权 > SQL > 输入校验 > 敏感"
        "数据),低优先级细节可能未完整包含。",
        f"敏感目录来源:{catalog_source}("
        + ("项目提供的敏感字段清单" if catalog_source == "project"
           else "默认模板回退:使用内置 37 项模板,不按维度收窄")
        + ");目录外字段仅按回退规则识别,非穷尽所有敏感字段。",
    ]
    if excluded and excluded.get("count"):
        by_reason = excluded.get("by_reason") or {}
        detail = "、".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "-"
        b.append(f"排除披露:本次评审按固定排除清单排除了 {excluded['count']} 个文件(测试树/"
                 f"构建产物/静态资源/锁文件/构建脚本;{detail}),它们未进入评审;如需全量评审"
                 f"可用 --include-excluded 兜底重跑。")
    if dims and sorted(dims) != sorted(DEFAULT_DIMENSIONS):
        b.append(f"本次检查范围经参数收窄为 {len(dims)} 个维度({', '.join(dims)}),"
                 f"范围外维度未覆盖。")
    if failed:
        b.append(f"{len(failed)} 个评审单元失败({'、'.join(u['unit'] for u in failed[:5])}"
                 f"{'…' if len(failed) > 5 else ''}),其覆盖范围本次未复核;建议重跑补齐。")
    if baseline_truncated:
        b.append("存量设计参考发生截断(超出字节预算),部分存量设计段落未参与本次评审。")
    # Only when this run actually slimmed something: the unit's diff body, file list and
    # hunk locators are intact, but its descriptive context was cut, so a "no finding" from
    # it is weaker evidence than from a normal unit. Silent degradation is not allowed.
    if slimmed:
        shown = "、".join(slimmed[:5]) + ("…" if len(slimmed) > 5 else "")
        b.append(f"输入完整度披露:本次有 {len(slimmed)} 个复核单元因评审内容超出字节预算,其"
                 f"辅助上下文块(注解上下文 / 符号表)被确定性截断({shown})——这些单元的 diff "
                 f"正文、文件清单与改动定位头仍完整,但方法/路由的定位信息少于常规单元,"
                 f"来自它们的「无问题」结论的充分性应据此打折。")
    if external:
        b.append(f"外部仓检索覆盖 {len(external)} 个声明仓;未声明/不可达的外部仓不在本次评审"
                 f"范围内。")
    if dispatch:
        b.append("派发形态为原生子代理波次派发(opencode 宿主会话内并发):止损为波次粒度"
                 "(无进程树杀,挂死单元由看门狗按静默/超时阈值中止兜底);编排父会话是单点"
                 "(进度在磁盘,恢复会话经状态查询接上,已完成单元不重做);单元任务文件路径经"
                 "编排器转述存在残余错抄面(越树路径被运行域守卫拦截,树内错配单元经重枚举回"
                 "待派,重派代价有界)。")
    if unapproved:
        shown = "、".join(unapproved[:3]) + ("…" if len(unapproved) > 3 else "")
        b.append(f"外部仓未授权:存量设计声明了 {len(unapproved)} 个外部目录({shown}),"
                 f"未经用户确认写入项目配置,本次未检索;前端相关检查未覆盖,经用户确认后"
                 f"重跑可覆盖。")
    return b


def _load_grouping(run_dir: Path) -> dict:
    """grouping.json (diff_group run record) when present — carries the grouping
    stats the report's overview section discloses. Missing/old layout -> {}."""
    gp = run_dir / "grouping.json"
    try:
        g = json.loads(gp.read_text(encoding="utf-8"))
        return g if isinstance(g, dict) else {}
    except (OSError, ValueError):
        return {}


def _dispatch_disclosure(repo: Path, run_dir: Path):
    """Native-dispatch disclosure basis, CONJUNCTIVE: the run dir carries the
    native plan artifact AND the shared resolver (`consumer=sdr`) resolves the
    native form — an explicit profile `native`, or the opencode host default for
    the sdr consumer (no profile file needed). Anything else (no plan artifact,
    runner form, corrupt profile) -> None, and the report keeps byte-identical
    output — absent means not applicable, so every pre-native run is unchanged.
    The evidence string names WHICH basis applied (profile choice vs host
    default) so a reader can tell a configured run from a default one. A corrupt
    profile degrades to no disclosure here (this is a report reader, not a
    dispatch consumer; the fail-closed startup contract belongs to the
    dispatch-facing scripts, which refuse to run on a corrupt profile in the
    first place)."""
    plan = run_dir / "native_plan.json"
    if not plan.is_file():
        return None
    try:
        res = env_profile.resolve(repo, consumer="sdr")
    except Exception:
        return None
    if res.form != "native":
        return None
    evidence = ("native_plan.json + env-profile dispatch_mode=native"
                if res.source == env_profile.SOURCE_PROFILE
                else "native_plan.json + opencode host default (no env profile)")
    return {"form": "native",
            "source": res.source,
            "host_face": res.host_face,
            "consumer": res.consumer,
            "profile_exists": res.profile_exists,
            "plan_artifact": str(plan.resolve()),
            "evidence": evidence}


def _overview_and_details(grouping: dict, excluded, cg_stats) -> tuple[list, list]:
    """分组概览 as plain-word main sentences + the call-edge quality numbers tucked into
    a default-collapsed 分组诊断 details block. Main sentences carry the grouping-shape
    counts a reviewer needs at a glance; the collapsed details keep every diagnostic
    number (nothing lost, default view quiet). grouping.json fields are read-only
    inputs — the machine face is untouched. English classification keys become the
    reader's words: interface -> 接口单元, standalone -> 独立文件单元."""
    overview: list = []
    details: list = []
    g_counts = grouping.get("counts") or {}
    if g_counts:
        overview.append({
            "k": "评审分组",
            "v": (f"{g_counts.get('interface', 0)} 个接口单元、"
                  f"{g_counts.get('standalone', 0)} 个独立文件单元"
                  f"(共 {grouping.get('total', '?')} 个)")})
    if cg_stats:
        if grouping.get("codegraph"):
            overview.append({
                "k": "调用链分析",
                "v": (f"启用——{cg_stats.get('anchors_changed', 0)} 个变更接口作为分组入口、"
                      f"{cg_stats.get('anchors_upstream', 0)} 处改动挂接到未变更接口、"
                      f"同入口链路合并 {cg_stats.get('chain_merged', 0)} 组")})
        else:
            overview.append({"k": "调用链分析", "v": "未启用(按接口注解与目录归堆分组)"})
        if cg_stats.get("edges_captured") is not None:
            details.append(f"捕获调用边 {cg_stats.get('edges_captured', 0)} 条"
                           f"(变更集内 {cg_stats.get('edges_in_changed_set', 0)} 条)")
        if cg_stats.get("symbols_queried") is not None:
            details.append(f"查询变更符号 {cg_stats.get('symbols_queried')} 个")
    if isinstance(excluded, dict) and excluded.get("count"):
        by_reason = excluded.get("by_reason") or {}
        detail = "、".join(f"{k} {v}" for k, v in sorted(by_reason.items())) or "-"
        overview.append({
            "k": "排除文件",
            "v": (f"{excluded['count']} 个({detail})(未进入评审,详见诚实边界)")})
    return overview, details


def _json_embed(data: dict) -> str:
    r"""The data dict serialized for the HTML embed: every `</` becomes `<\/` — a legal
    JSON string escape that parses identically — so a `</script>` literal carried in
    LLM/切片 text can never terminate the host `<script>` block, and every `<!--`
    becomes `<\u0021--` so the literal sequence can never flip the HTML parser into
    the script-data-double-escaped state (there the real `</script>` is ignored and
    the page's own render JS is swallowed as data)."""
    return (json.dumps(data, ensure_ascii=False)
            .replace("</", "<\\/")
            .replace("<!--", "<\\u0021--"))


def _readability_bundle(findings: list) -> dict:
    """The single text bundle for the best-effort readability review: every merged
    finding's human-face text fields, keyed by P-NN (+ its dimension label and route
    for context). Written on EVERY render; the review subagent reads exactly this file
    and nothing else."""
    items = []
    for f in findings:
        item = {"pnum": f["pnum"], "dimension_label": f["dimension_label"],
                "route": f["route"]}
        for k in ("risk", "suggestion", "repro"):
            if f.get(k):
                item[k] = f[k]
        if f.get("fix_diff"):
            item["fix_diff"] = f["fix_diff"]
        items.append(item)
    return {"v": 1, "items": items}


def _load_advisories(run_dir: Path):
    """Normalized readability advisories, or None when absent / unparsable / malformed /
    empty. Best-effort by contract: a missing or broken review only costs the report
    its optional readability section — never a failure, never a different exit code."""
    p = run_dir / ADVISORIES_FILE
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"[render_sdr_report] note: {ADVISORIES_FILE} unparsable ({e}); "
                f"可读性自检小节省略")
        return None
    items = raw.get("advisories") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        _eprint(f"[render_sdr_report] note: {ADVISORIES_FILE} shape malformed; "
                f"可读性自检小节省略")
        return None
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({"term": str(it.get("term", "")), "field": str(it.get("field", "")),
                    "pnum": str(it.get("pnum", "")), "why": str(it.get("why", ""))})
    return out or None


def _vocab_warn(findings: list):
    """Advisory closed-set scan over the LLM-produced human-face field text
    (risk/suggestion/repro/fix_diff). Soft quality by contract: stderr count warning
    (field name + term) only — NEVER a different exit code, NEVER a rewrite."""
    hits: dict = {}
    for f in findings:
        for field in ("risk", "suggestion", "repro"):
            t = f.get(field) or ""
            for term in human_face_vocab.scan_text(t, domains=("sdr",)):
                k = (field, term)
                hits[k] = hits.get(k, 0) + 1
        for pair in f.get("fix_diff") or []:
            for side in ("before", "after"):
                for term in human_face_vocab.scan_text(str(pair.get(side) or ""),
                                                       domains=("sdr",)):
                    k = ("fix_diff", term)
                    hits[k] = hits.get(k, 0) + 1
    if hits:
        summary = ", ".join(f"{field}×{n}「{term}」"
                            for (field, term), n in sorted(hits.items()))
        _eprint(f"[render_sdr_report] warning: 人类面文本命中内部词闭集(仅告警:退出码不变、"
                f"文本未改写;词条单源 human_face_vocab): {summary}")


# ============================================================================
# Self-contained HTML template: skeleton + CSS + page JS, section-commented.
# Static string — NO per-run interpolation. The run data enters at exactly one
# point (the __MGH_DATA_JSON__ marker inside the application/json block) and is
# rendered into the DOM by the JS below. All dynamic text reaches the DOM via
# textContent/setAttribute (auto-escaping) — string-concatenated innerHTML is
# never used for data, so LLM/切片 text cannot inject markup.
# ============================================================================
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>mgh-sdr 安全设计符合性复核报告</title>
<!-- section: css -->
<style>
  :root {
    --ink: #1f2430; --muted: #6b7280; --line: #d9dde5; --bg: #f7f8fa;
    --card: #ffffff; --accent: #1d4ed8;
    --high: #b91c1c; --medium: #b45309; --low: #1d4ed8; --info: #4b5563;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 0 16px 64px; background: var(--bg); color: var(--ink);
         font: 15px/1.65 "Segoe UI", "Microsoft YaHei", system-ui, sans-serif; }
  main { max-width: 1280px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 24px 0 4px; }
  h2 { font-size: 18px; margin: 36px 0 10px; padding-bottom: 6px;
       border-bottom: 2px solid var(--line); }
  h3 { font-size: 15px; margin: 18px 0 6px; }
  .banner { margin: 14px 0 0; padding: 10px 14px; border: 1px solid #f59e0b;
            border-left-width: 5px; background: #fffbeb; border-radius: 6px; }
  .muted { color: var(--muted); font-size: 13px; }
  ul.meta { margin: 8px 0; padding-left: 22px; }
  /* 章节一 summary table */
  .filters { margin: 10px 0; display: flex; gap: 10px; align-items: center; }
  .filters select { padding: 4px 8px; border: 1px solid var(--line); border-radius: 5px;
                    background: var(--card); font: inherit; }
  table.summary { border-collapse: collapse; width: 100%; background: var(--card);
                  font-size: 13.5px; }
  table.summary th, table.summary td { border: 1px solid var(--line);
                                       padding: 6px 9px; text-align: left;
                                       vertical-align: top; }
  table.summary thead th { position: sticky; top: 0; background: #eef1f6; z-index: 1; }
  table.summary tr.hidden { display: none; }
  td.chain { font-size: 13px; }
  td.chain .seg { display: inline-block; margin-right: 4px; overflow-wrap: anywhere; }
  .chain-main { margin-bottom: 3px; }
  .chain-sub { font-size: 11.5px; color: var(--muted); padding-left: 10px;
               border-left: 2px solid var(--line); line-height: 1.8; margin-top: 2px; }
  td a { color: var(--accent); text-decoration: none; }
  td a:hover { text-decoration: underline; }
  span.yes { color: var(--high); font-weight: 600; }
  span.no { color: var(--muted); }
  /* 章节二 findings */
  .finding { background: var(--card); border: 1px solid var(--line);
             border-left-width: 5px; border-radius: 6px; padding: 10px 14px;
             margin: 10px 0; scroll-margin-top: 60px; }
  .finding.sev-high   { border-left-color: var(--high); }
  .finding.sev-medium { border-left-color: var(--medium); }
  .finding.sev-low    { border-left-color: var(--low); }
  .finding.sev-info   { border-left-color: var(--info); }
  .finding h3 { margin: 0 0 6px; }
  .finding ul { margin: 0; padding-left: 20px; }
  .finding a { color: var(--accent); text-decoration: none; }
  .finding a:hover { text-decoration: underline; }
  /* 章节三 SVG chain graphs */
  .graph { background: var(--card); border: 1px solid var(--line); border-radius: 6px;
           margin: 10px 0; padding: 6px; }
  .graph svg { width: 100%; height: auto; display: block; cursor: grab;
               touch-action: none; }
  .graph svg.dragging { cursor: grabbing; }
  .graph svg .edge { fill: none; stroke: #64748b; stroke-width: 1.6; }
  .graph svg .edge.dashed { stroke-dasharray: 6 4; }
  .graph svg .node rect { fill: #eef2f9; stroke: #94a3b8; rx: 6; }
  .graph svg .node.terminal rect { fill: #fdf6ec; stroke: #d97706;
                                   stroke-dasharray: 4 3; }
  .graph svg .node text { font-size: 13px; fill: var(--ink); }
  .graph svg .node:hover rect { stroke: var(--accent); }
  /* 折叠明细(分组诊断 / 可读性自检)与修复对比 */
  details { margin: 8px 0; }
  details summary { cursor: pointer; font-weight: 600; }
  .fixdiff pre { margin: 4px 0; padding: 8px 10px; background: #f3f4f6;
                 border: 1px solid var(--line); border-radius: 5px;
                 font: 12.5px/1.5 Consolas, "Courier New", monospace;
                 white-space: pre-wrap; overflow-wrap: anywhere; }
  .fixdiff-label { font-size: 12px; color: var(--muted); margin-top: 6px; }
</style>
</head>
<body>
<main>
  <h1>mgh-sdr 安全设计符合性复核报告</h1>
  <div class="banner">发现是 LLM 生成的待复核候选,不是已确认漏洞。合并/处置前须人工复核。</div>
  <section id="sec-overview">
    <h2>报告头部</h2>
    <div id="head-meta"></div>
    <div id="grouping-overview"></div>
  </section>
  <section id="sec-summary">
    <h2>章节一 简报表</h2>
    <div id="summary"></div>
    <p class="muted">阅读方式:维度列只标 是/否 + <code>P-NN</code> 编号,点击编号跳转
    「章节二 问题详述」对应条目。`†` 未变更节点 · `⤷` 分支 · `⇢` mapper XML 终端 ·
    `·` 同类延续。筛选为纯视图态,不改写本报告携带的数据。</p>
  </section>
  <section id="sec-findings">
    <h2>章节二 问题详述</h2>
    <div id="findings"></div>
  </section>
  <section id="sec-graphs">
    <h2>章节三 分支调用链图</h2>
    <div id="graphs"></div>
  </section>
  <section id="sec-ok-units">
    <h2>无问题单元</h2>
    <ul id="ok-units"></ul>
  </section>
  <section id="sec-boundaries">
    <h2>诚实边界</h2>
    <ul id="boundaries"></ul>
  </section>
</main>
<!-- section: data (the ONLY per-run content; `</` -> `<\/` and `<!--` -> `<\u0021--` by the renderer) -->
<script type="application/json" id="mgh-data">__MGH_DATA_JSON__</script>
<!-- section: page js (vanilla; renders everything above from the embedded data) -->
<script>
(function () {
  "use strict";
  var DATA = JSON.parse(document.getElementById("mgh-data").textContent);

  // No string-level HTML assembly exists on this page: every dynamic value reaches
  // the DOM through textContent or setAttribute (both auto-isolate text from
  // markup), so finding text can never inject elements or attributes.

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function a(href, text) {
    var n = document.createElement("a");
    n.setAttribute("href", href);
    n.textContent = String(text);
    return n;
  }

  // ---- report head + grouping overview ------------------------------------
  function renderMeta(d) {
    var m = d.meta;
    var box = document.getElementById("head-meta");
    var ul = el("ul", "meta");
    ul.appendChild(el("li", null, "分支:" + m.branch + "(base:" + m.base + ")"));
    ul.appendChild(el("li", null, "时间:" + m.time_display));
    ul.appendChild(el("li", null, "检查维度:" + m.dimensions.join(", ")));
    ul.appendChild(el("li", null, "敏感目录来源:" + m.sensitive_catalog_source
      + m.catalog_note));
    ul.appendChild(el("li", null, "外部仓结论:" + m.external_headline));
    if (m.dispatch) ul.appendChild(el("li", null, "派发形态:" + m.dispatch.form
      + "(原生子代理波次派发;计划工件在场,证据:" + m.dispatch.evidence + ")"));
    ul.appendChild(el("li", null, "单元:" + m.units_total + " 个(done "
      + m.units_done + " / failed " + m.units_failed + ");findings 去重后 "
      + m.findings_total + " 条(高 " + m.by_severity.high + " / 中 "
      + m.by_severity.medium + " / 低 " + m.by_severity.low + " / 提示 "
      + m.by_severity.info + ")"));
    box.appendChild(ul);
    var ov = document.getElementById("grouping-overview");
    if (m.overview && m.overview.length) {
      ov.appendChild(el("h3", null, "分组概览"));
      var oul = el("ul", "meta");
      m.overview.forEach(function (o) {
        oul.appendChild(el("li", null, o.k + ":" + o.v));
      });
      ov.appendChild(oul);
      // 分组质量信号(调用边计数等)收进默认折叠的明细:信息不丢,默认视图不闹
      if (m.overview_details && m.overview_details.length) {
        var det = document.createElement("details");
        det.appendChild(el("summary", null, "分组诊断"));
        var dul = el("ul", "meta");
        m.overview_details.forEach(function (t) {
          dul.appendChild(el("li", null, t));
        });
        det.appendChild(dul);
        ov.appendChild(det);
      }
    }
  }

  // ---- 章节一 summary table (filters are view-state only) ------------------
  var F = { sev: "", dim: "" };

  function entryCell(td, rec) {
    if (rec.href) td.appendChild(a(rec.href, rec.text));
    else td.appendChild(el("span", null, rec.text));
  }
  function chainCell(td, rl) {
    if (!rl.chain.length) { entryCell(td, rl.entry); return; }
    // Two-tier display: the main line (entry → flow · same-class) reads at full size;
    // branch (⤷) and mapper-terminal (⇢) segments drop into an indented, smaller
    // sub-block. Segments keep their order and glyphs — read top-to-bottom the cell
    // reproduces the plain-text chain exactly (the rows[] machine projection).
    var main = [], sub = [];
    rl.chain.forEach(function (s) {
      (s.sep === " ⤷" || s.sep === " ⇢" ? sub : main).push(s);
    });
    function emit(parent, segs) {
      segs.forEach(function (s) {
        var sp = document.createElement("span");
        sp.className = "seg";
        if (s.sep) sp.appendChild(document.createTextNode(s.sep));
        if (s.href) sp.appendChild(a(s.href, s.text));
        else sp.appendChild(el("span", null, s.text));
        parent.appendChild(sp);
      });
    }
    var mainDiv = el("div", "chain-main");
    emit(mainDiv, main);
    td.appendChild(mainDiv);
    if (sub.length) {
      var subDiv = el("div", "chain-sub");
      emit(subDiv, sub);
      td.appendChild(subDiv);
    }
  }
  function dimCell(td, row, dim, byP) {
    var refs = row.issue_refs.filter(function (p) {
      return byP[p] && byP[p].dimension === dim;
    }).sort();
    if (!refs.length) { td.appendChild(el("span", "no", "否")); return; }
    td.appendChild(el("span", "yes", "是 ["));
    refs.forEach(function (p, i) {
      if (i) td.appendChild(document.createTextNode(", "));
      td.appendChild(a("#" + p, p));     // in-page anchor jump to 章节二
    });
    td.appendChild(el("span", "yes", "]"));
  }

  function renderTable(d) {
    var box = document.getElementById("summary");
    if (!d.rows.length) {
      box.appendChild(el("p", "muted",
        "(无 grouping.json 单元数据:旧 run 布局,仅问题详述可用)"));
      return;
    }
    var byP = {};
    d.findings.forEach(function (f) { byP[f.pnum] = f; });
    var links = {};
    d.row_links.forEach(function (rl) { links[rl.unit_id] = rl; });

    var bar = el("div", "filters");
    bar.appendChild(el("span", null, "筛选:"));
    var sevSel = el("select");
    [["", "全部严重度"], ["high", "高"], ["medium", "中"], ["low", "低"],
     ["info", "提示"]].forEach(function (o) {
      var op = document.createElement("option");
      op.value = o[0]; op.textContent = o[1];
      sevSel.appendChild(op);
    });
    var dimSel = el("select");
    var op0 = document.createElement("option");
    op0.value = ""; op0.textContent = "全部维度";
    dimSel.appendChild(op0);
    d.dimension_columns.forEach(function (c) {
      var op = document.createElement("option");
      op.value = c; op.textContent = d.meta.dimension_cols[c] || c;
      dimSel.appendChild(op);
    });
    var count = el("span", "muted");
    bar.appendChild(sevSel); bar.appendChild(dimSel); bar.appendChild(count);
    box.appendChild(bar);

    var t = el("table", "summary");
    var cols = ["接口/方法入口", "调用链", "是否前端接口", "前端使用"].concat(
      d.dimension_columns.map(function (c) { return d.meta.dimension_cols[c] || c; }));
    var thead = el("thead"), hr = el("tr");
    cols.forEach(function (cname) { hr.appendChild(el("th", null, cname)); });
    thead.appendChild(hr); t.appendChild(thead);
    var tbody = el("tbody");
    var trs = d.rows.map(function (row) {
      var tr = el("tr");
      var rl = links[row.unit_id] || { entry: { text: row.entry }, chain: [] };
      var tdE = el("td"); entryCell(tdE, rl.entry); tr.appendChild(tdE);
      var tdC = el("td", "chain"); chainCell(tdC, rl); tr.appendChild(tdC);
      tr.appendChild(el("td", null, row.frontend_is));
      tr.appendChild(el("td", null, row.frontend_count));
      d.dimension_columns.forEach(function (dim) {
        var td = el("td"); dimCell(td, row, dim, byP); tr.appendChild(td);
      });
      tbody.appendChild(tr);
      return { row: row, tr: tr };
    });
    t.appendChild(tbody); box.appendChild(t);

    function matches(row) {
      if (F.sev && !row.issue_refs.some(function (p) {
            return byP[p] && byP[p].severity === F.sev; })) return false;
      if (F.dim && !row.issue_refs.some(function (p) {
            return byP[p] && byP[p].dimension === F.dim; })) return false;
      return true;
    }
    function apply() {
      var n = 0;
      trs.forEach(function (x) {
        if (matches(x.row)) { x.tr.classList.remove("hidden"); n++; }
        else x.tr.classList.add("hidden");
      });
      count.textContent = "显示 " + n + " / " + trs.length + " 行";
    }
    sevSel.addEventListener("change", function () { F.sev = sevSel.value; apply(); });
    dimSel.addEventListener("change", function () { F.dim = dimSel.value; apply(); });
    apply();
  }

  // ---- 章节二 findings (id = P-NN: the anchor the table jumps to) ----------
  function renderFindings(d) {
    var box = document.getElementById("findings");
    if (!d.findings.length) {
      box.appendChild(el("p", null,
        "本次检查范围内未产出任何问题记录;不代表「无风险」,仅代表在本次检查范围与存量"
        + "设计参考下未命中。"));
      return;
    }
    d.findings.forEach(function (f) {
      var card = el("div", "finding sev-" + f.severity);
      card.setAttribute("id", f.pnum);
      card.appendChild(el("h3", null, f.pnum + " · " + f.dimension_label + " · "
        + (f.route || "(独立变更单元)") + " · " + f.severity_label));
      var ul = el("ul");
      var li = el("li");
      li.appendChild(document.createTextNode("位置:"));
      if (f.loc.href) li.appendChild(a(f.loc.href, f.loc.text));
      else li.appendChild(el("span", null, f.loc.text));
      ul.appendChild(li);
      if (f.risk) ul.appendChild(el("li", null, "风险:" + f.risk));
      // 复现方式:怎么调 + 传什么 + 看到什么(数据缺该字段 = 省略,不报错)
      if (f.repro) ul.appendChild(el("li", null, "复现方式:" + f.repro));
      if (f.suggestion) ul.appendChild(el("li", null, "建议:" + f.suggestion));
      // 修复对比:每组「修改前 / 修改后」两块上下堆叠的 <pre>,代码文本走
      // textContent 注入(与 finding 正文同一防注入路线)
      if (f.fix_diff && f.fix_diff.length) {
        var liFd = el("li");
        liFd.appendChild(document.createTextNode("修复对比:"));
        var wrap = el("div", "fixdiff");
        f.fix_diff.forEach(function (pair) {
          wrap.appendChild(el("div", "fixdiff-label", "修改前"));
          var preB = document.createElement("pre");
          preB.textContent = String(pair.before);
          wrap.appendChild(preB);
          wrap.appendChild(el("div", "fixdiff-label", "修改后"));
          var preA = document.createElement("pre");
          preA.textContent = String(pair.after);
          wrap.appendChild(preA);
        });
        liFd.appendChild(wrap);
        ul.appendChild(liFd);
      }
      if (f.control_ref) ul.appendChild(el("li", null, "命中存量控制:" + f.control_ref));
      card.appendChild(ul);
      box.appendChild(card);
    });
  }

  // ---- 章节三 SVG chain graphs (layout coords computed by the renderer) ----
  // XML namespace identifier — a name, not a fetched resource; nothing on this
  // page loads from the network.
  var SVGNS = "http://www.w3.org/2000/svg";

  function buildSvg(g) {
    var wrap = el("div", "graph");
    var svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", "0 0 " + g.width + " " + g.height);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    var byId = {};
    g.nodes.forEach(function (n) { byId[n.id] = n; });
    g.edges.forEach(function (e) {
      var s = byId[e.src], t = byId[e.dst];
      if (!s || !t) return;
      var sx = s.x + s.w, sy = s.y + s.h / 2, dx = t.x, ty = t.y + t.h / 2;
      var mx = (sx + dx) / 2;
      var p = document.createElementNS(SVGNS, "path");
      p.setAttribute("d", "M " + sx + " " + sy + " H " + mx + " V " + ty + " H " + dx);
      p.setAttribute("class", "edge" + (e.dashed ? " dashed" : ""));
      svg.appendChild(p);
    });
    g.nodes.forEach(function (n) {
      var grp = document.createElementNS(SVGNS, "g");
      grp.setAttribute("class", "node" + (n.terminal ? " terminal" : ""));
      var r = document.createElementNS(SVGNS, "rect");
      r.setAttribute("x", n.x); r.setAttribute("y", n.y);
      r.setAttribute("width", n.w); r.setAttribute("height", n.h);
      grp.appendChild(r);
      var tx = document.createElementNS(SVGNS, "text");
      tx.setAttribute("x", n.x + 10);
      tx.setAttribute("y", n.y + n.h / 2);
      tx.setAttribute("dominant-baseline", "middle");
      tx.textContent = n.label;
      grp.appendChild(tx);
      if (n.title) {
        var ti = document.createElementNS(SVGNS, "title");
        ti.textContent = n.title;          // hover: file:line
        grp.appendChild(ti);
      }
      svg.appendChild(grp);
    });
    attachZoomPan(svg, g);
    wrap.appendChild(svg);
    wrap.appendChild(el("p", "muted", "滚轮缩放 · 按住拖拽平移"));
    return wrap;
  }

  function attachZoomPan(svg, g) {
    var vb = { x: 0, y: 0, w: g.width, h: g.height };
    function apply() {
      svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.w + " " + vb.h);
    }
    svg.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var r = svg.getBoundingClientRect();
      var px = vb.x + (ev.clientX - r.left) / r.width * vb.w;
      var py = vb.y + (ev.clientY - r.top) / r.height * vb.h;
      var k = ev.deltaY > 0 ? 1.15 : 1 / 1.15;
      var nw = Math.min(Math.max(vb.w * k, 200), 20000);
      var nh = vb.h * (nw / vb.w);
      vb.x = px - (px - vb.x) * (nw / vb.w);
      vb.y = py - (py - vb.y) * (nh / vb.h);
      vb.w = nw; vb.h = nh;
      apply();
    }, { passive: false });
    var drag = null;
    svg.addEventListener("pointerdown", function (ev) {
      drag = { x: ev.clientX, y: ev.clientY };
      svg.setAttribute("class", "dragging");
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      var r = svg.getBoundingClientRect();
      vb.x -= (ev.clientX - drag.x) / r.width * vb.w;
      vb.y -= (ev.clientY - drag.y) / r.height * vb.h;
      drag = { x: ev.clientX, y: ev.clientY };
      apply();
    });
    ["pointerup", "pointerleave"].forEach(function (t) {
      svg.addEventListener(t, function () {
        drag = null;
        svg.removeAttribute("class");
      });
    });
  }

  function renderGraphs(d) {
    var box = document.getElementById("graphs");
    if (!d.chain_graphs.length) {
      box.appendChild(el("p", "muted", "(无带分支的单元:线性链不画图)"));
      return;
    }
    d.chain_graphs.forEach(function (g) {
      box.appendChild(el("h3", null, g.unit_id + " · " + g.route));
      box.appendChild(buildSvg(g));
    });
  }

  // ---- 收尾 sections --------------------------------------------------------
  function renderOkUnits(d) {
    var box = document.getElementById("ok-units");
    if (d.ok_units.length) {
      d.ok_units.forEach(function (u) {
        box.appendChild(el("li", null, u + "(复核通过,merge 前放行参考)"));
      });
    } else {
      box.appendChild(el("li", null, "(无:全部单元均产出问题记录或失败)"));
    }
  }
  function renderBoundaries(d) {
    var box = document.getElementById("boundaries");
    d.boundaries.forEach(function (b) { box.appendChild(el("li", null, b)); });
  }

  // 可读性自检:默认折叠的小节,列一次读者模拟评审的建议(仅建议、须人确认;评审缺席
  // = 整节不渲染,报告其余内容不变)。section 由 JS 动态创建——缺席时文件里没有该小节。
  function renderReadability(d) {
    var items = d.readability;
    if (!items || !items.length) return;
    var main = document.querySelector("main");
    var sec = el("section");
    sec.id = "sec-readability";
    var det = el("details");
    det.appendChild(el("summary", null, "可读性自检(" + items.length
      + " 条建议;来自一次读者模拟评审,仅建议、采纳由人确认)"));
    var ul = el("ul");
    items.forEach(function (adv) {
      var where = (adv.pnum ? adv.pnum + " " : "") + (adv.field || "");
      ul.appendChild(el("li", null, "「" + adv.term + "」(" + where + "):" + adv.why));
    });
    det.appendChild(ul);
    sec.appendChild(det);
    main.appendChild(sec);
  }

  renderMeta(DATA);
  renderTable(DATA);
  renderFindings(DATA);
  renderGraphs(DATA);
  renderOkUnits(DATA);
  renderBoundaries(DATA);
  renderReadability(DATA);
})();
</script>
</body>
</html>
"""


def _render(repo: Path, run_dir: Path, ctx: dict, by_dim: dict, drafts, failed,
            out_dir: Path):
    branch = ctx.get("branch", "")
    base = ctx.get("base", "")
    dims = ctx.get("dimensions") or DEFAULT_DIMENSIONS
    catalog_source = ctx.get("sensitive_catalog_source", "default-template")
    external = ctx.get("external_repos", [])
    skipped = [s for s in ctx.get("external_skipped", []) if isinstance(s, str)]
    unapproved = [s[len("unapproved: "):].strip() for s in skipped
                  if s.startswith("unapproved: ")]
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S")
    report_path = repo / f"{TOOL_NAME}-{_safe_name(branch)}-{ts}.html"

    total = sum(len(v) for v in by_dim.values())
    by_sev = {"high": 0, "medium": 0, "low": 0, "info": 0}
    for lst in by_dim.values():
        for f in lst:
            by_sev[f["severity"]] += 1
    ok_units = [d["unit"] for d in drafts if not d["findings"]]
    grouping = _load_grouping(run_dir)
    excluded = grouping.get("excluded") or ctx.get("excluded") or {}
    cg_stats = grouping.get("codegraph_stats") or ctx.get("codegraph_stats") or {}
    # units whose descriptive context blocks were truncated to fit the slice byte budget
    # (diff_group's gate): this run's input-completeness disclaimer, empty when none.
    slimmed = [str(u.get("unit_id")) for u in (grouping.get("pending") or [])
               if isinstance(u, dict) and u.get("slimmed")]

    # P-NN global numbering: severity asc (high→info), then (route, file) for a
    # deterministic order that is stable across runs.
    flat: list[dict] = []
    for dim_list in by_dim.values():
        flat.extend(dim_list)
    flat.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 9), f["route"], f["file"]))
    pnums: dict[tuple, str] = {}
    for i, f in enumerate(flat, 1):
        pnums[(f["dimension"], f["route"], f["file"])] = f"P-{i:02d}"
        f["pnum"] = f"P-{i:02d}"
    # unit -> its finding refs (a unit "owns" a finding when a draft with that unit id
    # carried the same triple; shared triples = shared P-NN across rows, by design)
    unit_refs: dict[str, set] = {}
    for d in drafts:
        for f in d["findings"]:
            if not isinstance(f, dict):
                continue
            key = (str(f.get("dimension", "")), str(f.get("route", "")),
                   str(f.get("file", "")))
            if key in pnums:
                unit_refs.setdefault(d["unit"], set()).add(pnums[key])

    g_units = grouping.get("units")
    if g_units:
        rows, manifest_rows, row_links = _build_rows(g_units, by_dim, unit_refs,
                                                     external, repo)
    else:
        rows, manifest_rows, row_links = [], [], []
    dim_cols = _row_dimensions(dims, rows)

    findings = []
    for f in flat:   # flat is already severity-asc then route/file = P-NN order
        loc_txt = f["file"]
        if f.get("line"):
            loc_txt += f":{f['line']}"
        elif f.get("line_hint"):
            loc_txt += f"({f['line_hint']})"
        rec = {
            "pnum": f["pnum"],
            "dimension": f["dimension"],
            "dimension_label": _DIMENSION_LABEL.get(f["dimension"], f["dimension"]),
            "severity": f["severity"],
            "severity_label": _SEVERITY_LABEL.get(f["severity"], f["severity"]),
            "route": f["route"],
            "loc": {"text": loc_txt, "href": _href_of(f["file"], f.get("line"), repo),
                    "line": f.get("line")},
            "line_hint": f["line_hint"],
            "risk": f["risk"],
            "suggestion": f["suggestion"],
            "control_ref": f.get("control_ref"),
        }
        # optional human-face fields: present keys only (absent = not applicable; old
        # drafts degrade silently)
        if f.get("repro"):
            rec["repro"] = f["repro"]
        if f.get("fix_diff"):
            rec["fix_diff"] = f["fix_diff"]
        findings.append(rec)

    # 章节三: real branches only = a NON-external node carries branch_of (a java
    # fan-out). branch_of on an `external` mapper-terminal node is encoding, NOT a
    # branch — a linear chain whose only branch_of is its ⇢ terminal draws NO diagram.
    branch_units = [u for u in g_units or []
                    if any(n.get("branch_of") is not None
                           and n.get("change") != "external"
                           for n in (u.get("chain") or []))]
    chain_graphs = []
    for u in branch_units:
        g = _layout_graph(u, str(u.get("route", "")).split(";")[0])
        if g:
            chain_graphs.append(g)

    if external:
        ext_headline = (f"{', '.join(e.get('slug', '?') for e in external)}"
                        f"({len(external)} 仓,检索时点快照)")
    elif unapproved:
        ext_headline = "无(外部仓未授权,前端相关检查未覆盖)"
    else:
        ext_headline = "无(未声明 / 不可达降级,前端相关检查未覆盖)"
    catalog_note = ("(项目提供的敏感字段清单)" if catalog_source == "project"
                    else "(默认模板回退:内置 37 项模板,不按维度收窄)")

    # 分组概览: plain-word main sentences + collapsed 分组诊断 details (grouping quality
    # at a glance — observable without opening grouping.json). Rides grouping.json in
    # the run dir (older layouts: the section is simply absent).
    overview, overview_details = _overview_and_details(grouping, excluded, cg_stats)

    # native-dispatch disclosure: conjunctive basis (plan artifact + profile);
    # None = no disclosure field anywhere (byte-identical pre-native output)
    dispatch = _dispatch_disclosure(repo, run_dir)

    boundaries = _boundaries(by_dim, failed, catalog_source, external, dims,
                             ctx.get("baseline_truncated", False), excluded,
                             skipped, slimmed, dispatch)

    data = {
        "v": 1,
        "meta": {
            "tool": TOOL_NAME,
            "branch": branch,
            "base": base,
            "ts": ts,
            "time_display": now.strftime("%Y-%m-%d %H:%M:%S %z"),
            "dimensions": list(dims),
            "dimension_cols": {d: _dim_col(d) for d in dim_cols},
            "sensitive_catalog_source": catalog_source,
            "catalog_note": catalog_note,
            "external_repos": [{"slug": e.get("slug"), "path": e.get("path"),
                                "branch_sync_note": e.get("branch_sync_note")}
                               for e in external],
            "external_headline": ext_headline,
            "units_total": len(drafts) + len(failed),
            "units_done": len(drafts),
            "units_failed": len(failed),
            "findings_total": total,
            "by_severity": by_sev,
            "overview": overview,
            "overview_details": overview_details,
        },
        "dimension_columns": dim_cols,
        "rows": manifest_rows,
        "row_links": row_links,
        "findings": findings,
        "chain_graphs": chain_graphs,
        "ok_units": ok_units,
        "boundaries": boundaries,
    }
    if dispatch:
        data["meta"]["dispatch"] = dispatch

    # best-effort readability review consumption: a parsable advisory file (written by
    # the review subagent between the first render and this re-render) rides the data
    # and the report; anything else just omits the section (exit code untouched)
    advisories = _load_advisories(run_dir)
    if advisories:
        data["readability"] = advisories
        _eprint(f"[render_sdr_report] readability advisories: {len(advisories)} 条"
                f"(已并入报告「可读性自检」小节;仅建议,采纳由人确认)")

    html_text = _HTML_TEMPLATE.replace("__MGH_DATA_JSON__", _json_embed(data))

    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / (report_path.name + ".tmp")
    tmp.write_text(html_text, encoding="utf-8")
    dtmp = out_dir / (DATA_FILE + ".tmp")
    dtmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")

    manifest = {
        "tool": TOOL_NAME,
        "branch": branch,
        "base": base,
        "dimensions": dims,
        "sensitive_catalog_source": catalog_source,
        "external_repos": [{"slug": e.get("slug"), "path": e.get("path"),
                            "branch_sync_note": e.get("branch_sync_note")}
                           for e in external],
        "rows": manifest_rows,
        "counts": {
            "units": len(drafts) + len(failed),
            "interfaces": ctx.get("counts_interface", None),
            "standalone": ctx.get("counts_standalone", None),
            "findings": total,
            "findings_by_severity": by_sev,
            "failed_units": len(failed),
            "excluded_files": excluded.get("count", 0) if isinstance(excluded, dict) else 0,
        },
        "boundaries": boundaries,
        "failed_units": failed,
        "report": str(report_path),
        "ts": ts,
    }
    if dispatch:
        manifest["dispatch"] = dispatch
    mtmp = out_dir / "sdr_manifest.json.tmp"
    mtmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    # atomic placement (same-volume os.replace): a same-second re-run overwrites cleanly
    os.replace(tmp, report_path)
    os.replace(dtmp, out_dir / DATA_FILE)
    os.replace(mtmp, out_dir / "sdr_manifest.json")
    # the readability text bundle: written on EVERY render (run dir, not out_dir — a
    # fixed convention path so the review subagent's contract never depends on flags)
    btmp = run_dir / (BUNDLE_FILE + ".tmp")
    btmp.write_text(json.dumps(_readability_bundle(findings), ensure_ascii=False,
                               indent=1) + "\n", encoding="utf-8")
    os.replace(btmp, run_dir / BUNDLE_FILE)
    _eprint(f"[render_sdr_report] readability_text_bundle: {run_dir / BUNDLE_FILE} "
            f"({len(findings)} items)")
    return report_path, manifest, data


def _run(args) -> dict:
    run_dir = Path(args.run_dir).resolve()
    repo = Path(args.repo).resolve()
    if not run_dir.is_dir():
        _eprint(f"error: run dir not found: {run_dir}\n"
                f"recipe: run diff_group.py --materialize first (creates the run dir "
                f"layout); a zero-diff run renders a 'no changes' report without drafts.")
        sys.exit(1)
    if not repo.is_dir():
        _eprint(f"error: --repo not a directory: {repo}")
        sys.exit(1)
    ctx_path = run_dir / "context.json"
    if not ctx_path.is_file():
        _eprint(f"error: context.json not found in {run_dir}\n"
                f"recipe: run `sdr_context.py --repo <abs> --run-dir <abs>` before "
                f"render (it produces context.json).")
        sys.exit(1)
    try:
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed context.json: {e}")
        sys.exit(1)

    drafts, failed = _load_drafts(run_dir)
    by_dim = _merge_findings(drafts)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir
    report_path, manifest, _data = _render(repo, run_dir, ctx, by_dim, drafts, failed,
                                           out_dir)
    _eprint(f"[render_sdr_report] report={report_path}")
    _eprint(f"[render_sdr_report] findings={manifest['counts']['findings']} "
            f"failed_units={manifest['counts']['failed_units']} "
            f"boundaries={len(manifest['boundaries'])}")
    result = {"report": str(report_path),
              "data": str(out_dir / DATA_FILE),
              "manifest": str(out_dir / "sdr_manifest.json"),
              "counts": manifest["counts"], "boundaries": len(manifest["boundaries"]),
              "checked": False}
    return result


def _check(run_dir: Path) -> int:
    violations = []
    mp = run_dir / "sdr_manifest.json"
    if not mp.is_file():
        _eprint(f"error: sdr_manifest.json not found in {run_dir}\n"
                f"recipe: run `render_sdr_report.py --run-dir <abs> --repo <abs>` first.")
        return 2
    try:
        m = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed sdr_manifest.json: {e}")
        return 2
    # canonical data file: present + parseable
    dp = run_dir / DATA_FILE
    data = None
    if not dp.is_file():
        violations.append(f"{DATA_FILE} missing (the canonical data file)")
    else:
        try:
            data = json.loads(dp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            violations.append(f"malformed {DATA_FILE}: {e}")
    # draft truth vs manifest counts
    drafts, failed = _load_drafts(run_dir)
    by_dim = _merge_findings(drafts)
    # soft-quality vocabulary scan over the LLM-produced human-face field text: stderr
    # count warning only — the exit code below is driven exclusively by the hard
    # consistency violations, never by model wording
    _vocab_warn([f for lst in by_dim.values() for f in lst])
    actual = sum(len(v) for v in by_dim.values())
    if m.get("counts", {}).get("findings") != actual:
        violations.append(f"counts.findings mismatch (manifest "
                          f"{m.get('counts', {}).get('findings')}, drafts {actual})")
    if m.get("counts", {}).get("failed_units") != len(failed):
        violations.append(f"counts.failed_units mismatch (manifest "
                          f"{m.get('counts', {}).get('failed_units')}, disk {len(failed)})")
    if len(m.get("boundaries", [])) < 6:
        violations.append(f"boundaries must have >=6 entries (got "
                          f"{len(m.get('boundaries', []))})")
    report = m.get("report", "")
    if not report or not Path(report).is_file():
        violations.append(f"report file missing: {report!r}")
    else:
        text = Path(report).read_text(encoding="utf-8")
        if Path(report).suffix.lower() != ".html":
            violations.append(f"report is not a .html file: {report}")
        if "诚实边界" not in text:
            violations.append("report missing honesty-boundary section")
        if report.replace("\\", "/").find("/openspec/") >= 0:
            violations.append("report path under openspec/ (NEVER allowed)")
        # text-level structure assertions (no browser): the embedded data block and
        # the per-section anchor markers the page's in-page navigation relies on
        for marker in ('id="mgh-data"', 'id="sec-overview"', 'id="sec-summary"',
                       'id="sec-findings"', 'id="sec-graphs"', 'id="sec-ok-units"',
                       'id="sec-boundaries"'):
            if marker not in text:
                violations.append(f"report missing section marker {marker}")
        # two carriers, one dict: the embedded block must parse to the data file's
        # exact content, and the manifest rows[] must equal the data rows[]
        if data is not None:
            mm = re.search(r'<script type="application/json" id="mgh-data">(.*?)'
                           r'</script>', text, re.S)
            if not mm:
                violations.append("report has no embedded data block")
            else:
                try:
                    embedded = json.loads(mm.group(1))
                except ValueError as e:
                    embedded = None
                    violations.append(f"embedded data block not parseable JSON: {e}")
                if embedded is not None and embedded != data:
                    violations.append("embedded data block != sdr_report_data.json "
                                      "(carrier drift)")
            if m.get("rows") != (data.get("rows") if isinstance(data, dict) else None):
                violations.append("manifest rows[] != data file rows[] (projection "
                                  "drift)")
    # the renderer writes the report at the repo root (--repo) and the manifest in
    # the run dir; a manifest pointing the report anywhere else is tampering or
    # misuse. The repo root comes from grouping.json when present, else from the
    # standard run-dir shape <repo>/.mgh-sdr/runs/<ts>; when neither yields one,
    # this check is skipped (no repo to compare against — never a false positive).
    repo_root = None
    gp = run_dir / "grouping.json"
    if gp.is_file():
        try:
            g = json.loads(gp.read_text(encoding="utf-8"))
            if isinstance(g.get("repo"), str) and g["repo"].strip():
                repo_root = Path(g["repo"])
        except (OSError, ValueError):
            pass
    if repo_root is None and run_dir.parent.name == "runs" \
            and run_dir.parent.parent.name == ".mgh-sdr":
        repo_root = run_dir.parent.parent.parent
    if repo_root is not None:
        rep = os.path.normcase(os.path.normpath(str(Path(report).resolve())))
        root = os.path.normcase(os.path.normpath(str(repo_root)))
        try:
            outside = os.path.relpath(rep, root).startswith("..")
        except ValueError:      # different drive (Windows) = outside
            outside = True
        if outside:
            violations.append(f"report not inside repo root: {report}")
    if violations:
        _eprint(f"error: render_sdr_report --check: {len(violations)} violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: re-run `render_sdr_report.py --run-dir <abs> --repo <abs>` "
                "(deterministic; same-second overwrite is atomic).")
        return 2
    _eprint(f"[render_sdr_report] --check ok ({run_dir})")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="deterministic summary renderer for /mgh-sdr: dedup-merge fan-out "
                    "draft findings and render the self-contained single-file HTML "
                    "report + canonical data JSON for the run")
    ap.add_argument("--run-dir", help="absolute run dir (<repo>/.mgh-sdr/runs/<ts>)")
    ap.add_argument("--repo", help="absolute target repo root (report lands here)")
    ap.add_argument("--out-dir", help="manifest/data output dir (default: the run dir)")
    ap.add_argument("--check", metavar="<run-dir>",
                    help="validate a run dir's data file, manifest + report "
                         "(fail-loud exit 2)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        if args.run_dir or args.repo:
            _eprint("error: --check takes only <run-dir>")
            return 2
        return _check(Path(args.check).resolve())
    if not args.run_dir or not args.repo:
        _eprint("error: --run-dir and --repo are required (or use --check <run-dir>)")
        return 2

    result = _run(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
