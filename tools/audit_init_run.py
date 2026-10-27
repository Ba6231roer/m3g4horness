#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""audit_init_run.py — deterministic post-run audit of a completed mgh-init run.

Single-file, read-only, stdlib-only (R2). Runs on any cwd; safe to carry into an
offline environment and run directly with `py audit_init_run.py`.

What it checks (on a finished <init-dir>, default <target>/.mgh-init):
  A. per-tier checkpoint reconciliation: .done/.failed markers vs *.json records
     (orphan markers, records without markers, strict JSON parse failures)
  B. T2: shard record parse; synthesis.json absent is NORMAL (marker-only design)
  C. T4: consistency.json parse + post-T4 purity re-lint via the installed
     assemble_rules.py --check (skipped when the script is not found)
  D. anchors: inventory evidence + rule-file anchor tokens -> file exists,
     line in range, symbol substrings present; evidence snippet containment
  E. reconciliation: inventory categories vs rule detail files; per-control
     representation in its category file; AGENTS.md managed-block links
  F. run health: init_manifest boundaries/failures, report.md presence,
     run_config flags, scout_plan batch count
  G. optional --scan-config: count declarative config files (xml/properties/…)
     containing conservative security-declaration patterns (hypothesis A4)

Outputs:
  stdout      <=16 ASCII KEY=value lines (hand-copy friendly; no paths/names)
  --json-out  full detail JSON (default <init-dir>/audit_report.json; STAYS
              LOCAL — it contains repo paths and control names, do not export)

Exit codes: 0 = report produced (findings do NOT flip the exit code);
            2 = usage error (bad args / init-dir missing).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

TIERS = ("scout", "t1", "t2", "t3", "t4")
# t2 terminal marker whose content file does not exist by design (single-context
# and rollup both only touch synthesis.json.done; artifact is inventory).
MARKER_ONLY_BASES = {"synthesis.json"}
SRC_EXT = ("java", "kt", "scala", "groovy", "py", "cs", "js", "ts", "php", "rb")
RULE_ANCHOR_SYMBOL = re.compile(
    r"[\w./\\\-]+\.(?:%s)::[\w$.\-]+" % "|".join(SRC_EXT))
RULE_ANCHOR_LINE = re.compile(
    r"[\w./\\\-]+\.(?:%s):\d{1,7}" % "|".join(SRC_EXT))
DECL_EXTS = {".xml", ".properties", ".ini", ".yml", ".yaml", ".xsd"}
DECL_PATTERNS = (
    "permissionid=", "<securitypermission", "<securitygroup", "intercept-url",
    "shiro", "authc", "haspermission", "security-constraint", "login-config",
)
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "target", "build", "dist",
             ".mgh-init", ".opencode", ".claude", ".gradle", "__pycache__"}


def _norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def load_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return True, json.load(fh), ""
    except Exception as exc:  # noqa: BLE001 — audit must never crash on bad files
        return False, None, "%s: %s" % (type(exc).__name__, exc)


def read_text(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return True, fh.read(), "utf-8"
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="gbk") as fh:
                return True, fh.read(), "gbk"
        except Exception:  # noqa: BLE001
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return True, fh.read(), "utf-8?replace"
    except Exception as exc:  # noqa: BLE001
        return False, "", "%s: %s" % (type(exc).__name__, exc)


class SourceCache:
    """Bounded read cache for source files referenced by anchors/snippets."""

    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self.used = 0
        self._text: dict[str, tuple[bool, str, str]] = {}
        self._lines: dict[str, int] = {}

    def text(self, key: str):
        if key in self._text:
            return self._text[key]
        try:
            size = os.path.getsize(key)
        except OSError:
            self._text[key] = (False, "", "missing")
            return self._text[key]
        if self.used + size > self.budget:
            self._text[key] = (False, "", "budget")
            return self._text[key]
        ok, data, enc = read_text(Path(key))
        if ok:
            self.used += size
        self._text[key] = (ok, data, enc)
        return self._text[key]

    def line_count(self, key: str):
        if key not in self._lines:
            ok, data, _ = self.text(key)
            self._lines[key] = data.count("\n") + 1 if ok else 0
        return self._lines[key]


