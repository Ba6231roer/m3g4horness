#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
anchor_resolve — shared evidence-anchor parsing + resolution for /mgh-init gates.

Single source of truth for BOTH deterministic output gates that touch anchor
tokens:
  - validate_inventory.py (T2 boundary): every inventory evidence token MUST
    resolve to a real repo file with its line/symbol claim verifiable;
  - assemble_rules.py (assembly boundary): coverage reconciliation matches the
    evidence PATH (or its basename) against the category rule-file text.
The two gates NEVER keep private copies of this logic (semantic drift is the
defect class this module exists to close). Semantics are field-proven: they
were lifted verbatim from the 2026-10-23 real-repo audit (tools/audit_init_run.py).

Token forms (closed set, same set the audit accepted):
  'path::Cls.method'   double-colon symbol anchor (rule-file form)
  'path:Cls.method'    single-colon symbol anchor (T1/inventory evidence form)
  'path:123'           line anchor
  'path'               bare path (existence check only)

Resolution ladder (deterministic): repo-root-relative exact hit -> same-dir
case-insensitive hit -> UNIQUE whole-repo basename hit. A basename hit PASSES
(counted separately as by_basename — a path-FORMAT issue, never fabrication);
basename ambiguity or total miss is file_missing.

Line anchors are 1-based and must satisfy 1 <= line <= len(lines). Symbol
anchors: every `.`-separated segment must appear in the file text.

Zero runtime deps (Python >=3.10 stdlib: os/re/sys/pathlib). Library module
(no CLI): imported by validate_inventory / assemble_rules via the sibling
self-locate guard (R5.3a). Pure functions + per-instance caches; import has
no side effects.
"""
from __future__ import annotations
import os
import re
from pathlib import Path

# Source extensions recognized by the token parser (single source; keep in
# lock-step with the rule-anchor regexes the rules-format fragment documents).
SRC_EXT = ("java", "kt", "scala", "groovy", "py", "cs", "js", "ts", "php", "rb")

# Dirs the lazy basename-index walk NEVER descends into (VCS/tool noise, huge
# build trees — a basename hit inside node_modules is noise, not evidence).
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "target", "build", "dist",
             ".mgh-init", ".mgh-ut-init", ".opencode", ".claude", ".gradle",
             "__pycache__"}

# Token-form regexes (closed set):
_LINE_RE = re.compile(r"^(.*):(\d{1,7})$")
_SYMBOL_RE = re.compile(r"^(.*\.(?:" + "|".join(SRC_EXT) + r")):([^:]+)$",
                        re.IGNORECASE)

# Closed status set for check_anchor (stdout counters of both gates).
STATUS_OK = "ok"
STATUS_BY_BASENAME = "by_basename"     # passing; resolved via unique basename
VIOL_FILE_MISSING = "file_missing"
VIOL_LINE_OUT_OF_RANGE = "line_out_of_range"
VIOL_SYMBOL_ABSENT = "symbol_absent"
VIOLATION_STATUSES = (VIOL_FILE_MISSING, VIOL_LINE_OUT_OF_RANGE,
                      VIOL_SYMBOL_ABSENT)


def parse_anchor_token(tok):
    """Evidence/anchor token -> (path, line|None, symbol|None).

    'path::Cls.method' / 'path:Cls.method' / 'path:123' / bare 'path'. The
    line form requires the path part to look like a path (contains '/' or ends
    with a known source extension) so a bare 'C:12' fragment never parses as a
    line anchor; the single-colon symbol form requires a source extension so
    'src/x.v1:yy' classifies as a bare path, not a symbol anchor."""
    tok = (tok or "").strip().strip('"').strip("'").replace("\\", "/")
    if "::" in tok:
        path, sym = tok.split("::", 1)
        return path, None, sym
    m = _LINE_RE.match(tok)
    if m and ("/" in m.group(1)
              or re.search(r"\.(?:%s)$" % "|".join(SRC_EXT), m.group(1),
                           re.IGNORECASE)):
        return m.group(1), int(m.group(2)), None
    m = _SYMBOL_RE.match(tok)
    if m:
        return m.group(1), None, m.group(2)
    return tok, None, None


def normalize_for_match(s):
    """Normalization shared by the coverage reconciliation (design D3):
    case-fold + backslash->slash. Applied to BOTH the evidence path keys and
    the rule-file text before substring matching (case/slash drift is a path
    FORMAT issue, not fabrication)."""
    return (s or "").replace("\\", "/").strip().lower()


def evidence_path_keys(path_str):
    """Matching keys for one evidence path against rule-file text: the full
    normalized path first, then its basename (inventory evidence and rule text
    may root paths differently). Deduplicated, longest-first."""
    rel = normalize_for_match(path_str)
    base = rel.rsplit("/", 1)[-1]
    keys = [rel] if rel else []
    if base and base not in keys:
        keys.append(base)
    return keys


def read_text_robust(path):
    """(ok, text, encoding) for one file: utf-8 -> gbk -> utf-8/replace (real
    repos mix encodings; a decode fallback NEVER turns into a check skip)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return True, fh.read(), "utf-8"
    except UnicodeDecodeError:
        try:
            with open(path, "r", encoding="gbk") as fh:
                return True, fh.read(), "gbk"
        except Exception:  # noqa: BLE001 — last resort below
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return True, fh.read(), "utf-8?replace"
    except OSError:
        return False, "", ""