class BasenameIndex:
    """Unique-basename fallback resolver (one walk over the target tree).

    Inventory/T1 evidence paths are not always repo-root-relative; when an
    anchor path fails to resolve directly, a UNIQUE basename match recovers
    it (counted separately — it signals a path-format issue, not fabrication).
    """

    def __init__(self, target: Path):
        self.map: dict[str, list[str]] = {}
        for root, dirs, names in os.walk(target):
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
            for n in names:
                self.map.setdefault(n.lower(), []).append(
                    os.path.join(root, n))

    def unique(self, name: str):
        hits = self.map.get(name.lower(), [])
        return hits[0] if len(hits) == 1 else None


def resolve_path(raw: str, target: Path, bidx: BasenameIndex | None = None):
    """Resolve an anchor path token against the repo root; case-insensitive FS
    fallback; unique-basename fallback last (returns (path|None, how))."""
    raw = raw.replace("\\", "/").strip().strip('"').strip("'")
    if raw.startswith("./"):
        raw = raw[2:]
    if not raw:
        return None, "empty"
    p = Path(raw)
    if not p.is_absolute():
        p = target / raw
    p = Path(os.path.normpath(str(p)))
    if p.is_file():
        return p, "exact"
    parent = p.parent
    if parent.is_dir():
        want = p.name.lower()
        try:
            for entry in os.listdir(parent):
                if entry.lower() == want:
                    return parent / entry, "case"
        except OSError:
            pass
    if bidx is not None:
        got = bidx.unique(p.name)
        if got:
            return Path(got), "basename"
    return None, "missing"


def parse_anchor_token(tok):
    """Evidence/anchor token -> (path, line|None, symbol|None).

    Accepted forms (t1-record-schema.md + rules-detail.md):
      'path::Cls.method'  rule-file anchor (double colon)
      'path:Cls.method'   T1/inventory evidence (SINGLE colon symbol form)
      'path:123'          line anchor
      'path'              bare path
    """
    tok = tok.strip().strip('"').strip("'").replace("\\", "/")
    if "::" in tok:
        path, sym = tok.split("::", 1)
        return path, None, sym
    m = re.match(r"^(.*):(\d{1,7})$", tok)
    if m and ("/" in m.group(1)
              or re.search(r"\.(?:%s)$" % "|".join(SRC_EXT), m.group(1), re.I)):
        return m.group(1), int(m.group(2)), None
    m = re.match(r"^(.*\.(?:%s)):([^:]+)$" % "|".join(SRC_EXT), tok, re.I)
    if m:
        return m.group(1), None, m.group(2)
    return tok, None, None


def scan_tier(cp_dir: Path):
    """One tier dir (one-level recursion) -> marker/record reconciliation.

    Markers whose base does NOT end in .json are classified as `orphan_other`
    (artifact-attached markers, e.g. rule files in native dispatch) instead of
    missing records — a design shape, not an anomaly.
    """
    st = {"done": 0, "failed": 0, "records": 0, "json_bad": 0,
          "orphan_done": 0, "orphan_other": 0, "rec_no_done": 0,
          "orphan_ids": [], "marker_other_ids": [], "rec_no_done_ids": [],
          "bad_files": [], "failed_reasons": [], "markers_terminal_only": 0,
          "files_total": 0, "pack_markers": 0}
    names: dict[str, Path] = {}
    try:
        for entry in sorted(os.listdir(cp_dir)):
            p = cp_dir / entry
            if p.is_dir():
                try:
                    for sub in sorted(os.listdir(p)):
                        if (p / sub).is_file():
                            names[entry + "/" + sub] = p / sub
                except OSError:
                    pass
            elif p.is_file():
                names[entry] = p
    except OSError:
        return st
    st["files_total"] = len(names)
    record_names = {n for n in names if n.endswith(".json")}
    done_json, done_other = [], []
    for name in names:
        if name.endswith(".done"):
            base = name[: -len(".done")]
            st["done"] += 1
            leaf = base.split("/")[-1]
            if leaf in MARKER_ONLY_BASES:
                st["markers_terminal_only"] += 1
            elif base.endswith(".json"):
                done_json.append(base)
            else:
                done_other.append(base)
        elif name.endswith(".failed"):
            st["failed"] += 1
    for name in names:
        if name.endswith(".failed"):
            ok, data, _ = read_text(names[name])
            if ok and data.strip():
                st["failed_reasons"].append(data.strip()[:200])
    for base in done_json:
        if base.startswith("pack__") or base.startswith("pack::"):
            # pack dispatch units are marker-only BY DESIGN (init_tier's own
            # orphan audit skips the same prefix); member records are real
            st["pack_markers"] += 1
        elif base not in record_names:
            st["orphan_done"] += 1
            st["orphan_ids"].append(base)
    for base in done_other:
        st["orphan_other"] += 1
        if len(st["marker_other_ids"]) < 20:
            st["marker_other_ids"].append(base)
    for name in sorted(record_names):
        st["records"] += 1
        if not ((name + ".done") in names
                or (name[: -len(".json")] + ".failed") in names
                or (name + ".failed") in names):
            st["rec_no_done"] += 1
            if len(st["rec_no_done_ids"]) < 20:
                st["rec_no_done_ids"].append(name)
        ok, _, err = load_json(names[name])
        if not ok:
            st["json_bad"] += 1
            if len(st["bad_files"]) < 20:
                st["bad_files"].append({"file": name, "error": err[:200]})
    return st


def pack_reconcile(t1_st: dict, cp_dir: Path):
    """Match orphan t1 marker ids to record contents via the trailing sha8.

    Marker filenames are SANITIZED cluster ids (`::` is unsafe on NTFS), so a
    plain substring match against raw ids inside records never hits; the
    trailing 8-hex sha8 survives sanitization and is a safe join key.
    """
    ids = t1_st.get("orphan_ids") or []
    if not ids:
        return 0
    blob, total = [], 0
    for name in sorted(os.listdir(cp_dir)):
        if name.endswith(".json"):
            ok, data, _ = read_text(cp_dir / name)
            if ok:
                total += len(data)
                blob.append(data)
                if total > 60_000_000:
                    break
    text = "\n".join(blob)
    hit = 0
    for i in ids:
        stem = i[: -len(".json")] if i.endswith(".json") else i
        tail = stem[-8:]
        if re.fullmatch(r"[0-9a-f]{8}", tail) and tail in text:
            hit += 1
    return hit


def audit_anchors(inventory: dict | None, rule_files: dict, target: Path,
                  cache: SourceCache):
    """Inventory evidence + rule-file anchor tokens -> existence/line/symbol/snippet."""
    m = {"total": 0, "ok": 0, "bad_file": 0, "bad_line": 0, "bad_symbol": 0,
         "unchecked": 0, "examples": [], "snippets_checked": 0,
         "snippet_mismatch": 0, "snippet_examples": [], "by_basename": 0}
    bidx_holder: list[BasenameIndex] = []

    def check_token(tok, line, sym, snippet, origin):
        m["total"] += 1
        path, how = resolve_path(tok, target)
        if path is None:
            # lazy unique-basename fallback (first miss builds the index)
            if not bidx_holder:
                try:
                    bidx_holder.append(BasenameIndex(target))
                except OSError:
                    bidx_holder.append(None)
            if bidx_holder[0] is not None:
                got = bidx_holder[0].unique(Path(tok.replace("\\", "/")).name)
                if got:
                    path, how = Path(got), "basename"
        if path is None:
            m["bad_file"] += 1
            if len(m["examples"]) < 20:
                m["examples"].append({"origin": origin, "token": tok[:160],
                                      "kind": "file_missing"})
            return
        if how == "basename":
            m["by_basename"] += 1
        key = str(path)
        if line is not None:
            n = cache.line_count(key)
            if n and not (1 <= line <= n):
                m["bad_line"] += 1
                if len(m["examples"]) < 20:
                    m["examples"].append({"origin": origin, "token": tok[:160],
                                          "kind": "line_out_of_range",
                                          "lines": n})
                return
        ok, text, enc = cache.text(key)
        if not ok:
            m["unchecked"] += 1
            return
        if sym is not None:
            parts = [p for p in sym.replace("(", " ").split(".") if p.strip()]
            if parts and not all(_norm_ws(p) and _norm_ws(p) in text for p in parts):
                m["bad_symbol"] += 1
                if len(m["examples"]) < 20:
                    m["examples"].append({"origin": origin, "token": tok[:160],
                                          "kind": "symbol_absent", "sym": sym[:80]})
                return
        if snippet:
            m["snippets_checked"] += 1
            frag = _norm_ws(snippet)[:60]
            if frag and frag not in _norm_ws(text):
                m["snippet_mismatch"] += 1
                if len(m["snippet_examples"]) < 20:
                    m["snippet_examples"].append(
                        {"origin": origin, "file": tok[:160], "frag": frag[:80]})
                return
        m["ok"] += 1

    if inventory:
        for idx, ctl in enumerate(inventory.get("controls") or []):
            if not isinstance(ctl, dict):
                continue
            ev = ctl.get("evidence")
            items = ev if isinstance(ev, list) else ([ev] if ev else [])
            for item in items[:10]:
                if isinstance(item, dict):
                    tok = str(item.get("file") or item.get("path") or "")
                    line = item.get("line")
                    line = int(line) if isinstance(line, str) and line.isdigit() else line
                    snip = str(item.get("snippet") or item.get("evidence_snippet") or "")
                    if not tok:
                        continue
                    sym = None
                    if not isinstance(line, int):
                        tok2, line2, sym = parse_anchor_token(tok)
                        tok, line = tok2, line2
                    check_token(tok, line, sym, snip, "inv[%d]" % idx)
                elif isinstance(item, str):
                    tok, line, sym = parse_anchor_token(item)
                    check_token(tok, line, sym, "", "inv[%d]" % idx)
    for stem, text in rule_files.items():
        for mt in RULE_ANCHOR_SYMBOL.finditer(text):
            tok, line, sym = parse_anchor_token(mt.group(0))
            check_token(tok, line, sym, "", "rule:%s" % stem)
        for mt in RULE_ANCHOR_LINE.finditer(text):
            tok, line, sym = parse_anchor_token(mt.group(0))
            check_token(tok, line, sym, "", "rule:%s" % stem)
    return m