class RepoResolver:
    """Repo-root-anchored anchor resolver with the deterministic ladder
    (exact -> same-dir case -> unique basename) and per-instance text/line
    caches. The basename index is LAZY: built on the FIRST ladder miss only
    (one os.walk over the repo; ~seconds at the 10k-file scale, zero cost when
    every anchor resolves directly)."""

    def __init__(self, repo_root):
        self.root = Path(repo_root)
        self._basename_index = None   # lazily built on first miss
        self._texts = {}              # abs path str -> (ok, text)

    # -- ladder ------------------------------------------------------------
    def resolve(self, raw):
        """Resolve one path string against the repo root.
        Returns (Path|None, how) with how in exact|case|basename|missing|empty."""
        raw = (raw or "").replace("\\", "/").strip().strip('"').strip("'")
        if raw.startswith("./"):
            raw = raw[2:]
        if not raw:
            return None, "empty"
        p = Path(raw)
        if not p.is_absolute():
            p = self.root / raw
        try:
            p = Path(os.path.normpath(str(p)))
        except (OSError, ValueError):
            return None, "missing"
        if p.is_file():
            return p, "exact"
        # same-dir case-insensitive hit (POSIX needs this explicitly; Windows
        # is case-insensitive at the FS layer and already returned above)
        parent = p.parent
        if parent.is_dir():
            want = p.name.lower()
            try:
                for entry in os.listdir(parent):
                    if entry.lower() == want and (parent / entry).is_file():
                        return parent / entry, "case"
            except OSError:
                pass
        got = self._unique_basename(p.name)
        if got is not None:
            return got, "basename"
        return None, "missing"

    def _unique_basename(self, name):
        """Whole-repo UNIQUE basename hit (lazy one-walk index). None when the
        name is absent OR ambiguous (two same-named files = no deterministic
        pick, judged missing)."""
        if self._basename_index is None:
            idx = {}
            for root, dirs, names in os.walk(self.root):
                dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
                for n in names:
                    idx.setdefault(n.lower(), []).append(os.path.join(root, n))
            self._basename_index = idx
        hits = self._basename_index.get(name.lower(), [])
        return Path(hits[0]) if len(hits) == 1 else None

    # -- text caches ---------------------------------------------------------
    def text(self, path):
        key = str(path)
        if key not in self._texts:
            self._texts[key] = read_text_robust(path)
        return self._texts[key]

    def line_count(self, path):
        ok, body, _enc = self.text(path)
        if not ok:
            return None
        return len(body.splitlines())


def _symbol_segments(sym):
    """'Cls.method(args)' -> ['Cls', 'method'] — split on '.', strip call
    parentheses; every segment must appear in the file text (spec: 符号段逐段)."""
    return [p for p in (sym or "").replace("(", " ").split(".") if p.strip()]


def check_anchor(token, resolver):
    """Full existence check for one evidence token against the resolver's repo.
    Returns a dict with the closed status set:
      ok | by_basename | file_missing | line_out_of_range | symbol_absent
    plus `resolved` (abs path str or None) and `how`. A resolved-but-unreadable
    file (OS-level anomaly) keeps status ok for its line/symbol claims are
    unverifiable, not falsified — existence itself was proven."""
    path, line, sym = parse_anchor_token(token)
    resolved, how = resolver.resolve(path)
    if resolved is None:
        return {"status": VIOL_FILE_MISSING, "resolved": None, "how": how,
                "line": line, "symbol": sym}
    status = STATUS_BY_BASENAME if how == "basename" else STATUS_OK
    if line is not None:
        n = resolver.line_count(resolved)
        if n is not None and not (1 <= line <= n):
            return {"status": VIOL_LINE_OUT_OF_RANGE, "resolved": str(resolved),
                    "how": how, "line": line, "lines": n, "symbol": sym}
    if sym is not None:
        ok, body, _enc = resolver.text(resolved)
        if ok:
            segs = _symbol_segments(sym)
            if segs and not all(s in body for s in segs):
                return {"status": VIOL_SYMBOL_ABSENT, "resolved": str(resolved),
                        "how": how, "line": line, "symbol": sym}
    return {"status": status, "resolved": str(resolved), "how": how,
            "line": line, "symbol": sym}