def audit_reconciliation(inventory: dict | None, rules_dir: Path, target: Path,
                         fmt: str):
    r = {"controls": 0, "cats": 0, "files": 0, "missing_files": [],
         "extra_files": [], "represented": 0, "missing_controls": [],
         "index_links": None, "index_files": None}
    files = {}
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*.md")):
            ok, text, _ = read_text(p)
            if ok:
                files[p.stem] = text
    r["files"] = len(files)
    if not inventory:
        return r
    controls = [c for c in (inventory.get("controls") or []) if isinstance(c, dict)]
    r["controls"] = len(controls)
    cats = sorted({str(c.get("category")) for c in controls if c.get("category")})
    r["cats"] = len(cats)
    for cat in cats:
        if cat not in files:
            r["missing_files"].append(cat)
    for stem in files:
        if stem not in cats:
            r["extra_files"].append(stem)
    for idx, ctl in enumerate(controls):
        cat = str(ctl.get("category") or "")
        body = files.get(cat, "")
        hit = False
        ev = ctl.get("evidence")
        items = ev if isinstance(ev, list) else ([ev] if ev else [])
        for item in items[:10]:
            tok = ""
            if isinstance(item, dict):
                tok = str(item.get("file") or item.get("path") or "")
            elif isinstance(item, str):
                tok = parse_anchor_token(item)[0]
            if not tok:
                continue
            # match on the repo-relative path AS WRITTEN or its basename —
            # inventory evidence and rule text may root paths differently
            rel = tok.replace("\\", "/")
            base = os.path.basename(rel)
            if rel in body or base in body:
                hit = True
                break
        if hit:
            r["represented"] += 1
        else:
            r["missing_controls"].append(
                {"idx": idx, "name": str(ctl.get("name") or "")[:120],
                 "category": cat[:80]})
    if fmt == "opencode":
        agents = target / "AGENTS.md"
        if agents.is_file():
            ok, text, _ = read_text(agents)
            if ok and "security-controls:begin" in text:
                seg = text.split("security-controls:begin", 1)[1]
                seg = seg.split("security-controls:end", 1)[0]
                links = set(re.findall(r"security-controls/([\w.\-]+)\.md", seg))
                r["index_links"] = len(links)
                r["index_files"] = len(links & set(files))
                r["index_orphans"] = sorted(links - set(files))[:20]
                r["index_unlinked"] = sorted(set(files) - links)[:20]
    return r


def pack_manifest_expected(cp_root: Path):
    """Collect expected member record basenames + member ids from pack
    manifests (any checkpoints/*manifest* dir). Regex-over-JSON on purpose:
    robust to manifest shape drift for this diagnostic."""
    expected: set[str] = set()
    n_manifests = 0
    try:
        dirs = sorted(os.listdir(cp_root))
    except OSError:
        return expected, 0
    for d in dirs:
        if "manifest" not in d.lower():
            continue
        dp = cp_root / d
        if not dp.is_dir():
            continue
        for f in sorted(os.listdir(dp)):
            if not f.endswith(".json"):
                continue
            ok, data, _ = read_text(dp / f)
            if not ok:
                continue
            n_manifests += 1
            for mt in re.finditer(r'"checkpoint_path"\s*:\s*"([^"]+)"', data):
                expected.add(Path(mt.group(1).replace("\\", "/")).name)
    return expected, n_manifests


def classify_t1_orphans(t1_st: dict, expected: set[str]):
    """Split orphan t1 markers: expected-by-manifest (record GENUINELY missing
    — a T1 coverage gap) vs not in any manifest (stale/foreign marker)."""
    gap = stale = 0
    for base in t1_st.get("orphan_ids") or []:
        if base in expected:
            gap += 1
        else:
            stale += 1
    return gap, stale


def scout_probe(init_dir: Path, scout_t: dict):
    """Probe orphan scout markers: (a) misnamed-but-present records (search
    every filename under init-dir for the batch token), (b) whether the batch
    reached scout_candidates.json (batch-token string search), (c) count of
    non-record/non-marker files in the scout tier (miswritten outputs land
    here)."""
    ids = [b[: -len(".json")] for b in (scout_t.get("orphan_ids") or [])
           if b.endswith(".json")]
    if not ids:
        return None
    names: list[str] = []
    for root, dirs, files in os.walk(init_dir):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        names.extend(files)

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def _hit(token: str):
        raw_marker = token + ".json.done"
        raw_record = token + ".json"
        nt = _norm(token)
        if not nt:
            return []
        return [n for n in names
                if n not in (raw_marker, raw_record) and nt in _norm(n)][:3]

    hits = {i: _hit(i) for i in ids}
    elsewhere = sum(1 for i in ids if hits[i])
    cands_hit = 0
    cands_detail = []
    for cand_file in ("scout_candidates.json", "controls_candidates.json"):
        p = init_dir / cand_file
        if p.is_file():
            ok, data, _ = read_text(p)
            if ok:
                for i in ids:
                    if i in data:
                        cands_hit += 1
                        cands_detail.append("%s:1" % i)
                    else:
                        cands_detail.append("%s:0" % i)
                break
    extras = []
    scout_dir = init_dir / "checkpoints" / "scout"
    if scout_dir.is_dir():
        for entry in sorted(os.listdir(scout_dir)):
            if entry.endswith((".json", ".done", ".failed")):
                continue
            extras.append(entry)
            if len(extras) >= 3:
                break
    total_cands = -1
    p = init_dir / "scout_candidates.json"
    if p.is_file():
        ok, data, _ = load_json(p)
        if ok and isinstance(data, dict) and isinstance(data.get("candidates"), list):
            total_cands = len(data["candidates"])
    return {"ids": len(ids), "elsewhere": elsewhere, "cands_hit": cands_hit,
            "cands_detail": ",".join(cands_detail)[:120],
            "hit_names": [n for v in hits.values() for n in v][:3],
            "extras": len(extras), "extra_names": extras,
            "cands_total": total_cands}


def post_t4_lint(target: Path, fmt: str, rules_dir: Path, script: Path):
    if script is None or not script.is_file():
        return "skipped"
    cmd = [sys.executable, str(script), "--target", str(target), "--format", fmt,
           "--rules-dir", str(rules_dir), "--check"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=180)
    except Exception as exc:  # noqa: BLE001
        return "error:%s" % type(exc).__name__
    if proc.returncode == 0:
        return "ok"
    tail = (proc.stderr or proc.stdout or "").strip()[-300:]
    return "fail:%d" % proc.returncode + (("|" + tail.replace("\n", " ")[:200]) if tail else "")


def scan_config(target: Path):
    hits, files_scanned, files_hit = 0, 0, 0
    for root, dirs, names in os.walk(target):
        dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
        if files_scanned >= 20000:
            break
        for name in names:
            if Path(name).suffix.lower() not in DECL_EXTS:
                continue
            if files_scanned >= 20000:
                break
            p = Path(root) / name
            try:
                if p.stat().st_size > 2_000_000:
                    continue
            except OSError:
                continue
            files_scanned += 1
            ok, text, _ = read_text(p)
            if not ok:
                continue
            low = text.lower()
            n = sum(low.count(pat) for pat in DECL_PATTERNS)
            if n:
                files_hit += 1
                hits += n
    return {"files_scanned": files_scanned, "files_hit": files_hit, "hits": hits}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic post-run audit of a finished mgh-init run")
    ap.add_argument("--target", required=True, help="repo root (absolute)")
    ap.add_argument("--init-dir", help="default <target>/.mgh-init")
    ap.add_argument("--format", choices=("opencode", "claude"), default="opencode")
    ap.add_argument("--rules-dir",
                    help="default opencode <target>/docs/security-controls | "
                         "claude <target>/.claude/rules")
    ap.add_argument("--assemble-rules",
                    help="path to assemble_rules.py for post-T4 lint; default "
                         "<target>/.opencode/mgh-core/scripts/assemble_rules.py")
    ap.add_argument("--max-src-mb", type=int, default=300,
                    help="source-read budget for anchor/symbol checks")
    ap.add_argument("--scan-config", action="store_true",
                    help="count declarative config files (xml/properties/…) "
                         "with security-declaration patterns")
    ap.add_argument("--json-out", help="default <init-dir>/audit_report.json")
    ap.add_argument("--full", action="store_true",
                    help="print the full summary even when a previous "
                         "audit_summary.json exists (default: diff-only)")
    args = ap.parse_args(argv)

    target = Path(args.target).resolve()
    init_dir = Path(args.init_dir).resolve() if args.init_dir \
        else target / ".mgh-init"
    if not init_dir.is_dir():
        print("error: init-dir not found: %s" % init_dir, file=sys.stderr)
        return 2
    rules_dir = Path(args.rules_dir).resolve() if args.rules_dir else (
        target / ".claude/rules" if args.format == "claude"
        else target / "docs/security-controls")
    assemble = Path(args.assemble_rules).resolve() if args.assemble_rules else (
        target / ".opencode/mgh-core/scripts/assemble_rules.py")
    detail: dict = {"target": str(target), "init_dir": str(init_dir),
                    "format": args.format, "tiers": {}, "notes": []}

    cp_root = init_dir / "checkpoints"
    tiers_found = []
    if cp_root.is_dir():
        for d in sorted(os.listdir(cp_root)):
            if (cp_root / d).is_dir():
                tiers_found.append(d)
    pack_expected, pack_manifest_count = (set(), 0)
    if cp_root.is_dir():
        pack_expected, pack_manifest_count = pack_manifest_expected(cp_root)
    for tier in tiers_found:
        st = scan_tier(cp_root / tier)
        st["orphan_sha_hit"] = pack_reconcile(st, cp_root / tier) \
            if tier == "t1" else 0
        if tier == "t1":
            st["orphan_gap"], st["orphan_stale"] = classify_t1_orphans(
                st, pack_expected)
        else:
            st["orphan_gap"] = st["orphan_stale"] = 0
        detail["tiers"][tier] = st

    ok_inv, inventory, inv_err = load_json(init_dir / "controls_inventory.json")
    if not ok_inv and inventory is None:
        detail["notes"].append("inventory unreadable: %s" % inv_err)

    t4c = "absent"
    t4_path = init_dir / "checkpoints/t4/consistency.json"
    if t4_path.is_file():
        ok, _, err = load_json(t4_path)
        t4c = "ok" if ok else "bad"
        if not ok:
            detail["notes"].append("t4 consistency.json parse: %s" % err[:200])
    lint = post_t4_lint(target, args.format, rules_dir, assemble)

    rule_texts = {}
    if rules_dir.is_dir():
        for p in sorted(rules_dir.glob("*.md")):
            ok, text, _ = read_text(p)
            if ok:
                rule_texts[p.stem] = text
    cache = SourceCache(args.max_src_mb * 1_000_000)
    anchors = audit_anchors(inventory if ok_inv else None, rule_texts, target, cache)
    recon = audit_reconciliation(inventory if ok_inv else None, rules_dir, target,
                                 args.format)

    manifest, boundaries, failures = None, None, None
    ok_m, manifest, _ = load_json(init_dir / "init_manifest.json")
    if ok_m and isinstance(manifest, dict):
        boundaries = manifest.get("boundaries")
        failures = manifest.get("failures")
    report_md = init_dir / "report.md"
    report_bytes = report_md.stat().st_size if report_md.is_file() else -1
    cfg = None
    ok_c, cfg_data, _ = load_json(init_dir / "run_config.json")
    if ok_c and isinstance(cfg_data, dict):
        cfg = {k: cfg_data.get(k) for k in
               ("format", "scope", "no_scout", "skip_consistency",
                "max_aggregate_bytes", "pack_bytes") if k in cfg_data}
    scout_batches = None
    ok_s, scout_plan, _ = load_json(init_dir / "scout_plan.json")
    if ok_s and isinstance(scout_plan, dict):
        b = scout_plan.get("batches")
        if isinstance(b, list):
            scout_batches = len(b)

    t2 = detail["tiers"].get("t2", {})

    detail.update({"anchors": anchors, "reconciliation": recon,
                   "post_t4_lint": lint, "t4_consistency": t4c,
                   "manifest_boundaries": boundaries,
                   "manifest_failures": failures, "run_config": cfg,
                   "scout_plan_batches": scout_batches,
                   "report_md_bytes": report_bytes,
                   "src_budget_used_mb": round(cache.used / 1_000_000, 1)})
    if args.scan_config:
        detail["declarative_config"] = scan_config(target)

    json_out = Path(args.json_out).resolve() if args.json_out \
        else init_dir / "audit_report.json"
    try:
        with open(json_out, "w", encoding="utf-8") as fh:
            json.dump(detail, fh, ensure_ascii=False, indent=1)
    except Exception as exc:  # noqa: BLE001
        print("error: cannot write detail report: %s" % exc, file=sys.stderr)
        return 2

    def mk(name):
        t = detail["tiers"].get(name, {})
        return "%s=%d/%d" % (name, t.get("done", 0), t.get("failed", 0))

    tier_names = sorted(detail["tiers"])
    scout_t = detail["tiers"].get("scout", {})

    def _leaf(name):
        n = name.split("/")[-1][:36]
        return n if n.isascii() else ""

    orphan_ex = [x for x in (_leaf(n) for n in (scout_t.get("orphan_ids") or [])) if x][:2]
    recno_ex = [x for x in (_leaf(n) for n in (scout_t.get("rec_no_done_ids") or [])) if x][:2]
    t1_t = detail["tiers"].get("t1", {})
    json_bad_total = sum(t.get("json_bad", 0) for t in detail["tiers"].values())
    lines = [
        "markers " + " ".join(mk(t) for t in tier_names),
        "records " + " ".join(
            "%s=%d(files=%d)" % (t, detail["tiers"][t].get("records", 0),
                                 detail["tiers"][t].get("files_total", 0))
            for t in tier_names),
        "orphan_json t1=%d gap=%d stale=%d sha_hit=%d pack_markers=%d scout=%d t2=%d t3=%d other_marker=%d rec_no_scout=%d rec_no_total=%d" % (
            t1_t.get("orphan_done", 0), t1_t.get("orphan_gap", 0),
            t1_t.get("orphan_stale", 0), t1_t.get("orphan_sha_hit", 0),
            t1_t.get("pack_markers", 0),
            scout_t.get("orphan_done", 0),
            detail["tiers"].get("t2", {}).get("orphan_done", 0),
            detail["tiers"].get("t3", {}).get("orphan_done", 0),
            detail["tiers"].get("t3", {}).get("orphan_other", 0),
            scout_t.get("rec_no_done", 0),
            sum(t.get("rec_no_done", 0) for t in detail["tiers"].values())),
        "packs manifests=%d" % pack_manifest_count,
        "json_bad total=%d %s" % (json_bad_total, " ".join(
            "%s=%d" % (t, detail["tiers"][t].get("json_bad", 0))
            for t in tier_names)),
        "t2 shards=%d shard_bad=%d synthesis=%s" % (
            t2.get("records", 0), t2.get("json_bad", 0), _synthesis_state(detail)),
        "t4 consistency=%s post_t4_lint=%s" % (t4c, lint.split("|")[0]),
        "anchors total=%d ok=%d bad_file=%d(basename_resolved=%d) bad_line=%d bad_symbol=%d unchecked=%d" % (
            anchors["total"], anchors["ok"], anchors["bad_file"],
            anchors["by_basename"], anchors["bad_line"],
            anchors["bad_symbol"], anchors["unchecked"]),
        "snippets checked=%d mismatch=%d" % (
            anchors["snippets_checked"], anchors["snippet_mismatch"]),
        "inv controls=%d cats=%d files=%d missing_files=%d extra_files=%d" % (
            recon["controls"], recon["cats"], recon["files"],
            len(recon["missing_files"]), len(recon["extra_files"])),
        "cover represented=%d missing=%d" % (
            recon["represented"], len(recon["missing_controls"])),
        "index links=%s files=%s" % (
            recon["index_links"] if recon["index_links"] is not None else "n/a",
            recon["index_files"] if recon["index_files"] is not None else "n/a"),
        "manifest boundaries=%s failures=%s report_md=%d cfg_scout=%s" % (
            len(boundaries) if isinstance(boundaries, list) else "n/a",
            _fail_total(failures), report_bytes,
            "off" if (cfg and cfg.get("no_scout")) else "on"),
        "detail_json=written",
    ]
    if orphan_ex or recno_ex:
        parts = []
        if orphan_ex:
            parts.append("orphan=" + ",".join(orphan_ex))
        if recno_ex:
            parts.append("no_marker=" + ",".join(recno_ex))
        lines.append("scout_mismatch " + " ".join(parts))
    sp = scout_probe(init_dir, scout_t)
    if sp:
        lines.append(
            "scout_probe orphan=%d elsewhere=%d cands_hit=%d cands_total=%d extras=%d"
            % (sp["ids"], sp["elsewhere"], sp["cands_hit"], sp["cands_total"],
               sp["extras"]))
        lines.append("scout_cands_detail %s" % sp["cands_detail"])
        for n in sp["hit_names"] + sp["extra_names"]:
            if n.isascii():
                lines.append("scout_hit_name %s" % n[:60])
    dc = detail.get("declarative_config") or {}
    if dc:
        lines.append("decl_cfg scanned=%d hit_files=%d hits=%d" % (
            dc["files_scanned"], dc["files_hit"], dc["hits"]))

    # summary persistence + diff printing: only keys that CHANGED since the
    # previous audit are printed by default (--full forces the whole page)
    flat: dict[str, str] = {}
    for ln in lines:
        toks = ln.split()
        if not toks or "=" in toks[0]:
            continue
        label = toks[0]
        for tok in toks[1:]:
            if "=" in tok:
                k, v = tok.split("=", 1)
                flat["%s:%s" % (label, k)] = v
    summary_path = init_dir / "audit_summary.json"
    prev_keys = None
    if summary_path.is_file():
        ok_s, prev_summary, _ = load_json(summary_path)
        if ok_s and isinstance(prev_summary, dict) \
                and isinstance(prev_summary.get("keys"), dict):
            prev_keys = prev_summary["keys"]
    out_lines = []
    if prev_keys is not None and not args.full:
        changed = {k: v for k, v in flat.items() if prev_keys.get(k) != v}
        removed = [k for k in prev_keys if k not in flat]
        out_lines.append("AUDIT v1.3 fmt=%s mode=diff changed=%d removed=%d"
                         % (args.format, len(changed), len(removed)))
        for k in sorted(changed):
            out_lines.append("%s %s -> %s" % (k, prev_keys.get(k, "?"), changed[k]))
        for k in sorted(removed):
            out_lines.append("%s REMOVED" % k)
        if not changed and not removed:
            out_lines.append("NO_CHANGES")
    else:
        out_lines.append("AUDIT v1.3 fmt=%s mode=full" % args.format)
        out_lines.extend(lines)
        out_lines.append("baseline_saved=yes")
    out_lines.append("detail: %s" % json_out)
    for ln in out_lines:
        print(ln)
    try:
        with open(summary_path, "w", encoding="utf-8") as fh:
            json.dump({"v": "1.3", "keys": flat}, fh, ensure_ascii=False, indent=1)
    except Exception as exc:  # noqa: BLE001
        print("warn: cannot write audit_summary.json: %s" % exc, file=sys.stderr)
    return 0


def _synthesis_state(detail: dict) -> str:
    # synthesis.json content file is absent by design; reflect what exists on disk
    syn = detail.get("init_dir") and Path(detail["init_dir"]) / \
        "checkpoints/t2/synthesis.json"
    if syn and Path(syn).is_file():
        ok, _, _ = load_json(Path(syn))
        return "ok" if ok else "bad"
    return "absent"


def _fail_total(failures):
    if not isinstance(failures, dict):
        return "n/a"
    tot = 0
    for v in failures.values():
        if isinstance(v, dict):
            tot += int(v.get("failed") or 0)
    return tot


if __name__ == "__main__":
    sys.exit(main())
