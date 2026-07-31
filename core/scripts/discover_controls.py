#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
discover_controls — deterministic discovery of existing security controls.

Zero runtime deps (Python >=3.10 stdlib). The Semgrep/CodeQL "control inventory"
idea (glasswing_docs/09 §1.3) downgraded to text patterns + textual call graph,
reusing expand_scope's per-language primitives (DEF_CALL / FRAMEWORK_RX /
SOURCE_EXT / walk_sources) — see D2 (import, no rewrite) + D11 (no silent cap).

Produces:
  controls_candidates.json  — raw hits (audit trail), see core/contracts/init/
  clusters.json             — T1 isolation units (centralized / distributed)

Pipeline: walk sources ONCE (materialized) -> read each file ONCE (cached) ->
regex scan per category -> enclosing anchor (precomputed nodes + bisect) ->
reverse-graph wiring (entry_points) -> cluster formation. Single-pass I/O keeps
multi-tens-of-thousands-of-files repos within the host timeout.

Resilience (host-shell timeout safety): discover no longer assumes a single host
call finishes. A built call graph is cached under <out>/cache/ and reused across
runs (mtime/size freshness); scanning checkpoints <out>/cache/scan_progress.json
every --progress-every files so --resume continues without rescanning; with
--time-budget-ms set, discover stops at a safe boundary, writes cache + checkpoint,
and exits 0 with stdout `partial:true` + `resume_hint` (the orchestrator re-dispatches
--resume). All product JSON is written atomically (.tmp + os.replace) so a SIGKILL
mid-write leaves no truncated artifact. Cache/resume/budget are additive; default
behavior (budget 0 = off, no cache yet = rebuild) is byte-equivalent to before.

Usage:
  py discover_controls.py --repo <root> --out <dir> [--scope path:<d>|package:<p>|file:<g>]
        [--scope-mode defined|applicable] [--language <l>] [--max-files <N>]
        [--big-file-bytes <N>] [--sample <N>] [--progress-every <N>]
        [--large-repo-threshold <N>] [--include-dotfiles]
        [--time-budget-ms <N>] [--rebuild-cache] [--resume]
  py discover_controls.py --check <out-dir>
"""
from __future__ import annotations
import argparse
import bisect
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

# FD2: self-locate this script's directory so the sibling `expand_scope` import
# resolves under ANY cwd / host-agent invocation (direct `py`/`python`), removing
# the "No module named 'expand_scope'" failure and the python -c exec workaround.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from expand_scope import (  # reuse, no rewrite (D2)
    SOURCE_EXT, EXCLUDE_DIR, DEF_CALL, FRAMEWORK_RX,
    walk_sources, package_to_dirs, collect_dir,
)

# Stronger Java method pattern than expand_scope's DEF_CALL: the upstream pattern
# misses methods with a return type (e.g. "public static String mask(...)"), which
# would silently break name resolution → entry_points wiring. Used for the graph
# and anchor detection (deterministic-only; does not touch expand_scope itself).
JAVA_DEF = re.compile(
    r"\b(?:public|private|protected|static|final|synchronized|abstract|native|default|\s)*"
    r"(?:[A-Za-z_]\w*(?:\s*<[^>]*>)?(?:\s*\[\s*\])*\s+)*"
    r"([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:throws[^{]*)?\{")


def _def_pattern(lang: str):
    """Def-site regex for a language (stronger for Java; else expand_scope's)."""
    if lang == "java":
        return JAVA_DEF
    return DEF_CALL.get(lang, DEF_CALL["c"])[0]


def _call_pattern(lang: str):
    return DEF_CALL.get(lang, DEF_CALL["c"])[1]

# ── per-category detection patterns (text; Semgrep-equivalent, zero-dep) ──
CATEGORY_PATTERNS: dict[str, list[str]] = {
    "input-validation": [
        r"@Valid\b", r"@Validated\b", r"@Pattern\b", r"@Size\b", r"@NotNull\b",
        r"@NotBlank\b", r"@NotEmpty\b", r"@Min\b", r"@Max\b", r"@Digits\b",
        r"\bValidator\b", r"\bHibernateValidator\b", r"\bsanitize\w*\b", r"\bsanitise\w*\b",
        r"\bescapeHtml\w*\b", r"\bpydantic\b", r"\bBaseModel\b", r"\bzod\b", r"\bJoi\.\w+",
    ],
    "data-masking": [
        r"@JsonSerialize\b", r"@JsonIgnore\b", r"WRITE_ONLY", r"\bmask\w*\b", r"\bredact\w*\b",
        r"\bdesensitiz\w*\b", r"脱敏", r"\bMaskingSerializer\b", r"\bLuhn\b", r"\bidcard\w*\b",
    ],
    "authentication": [
        r"@EnableWebSecurity\b", r"\bAuthenticationManager\b", r"\bAuthenticationProvider\b",
        r"\bJwtDecoder\b", r"\bJwtEncoder\b", r"\bAbstractAuthenticationProcessingFilter\b",
        r"\bOAuth2Client\b", r"\bloginFilter\b", r"\bBCryptPasswordEncoder\b",
        r"\bUsernamePasswordAuthenticationFilter\b",
    ],
    "authorization": [
        r"@PreAuthorize\b", r"@PostAuthorize\b", r"@Secured\b", r"@RolesAllowed\b",
        r"@DenyAll\b", r"@PermitAll\b", r"@EnableMethodSecurity\b",
        r"@EnableGlobalMethodSecurity\b", r"\bSecurityConfig\b",
        r"\bWebSecurityConfigurerAdapter\b", r"\bAuthorizationManager\b",
        r"\bAccessDecisionManager\b", r"\bFilterSecurityInterceptor\b",
        r"\bhasAuthority\b", r"\bhasRole\b", r"\bSecurityFilterChain\b",
    ],
    "crypto": [
        r"\bCipher\b", r"\bMessageDigest\b", r"\bMac\.getInstance\b", r"\bSignature\.getInstance\b",
        r"\bKeyGenerator\b", r"\bSecretKeySpec\b", r"\bIvParameterSpec\b", r"\bBCrypt\b",
        r"\bArgon2\w*\b", r"\bPBKDF2\w*\b", r"\bEncryptor\b", r"\bDecryptor\b",
        r"\bAES\w*\b", r"\bRSA\w*\b",
    ],
    "rate-limiting": [
        r"@RateLimit\w*\b", r"\bRateLimiter\b", r"\bBucket4j\b", r"\bRedisRateLimiter\b",
        r"\bthrottle\w*\b", r"\banti-?replay\b", r"\bnonce\w*\b",
    ],
    "csrf": [
        r"\bCsrfFilter\b", r"\bCsrfToken\w*\b", r"\bCookieCsrfTokenRepository\b",
        r"\bXSRF\b", r"\bcsrf\(\)\b",
    ],
    "audit-logging": [
        r"@Audit\w*\b", r"\bAuditLog\b", r"\bAuditAspect\b", r"\bAuditTrail\b",
        r"\bAuditRepository\b", r"\bAuditable\b",
    ],
}
COMPILED = {cat: [re.compile(rx) for rx in rxs] for cat, rxs in CATEGORY_PATTERNS.items()}

# FD3 pre-filter: union of every category pattern. One search per file decides
# whether the file can yield ANY candidate — marker-free files (the majority in a
# real repo) skip the per-category scan + node index entirely. Exact (no false
# negatives: it IS the alternation of all category patterns), so the candidate
# set is unchanged; it only avoids wasted regex work on irrelevant files.
_QUICK_RX = re.compile("|".join(
    f"(?:{rx})" for rxs in CATEGORY_PATTERNS.values() for rx in rxs))

# category -> vvah kind (deterministic; see core/contracts/init/inventory.md)
KIND = {
    "input-validation": "input-validation",
    "authentication": "auth", "authorization": "auth",
    "data-masking": "other", "crypto": "other", "csrf": "other",
    "rate-limiting": "other", "audit-logging": "other",
}
# Annotations that scatter across files → distributed shape (cluster by token).
DISTRIBUTED = {"@Valid", "@Validated", "@PreAuthorize", "@PostAuthorize",
               "@Secured", "@RolesAllowed", "@DenyAll", "@PermitAll",
               "@Pattern", "@Size", "@NotNull"}

CLASS_RX = {
    "java":   re.compile(r"\b(?:class|interface|enum|record|@interface)\s+([A-Za-z_]\w*)"),
    "python": re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
    "js":     re.compile(r"\bclass\s+([A-Za-z_]\w*)"),
    "ts":     re.compile(r"\bclass\s+([A-Za-z_$]\w*)"),
    "go":     re.compile(r"\btype\s+([A-Za-z_]\w*)\s+(?:struct|interface)"),
    "c":      re.compile(r"\b(?:struct|union|enum)\s+([A-Za-z_]\w*)"),
    "ruby":   re.compile(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", re.M),
    "php":    re.compile(r"\b(?:class|interface|trait)\s+([A-Za-z_]\w*)"),
}

# ── per-language import/include patterns (mechanical; feeds skeleton.json only) ──
# Used by the scout discovery layer (improve-mgh-init-llm-discovery) to give the LLM
# cheap "what does this file depend on" metadata. Multi-group patterns coalesced.
IMPORTS_RX = {
    "java":   re.compile(r"^\s*import\s+(?:static\s+)?([\w.\*]+)\s*;", re.M),
    "python": re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M),
    "js":     re.compile(r"""^\s*(?:import\b[^'"]*['"]([\w./@-]+)['"]|require\(\s*['"]([\w./@-]+)['"]\s*\))""", re.M),
    "ts":     re.compile(r"""^\s*(?:import\b[^'"]*['"]([\w./@-]+)['"]|require\(\s*['"]([\w./@-]+)['"]\s*\))""", re.M),
    "go":     re.compile(r'^\s*import\s+"?([\w./]+)"?', re.M),
    "c":      re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.M),
    "ruby":   re.compile(r"""^\s*(?:require_relative|require)\s+['"]([\w./]+)['"]""", re.M),
    "php":    re.compile(r"^\s*use\s+([\w\\]+)\s*;", re.M),
}


def _extract_imports(text: str, lang: str, cap: int = 64):
    rx = IMPORTS_RX.get(lang)
    if not rx:
        return []
    out = []
    for m in rx.finditer(text):
        g = next((x for x in m.groups() if x), None)
        if g and g not in out:
            out.append(g)
        if len(out) >= cap:
            break
    return out


def _extract_meta(text: str, lang: str, rel: str):
    """Lossless per-file metadata for skeleton.json (D2). NO semantic 'is this a control'
    judgment — classes/method_sigs/imports are mechanical extractions over cached text."""
    pkg = Path(rel).parent.as_posix() if rel else ""
    cls_rx = CLASS_RX.get(lang)
    classes = []
    if cls_rx:
        for m in cls_rx.finditer(text):
            n = m.group(1)
            if n and n not in classes:
                classes.append(n)
            if len(classes) >= 32:
                break
    method_sigs = []
    for m in _def_pattern(lang).finditer(text):
        n = m.group(1)
        if n and len(n) > 2 and n not in method_sigs:
            method_sigs.append(n)
        if len(method_sigs) >= 64:
            break
    return pkg, classes, method_sigs, _extract_imports(text, lang)


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _node_index(text: str, lang: str):
    """Per-file precomputed structural nodes for O(log n) enclosing lookup (FD3).

    Returns (cls_lines, cls_names, fn_lines, fn_names). Lines are non-decreasing
    (finditer order); consecutive duplicate lines keep the FIRST occurrence, which
    makes `bisect_right(lines, L)-1` match the old linear "nearest preceding,
    first-wins-on-ties" _enclosing exactly.
    """
    cls_lines: list[int] = []
    cls_names: list[str] = []
    cls_rx = CLASS_RX.get(lang)
    if cls_rx:
        prev = -1
        for m in cls_rx.finditer(text):
            ln = _line_of(text, m.start())
            if ln == prev:
                continue  # keep first per line (matches strict-gt linear scan)
            prev = ln
            cls_lines.append(ln)
            cls_names.append(m.group(1))
    fn_lines: list[int] = []
    fn_names: list[str] = []
    prev = -1
    for m in _def_pattern(lang).finditer(text):
        name = m.group(1)
        if not name or len(name) <= 2:
            continue
        ln = _line_of(text, m.start())
        if ln == prev:
            continue
        prev = ln
        fn_lines.append(ln)
        fn_names.append(name)
    return cls_lines, cls_names, fn_lines, fn_names


def _enclosing_from_index(cls_lines, cls_names, fn_lines, fn_names, line: int):
    """Nearest preceding class & function for a 1-based line, via bisect (FD3)."""
    cls = fn = None
    if cls_lines:
        i = bisect.bisect_right(cls_lines, line) - 1
        if i >= 0:
            cls = cls_names[i]
    if fn_lines:
        i = bisect.bisect_right(fn_lines, line) - 1
        if i >= 0:
            fn = fn_names[i]
    kind = "class" if cls and (fn is None) else ("method" if fn else "annotation")
    return {"class": cls, "method": fn, "kind": kind}


def collect_sources(repo: Path, max_files: int, include_dotfiles: bool = False,
                    dot_skipped: list | None = None):
    """Walk the repo ONCE (FD3); materialize the source list shared by graph + scan.

    Returns (files, truncated, scanned). Counting mirrors the old build_call_graph_bounded
    so `truncated` / `scanned` in the output JSON stay equivalent. `dot_skipped`, when
    given, is a 1-element `[0]` list accumulating dot-prefixed source files pruned by the
    default skip (surfaced as stdout `dotfiles_skipped` for disclosure).

    The materialized list is sorted by `rel` (repo-relative posix path) so the scan order
    — and therefore `cache/scan_progress.json::scanned_index` — is reproducible across
    runs regardless of the host filesystem's `rglob` ordering. The candidate SET is
    order-independent (per-file scan); only the resume index benefits from determinism.
    """
    files: list[tuple[str, str, str]] = []  # (path, lang, rel)
    scanned = 0
    truncated = False
    for path, lang in walk_sources(repo, limit_files=max_files + 1,
                                   include_dotfiles=include_dotfiles,
                                   dot_skipped=dot_skipped):
        scanned += 1
        if scanned > max_files:
            truncated = True
            break
        files.append((path, lang, path.relative_to(repo).as_posix()))
    files.sort(key=lambda t: t[2])  # stable rel order -> reproducible scanned_index
    return files, truncated, scanned


def index_files(files, big_bytes: int):
    """Read each file ONCE; cache text + splitlines + big flag + skeleton meta
    (D2: pkg/classes/method_sigs/imports/bytes) + mtime (cache freshness). Unreadable
    files are dropped."""
    out = []
    for path, lang, rel in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            st = path.stat()
            size = st.st_size
            mtime = int(st.st_mtime)
        except OSError:
            size = len(text.encode("utf-8", errors="replace"))
            mtime = 0
        pkg, classes, method_sigs, imports = _extract_meta(text, lang, rel)
        out.append({"rel": rel, "lang": lang, "text": text,
                    "lines": text.splitlines(), "big": size > big_bytes,
                    "bytes": size, "mtime": mtime, "pkg": pkg, "classes": classes,
                    "method_sigs": method_sigs, "imports": imports})
    return out


def build_skeleton(files_data, reverse, cand_files):
    """Assemble skeleton.json (D2): lossless per-file metadata + fan_in + regex_hit.
    reverse = call-graph reverse map (callees -> callers); cand_files = files that
    already yielded a regex candidate (scout skips these, D4 targets)."""
    out = []
    for fd in files_data:
        rel = fd["rel"]
        out.append({
            "file": rel,
            "lang": fd["lang"],
            "pkg": fd.get("pkg", ""),
            "classes": fd.get("classes", []),
            "imports": fd.get("imports", []),
            "method_sigs": fd.get("method_sigs", []),
            "fan_in": len(reverse.get(rel, ())) if reverse else 0,
            "bytes": fd.get("bytes", 0),
            "regex_hit": rel in cand_files,
        })
    return out


def build_call_graph(files_data, progress_every: int = 0):
    """Two-pass textual graph over CACHED texts (FD3; no re-read). Order-independent.

    Returns (forward, reverse, framework_files). forward is unused downstream but
    kept to preserve scan()'s return contract.
    """
    name_to_files: dict[str, set[str]] = defaultdict(set)
    framework_files: set[str] = set()
    n = len(files_data)
    # pass 1: definitions + framework markers
    for i, fd in enumerate(files_data):
        if progress_every and i and i % progress_every == 0:
            print(f"[discover] callgraph pass1 {i}/{n} files", file=sys.stderr)
        rel, lang, text = fd["rel"], fd["lang"], fd["text"]
        if FRAMEWORK_RX.search(text):
            framework_files.add(rel)
        dp = _def_pattern(lang)
        for m in dp.finditer(text):
            name = m.group(1)
            if name and len(name) > 2:
                name_to_files[name].add(rel)
    # pass 2: resolve calls against the COMPLETE def index (cached text)
    forward: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for i, fd in enumerate(files_data):
        if progress_every and i and i % progress_every == 0:
            print(f"[discover] callgraph pass2 {i}/{n} files", file=sys.stderr)
        rel, lang, text = fd["rel"], fd["lang"], fd["text"]
        cp = _call_pattern(lang)
        seen: set[str] = set()
        for m in cp.finditer(text):
            name = m.group(1)
            if len(name) <= 2 or name in seen:
                continue
            seen.add(name)
            for tgt in name_to_files.get(name, ()):
                if tgt != rel:
                    forward[rel][tgt] += 1
    reverse: dict[str, set[str]] = defaultdict(set)
    for caller, callees in forward.items():
        for callee in callees:
            reverse[callee].add(caller)
    return dict(forward), reverse, framework_files


def scan_candidates(files_data, reverse, seed_files, language: str | None,
                    progress_every: int = 0, start_i: int = 0,
                    prior_candidates=None, start_cid: int = 0,
                    deadline=None, outdir=None, manifest=None):
    """Scan CACHED texts: one splitlines + one node index per file, O(log n) enclosing.

    Resilience: resumes from `start_i` appending to `prior_candidates` (candidate ids
    continue from `start_cid`); at each `--progress-every` boundary writes a scan
    checkpoint `<out>/cache/scan_progress.json`, and if `deadline` has passed stops
    early (partial=True) at that safe boundary. Returns (candidates, partial)."""
    candidates = list(prior_candidates) if prior_candidates else []
    cid = start_cid
    n = len(files_data)
    partial = False
    for i in range(start_i, n):
        if progress_every and i and i % progress_every == 0:
            print(f"[discover] scanned {i}/{n} files, {len(candidates)} candidates",
                  file=sys.stderr)
            if outdir is not None and manifest is not None:
                _write_scan_progress(outdir, i, candidates, manifest)
            if deadline is not None and time.monotonic() >= deadline:
                partial = True
                break
        fd = files_data[i]
        rel, lang, text, lines = fd["rel"], fd["lang"], fd["text"], fd["lines"]
        if language and lang != language:
            continue
        if seed_files is not None and rel not in seed_files:
            continue
        if not _QUICK_RX.search(text):
            continue  # pre-filter: no security marker → cannot yield a candidate
        cls_lines, cls_names, fn_lines, fn_names = _node_index(text, lang)
        n_lines = len(lines)
        for cat, rxs in COMPILED.items():
            for rx in rxs:
                for m in rx.finditer(text):
                    ln = _line_of(text, m.start())
                    snippet = lines[ln - 1].strip()[:160] if ln <= n_lines else m.group(0)
                    anchor = _enclosing_from_index(
                        cls_lines, cls_names, fn_lines, fn_names, ln)
                    cid += 1
                    token = m.group(0)
                    shape = "distributed" if token in DISTRIBUTED else "centralized"
                    candidates.append({
                        "id": f"C-{cid:04d}",
                        "file": rel,
                        "line": ln,
                        "category": cat,
                        "kind": KIND[cat],
                        "pattern": token,
                        "anchor": anchor,
                        "snippet": snippet,
                        "shape": shape,
                        "cluster_id": None,  # filled by form_clusters
                        "entry_points": sorted(reverse.get(rel, set()))[:8],
                        "big_file": fd["big"],
                        "source": "regex",
                    })
    if outdir is not None and manifest is not None and not partial:
        # final checkpoint at completion -> a later --resume is an idempotent no-op
        _write_scan_progress(outdir, n, candidates, manifest)
    return candidates, partial


CACHE_DIRNAME = "cache"


def _atomic_write_json(path, obj):
    """Write `<path>.tmp` then `os.replace` (atomic on POSIX & same-volume Windows).

    A SIGKILL mid-write leaves at most a stale `.tmp` (overwritten next run), never a
    truncated/half-written JSON — so `--check` and downstream `json.loads` never read a
    broken artifact. Python stdlib only (`os.replace` / `pathlib`)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _build_manifest(files_data):
    """Cache-freshness snapshot: per-source (rel, mtime, size), sorted by rel.

    Two runs over an unchanged repo produce an identical list, so byte-equality is the
    cache hit/miss signal. mtime granularity is filesystem-dependent (coarser on some
    Windows FS) but acceptable; `--rebuild-cache` is the force-override escape hatch."""
    out = [{"rel": fd["rel"], "mtime": fd.get("mtime", 0),
            "size": fd.get("bytes", 0)} for fd in files_data]
    out.sort(key=lambda e: e["rel"])
    return out


def _try_load_callgraph_cache(outdir, manifest):
    """Return (forward, reverse, framework_files) if a fresh cache exists, else None.

    Fresh = the cached `manifest.json` is byte-equal to the current source snapshot. A
    changed/missing cache (or unreadable JSON) yields None, so the caller rebuilds."""
    if outdir is None or manifest is None:
        return None
    cdir = Path(outdir) / CACHE_DIRNAME
    cg_path = cdir / "callgraph.json"
    mf_path = cdir / "manifest.json"
    if not (cg_path.is_file() and mf_path.is_file()):
        return None
    try:
        graph = json.loads(cg_path.read_text(encoding="utf-8"))
        cached_manifest = json.loads(mf_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if cached_manifest != manifest:
        return None  # stale: a source changed (mtime/size) -> rebuild
    reverse = {k: set(v) for k, v in graph.get("reverse", {}).items()}
    framework_files = set(graph.get("framework_files", []))
    forward = graph.get("forward", {})
    return forward, reverse, framework_files


def _write_callgraph_cache(outdir, forward, reverse, framework_files, manifest):
    """Atomically persist the call graph + manifest so a re-run can skip the two passes."""
    if outdir is None:
        return
    graph = {"forward": {k: dict(v) for k, v in forward.items()},
             "reverse": {k: sorted(v) for k, v in reverse.items()},
             "framework_files": sorted(framework_files)}
    _atomic_write_json(Path(outdir) / CACHE_DIRNAME / "callgraph.json", graph)
    _atomic_write_json(Path(outdir) / CACHE_DIRNAME / "manifest.json", manifest)


def _try_load_scan_progress(outdir, manifest):
    """Return {scanned_index, candidates} if a fresh scan checkpoint exists, else None.

    Fresh = the checkpoint's stored manifest is byte-equal to the current source
    snapshot (so a checkpoint from a changed repo is ignored, not blindly trusted)."""
    if outdir is None or manifest is None:
        return None
    sp_path = Path(outdir) / CACHE_DIRNAME / "scan_progress.json"
    if not sp_path.is_file():
        return None
    try:
        sp = json.loads(sp_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if sp.get("manifest") != manifest:
        return None  # checkpoint belongs to a different source set -> ignore
    return sp


def _write_scan_progress(outdir, scanned_index, candidates, manifest):
    if outdir is None or manifest is None:
        return
    _atomic_write_json(Path(outdir) / CACHE_DIRNAME / "scan_progress.json",
                       {"scanned_index": scanned_index, "candidates": candidates,
                        "manifest": manifest})


def run_discover(repo: Path, seed_files, max_files: int, big_bytes: int,
                 language: str | None, progress_every: int = 0,
                 large_repo_threshold: int = 0, outdir=None,
                 include_dotfiles: bool = False, dot_skipped: list | None = None,
                 time_budget_ms: int = 0, rebuild_cache: bool = False,
                 resume: bool = False, write_cache: bool = True):
    """Resilient discover pipeline. Returns a dict:
      candidates, forward, reverse, framework_files, truncated, scanned,
      partial, resume_hint, cache_hit.

    Cache / resume / soft-budget are inert unless `write_cache` is True and the
    corresponding knob is set. `scan()` calls this with `write_cache=False` for
    byte-equivalent legacy behavior (always rebuild, full single run, partial=False).
    On a partial exit only `cache/` + `scan_progress.json` land on disk; the final
    products (controls_candidates/clusters/skeleton) are written by `main()` only on a
    complete run, so a partial never leaves a truncated artifact."""
    files, truncated, scanned = collect_sources(repo, max_files,
                                                include_dotfiles=include_dotfiles,
                                                dot_skipped=dot_skipped)
    if large_repo_threshold and scanned > large_repo_threshold:
        print(f"[discover] large repo: ~{scanned} source files exceed "
              f"--large-repo-threshold ({large_repo_threshold}); for speed consider "
              f"--scope path:<module> + --merge", file=sys.stderr)
    files_data = index_files(files, big_bytes)
    manifest = _build_manifest(files_data) if write_cache else None

    deadline = (time.monotonic() + time_budget_ms / 1000.0) if time_budget_ms else None

    # call graph: cache load or rebuild (cache hit skips the two regex passes)
    cache_hit = False
    loaded = None
    if write_cache and not rebuild_cache:
        loaded = _try_load_callgraph_cache(outdir, manifest)
    if loaded is not None:
        forward, reverse, framework_files = loaded
        cache_hit = True
        print("[discover] callgraph cache hit; skipping two-pass rebuild", file=sys.stderr)
    else:
        forward, reverse, framework_files = build_call_graph(files_data, progress_every)
        if write_cache:
            _write_callgraph_cache(outdir, forward, reverse, framework_files, manifest)

    partial = False
    resume_hint = ""
    candidates = []  # set by scan_candidates unless the budget trips at the callgraph boundary

    # safe boundary 1: call graph built (+ cached). Budget exceeded here → no scan yet.
    if deadline is not None and time.monotonic() >= deadline:
        # Preserve any existing fresh checkpoint — do NOT clobber prior scan progress.
        # (On a huge repo, loading the callgraph cache can itself eat the budget on a
        # --resume call; wiping the checkpoint to (0, []) would lose all prior progress.)
        if write_cache and _try_load_scan_progress(outdir, manifest) is None:
            _write_scan_progress(outdir, 0, [], manifest)
        partial = True
        resume_hint = ("callgraph built + cached; re-dispatch with --resume "
                       "(or raise --time-budget-ms) to scan candidates")
    else:
        start_i, prior, start_cid = 0, None, 0
        if resume and write_cache and cache_hit:
            sp = _try_load_scan_progress(outdir, manifest)
            if sp is not None:
                start_i = sp["scanned_index"]
                prior = sp["candidates"]
                start_cid = len(prior)
                print(f"[discover] resuming scan from file {start_i}/{len(files_data)} "
                      f"({start_cid} prior candidates)", file=sys.stderr)
        candidates, partial = scan_candidates(
            files_data, reverse, seed_files, language, progress_every,
            start_i=start_i, prior_candidates=prior, start_cid=start_cid,
            deadline=deadline, outdir=outdir if write_cache else None, manifest=manifest)
        if partial:
            resume_hint = ("scan incomplete within --time-budget-ms; re-dispatch with "
                           "--resume to continue from the checkpoint")

    # skeleton on complete runs only (partial leaves only cache/ + checkpoint)
    if outdir is not None and not partial:
        cand_files = {c["file"] for c in candidates}
        skeleton = build_skeleton(files_data, reverse, cand_files)
        _atomic_write_json(Path(outdir) / "skeleton.json",
                           {"repo": str(repo), "generated_by": "discover_controls.py",
                            "files": skeleton})
        print(f"[discover] skeleton.json: {len(skeleton)} files", file=sys.stderr)

    return {"candidates": candidates, "forward": forward, "reverse": reverse,
            "framework_files": framework_files, "truncated": truncated,
            "scanned": scanned, "partial": partial, "resume_hint": resume_hint,
            "cache_hit": cache_hit}


def scan(repo: Path, seed_files, max_files: int, big_bytes: int, language: str | None,
         progress_every: int = 0, large_repo_threshold: int = 0, outdir=None,
         include_dotfiles: bool = False, dot_skipped: list | None = None):
    """Legacy single-pass discover API: returns the 6-tuple
    (candidates, forward, reverse, framework_files, truncated, scanned).

    Delegates to run_discover(write_cache=False) — no cache/resume/budget, always a full
    rebuild in one call (byte-equivalent behavior). Kept for direct callers / tests."""
    r = run_discover(repo, seed_files, max_files, big_bytes, language, progress_every,
                     large_repo_threshold, outdir, include_dotfiles, dot_skipped,
                     write_cache=False)
    return (r["candidates"], r["forward"], r["reverse"], r["framework_files"],
            r["truncated"], r["scanned"])


def resolve_seed(repo: Path, scope: str | None, include_dotfiles: bool = False):
    """Return (seed_files:set[rel], scope_note:str). None/empty => whole repo marker []."""
    if not scope:
        return None, "full-repo"
    if scope.startswith("path:"):
        d = repo / scope[5:]
        return set(collect_dir(repo, d, include_dotfiles)) if d.is_dir() else set(), scope
    if scope.startswith("package:"):
        files = set()
        for d in package_to_dirs(repo, scope[8:]):
            files |= set(collect_dir(repo, d, include_dotfiles))
        return files, scope
    if scope.startswith("file:"):
        pat = scope[5:]
        import fnmatch
        out = set()
        for p, _ in walk_sources(repo, limit_files=10**9, include_dotfiles=include_dotfiles):
            rel = p.relative_to(repo).as_posix()
            if fnmatch.fnmatch(rel, pat):
                out.add(rel)
        return out, scope
    return None, "full-repo"


def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def form_clusters(candidates, reverse, framework_files, seed_files, sample: int):
    """Assign cluster_id (centralized by anchor; distributed by token) + build clusters.

    Returns clusters list. Mutates candidates' cluster_id / entry_points.
    """
    # group candidate indices
    cent: dict[str, list[int]] = defaultdict(list)  # key -> cand idx
    dist: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(candidates):
        if c["shape"] == "distributed":
            dist[f'{c["category"]}::{c["pattern"]}'].append(i)
        else:
            a = c["anchor"]
            home = a.get("class") or a.get("method") or c["file"]
            cent[f'{c["category"]}::{home}::{c["file"]}'].append(i)

    clusters = []
    for key, idxs in {**cent, **dist}.items():
        if not idxs:
            continue
        head = candidates[idxs[0]]
        shape = head["shape"]
        members = [candidates[i]["file"] for i in idxs]
        usage_sites = sorted(set(members))
        if shape == "distributed":
            usage_sites = usage_sites[:sample]
            evidence_files = usage_sites[:3]
        else:
            evidence_files = sorted({candidates[i]["file"] for i in idxs})
            # centralized: pull a few immediate callers as usage sites
            extra = set()
            for i in idxs:
                extra |= set(reverse.get(candidates[i]["file"], set()))
            usage_sites = sorted(set(evidence_files) | set(sorted(extra)[:sample]))
        cluster_id = f'{key}::{_sha(key)}'
        for i in idxs:
            candidates[i]["cluster_id"] = cluster_id
            if shape == "distributed":
                candidates[i]["entry_points"] = usage_sites
        clusters.append({
            "cluster_id": cluster_id,
            "category": head["category"],
            "kind": head["kind"],
            "shape": shape,
            "evidence_files": evidence_files,
            "usage_sites": usage_sites,
            "candidate_ids": [candidates[i]["id"] for i in idxs],
        })
    return clusters


def _run_check(outdir: Path):
    """R5.9 boundary check: validate an existing out-dir's products without scanning.
    Asserts controls_candidates.json + clusters.json wrappers, every candidate carries a
    `source`, and cluster_id uniqueness. Returns exit 0 ok / 2 violation."""
    violations = []
    cand_path = outdir / "controls_candidates.json"
    cl_path = outdir / "clusters.json"
    cands, clusters = [], []

    if not cand_path.is_file():
        violations.append({"file": "controls_candidates.json", "issue": "missing"})
    else:
        try:
            cd = json.loads(cand_path.read_text(encoding="utf-8"))
            cands = cd.get("candidates") if isinstance(cd, dict) else None
            if not isinstance(cands, list):
                violations.append({"file": "controls_candidates.json",
                                   "issue": "wrapper must be {repo,candidates[],...}"})
        except (OSError, ValueError) as e:
            violations.append({"file": "controls_candidates.json", "issue": f"malformed: {e}"})
            cands = []
    for i, c in enumerate(cands):
        if not isinstance(c, dict):
            violations.append({"file": "controls_candidates.json", "index": i,
                               "issue": "candidate not an object"})
            continue
        if not c.get("source"):
            violations.append({"file": "controls_candidates.json", "index": i,
                               "issue": "candidate missing `source`"})
        if not c.get("file"):
            violations.append({"file": "controls_candidates.json", "index": i,
                               "issue": "candidate missing `file`"})

    if not cl_path.is_file():
        violations.append({"file": "clusters.json", "issue": "missing"})
    else:
        try:
            cl = json.loads(cl_path.read_text(encoding="utf-8"))
            clusters = cl.get("clusters") if isinstance(cl, dict) else None
            if not isinstance(clusters, list):
                violations.append({"file": "clusters.json",
                                   "issue": "wrapper must be {repo,clusters[],truncated}"})
        except (OSError, ValueError) as e:
            violations.append({"file": "clusters.json", "issue": f"malformed: {e}"})
            clusters = []
    seen_ids = set()
    for i, cl_ in enumerate(clusters):
        if not isinstance(cl_, dict):
            violations.append({"file": "clusters.json", "index": i, "issue": "cluster not an object"})
            continue
        cid = cl_.get("cluster_id")
        if not cid:
            violations.append({"file": "clusters.json", "index": i, "issue": "missing cluster_id"})
        elif cid in seen_ids:
            violations.append({"file": "clusters.json", "index": i,
                               "issue": f"duplicate cluster_id {cid}"})
        else:
            seen_ids.add(cid)

    ok = not violations
    print(f"[discover --check] {outdir}: {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "discover", "ok": ok,
                      "candidates": len(cands), "clusters": len(clusters),
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(description="discover existing security controls")
    ap.add_argument("--repo", required=False)
    ap.add_argument("--out", required=False, help="output dir (candidates + clusters)")
    ap.add_argument("--check", help="validate an existing out-dir's products (boundary check)")
    ap.add_argument("--scope", help="path:<dir>|package:<pkg>|file:<glob>")
    ap.add_argument("--scope-mode", choices=["defined", "applicable"], default="defined")
    ap.add_argument("--language")
    ap.add_argument("--max-files", type=int, default=200000,
                    help="warn-and-continue beyond this (no silent truncation)")
    ap.add_argument("--big-file-bytes", type=int, default=204800)
    ap.add_argument("--sample", type=int, default=8)
    ap.add_argument("--progress-every", type=int, default=1000,
                    help="emit stderr progress every N files; also the scan-checkpoint "
                         "and soft-budget check cadence")
    ap.add_argument("--large-repo-threshold", type=int, default=15000,
                    help="advise --scope + --merge when source-file count exceeds this")
    ap.add_argument("--include-dotfiles", action="store_true",
                    help="scan dot-prefixed paths (.opencode/.claude/.codegraph/.github/.env); "
                         "default skips any path component starting with '.' "
                         "(tooling/VCS/IDE/build/config are non-first-party code)")
    ap.add_argument("--time-budget-ms", type=int, default=0,
                    help="soft time budget in ms (0=off); on exceeding, at a safe boundary "
                         "(callgraph built / every --progress-every files) write cache + scan "
                         "checkpoint and exit 0 with stdout partial:true + resume_hint")
    ap.add_argument("--rebuild-cache", action="store_true",
                    help="force call-graph rebuild + cache refresh (ignore the mtime/size "
                         "freshness check); default rebuilds only when the cache is absent/stale")
    ap.add_argument("--resume", action="store_true",
                    help="reuse the callgraph cache + scan checkpoint; continue a partial run "
                         "without rescanning already-checkpointed files")
    args = ap.parse_args()
    if args.check:
        return _run_check(Path(args.check).resolve())
    if not args.repo or not args.out:
        print("error: --repo and --out are required (or use --check <out-dir>)",
              file=sys.stderr)
        return 2
    repo = Path(args.repo).resolve()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    seed_files, scope_note = resolve_seed(repo, args.scope, args.include_dotfiles)
    seed_set = seed_files if seed_files is not None else None

    dot_skipped = [0]
    r = run_discover(
        repo, seed_set, args.max_files, args.big_file_bytes, args.language,
        progress_every=args.progress_every,
        large_repo_threshold=args.large_repo_threshold,
        outdir=args.out, include_dotfiles=args.include_dotfiles,
        dot_skipped=dot_skipped,
        time_budget_ms=args.time_budget_ms,
        rebuild_cache=args.rebuild_cache, resume=args.resume, write_cache=True)
    candidates = r["candidates"]
    reverse = r["reverse"]
    framework_files = r["framework_files"]
    truncated = r["truncated"]
    scanned = r["scanned"]

    # partial clean exit (soft time-budget): only cache/ + scan_progress.json landed.
    # Do NOT write truncated final products; the orchestrator re-dispatches --resume.
    if r["partial"]:
        print(json.dumps({"candidates": len(candidates), "clusters": 0,
                          "unresolved": 0, "unresolved_count": 0, "big_files": 0,
                          "dotfiles_skipped": dot_skipped[0], "out_of_scope": 0,
                          "truncated": truncated, "scanned": scanned,
                          "partial": True, "resume_hint": r["resume_hint"],
                          "cache_hit": r["cache_hit"]}))
        return 0

    # applicable mode: keep only candidates called from a seed file
    out_of_scope = []
    if seed_set is not None and args.scope_mode == "applicable":
        kept = []
        for c in candidates:
            if any(ep in seed_set for ep in c["entry_points"]) or c["file"] in seed_set:
                if c["file"] not in seed_set:
                    out_of_scope.append(c["file"])
                kept.append(c)
        candidates = kept
    elif seed_set is not None and args.scope_mode == "defined":
        # cross-module callers of in-scope controls → disclosed
        for c in candidates:
            for ep in c["entry_points"]:
                if ep not in seed_set and ep not in out_of_scope:
                    out_of_scope.append(ep)

    clusters = form_clusters(candidates, reverse, framework_files, seed_set, args.sample)

    # unresolved: framework-routed files with no textual edge to any candidate
    cand_files = {c["file"] for c in candidates}
    touched = set(cand_files)
    for c in candidates:
        touched |= set(c["entry_points"])
    unresolved = sorted(framework_files - touched)

    payload = {
        "repo": str(repo),
        "scope": {"mode": args.scope_mode, "seed": scope_note,
                  "scope-mode": args.scope_mode},
        "generated_by": "discover_controls.py",
        "candidates": candidates,
        "truncated": truncated,
        "max_files_note": (f"warned-and-continued: scanned {scanned} source files"
                           if truncated else "ok"),
        "unresolved": unresolved,
        "out_of_scope": sorted(set(out_of_scope)),
    }
    _atomic_write_json(outdir / "controls_candidates.json", payload)
    _atomic_write_json(outdir / "clusters.json",
                       {"repo": str(repo), "clusters": clusters,
                        "truncated": truncated})
    # big_files: #source files over --big-file-bytes (downstream commonly queries this
    # for slicing decisions). Read the just-written skeleton for the true count; fall back
    # to distinct big candidate files if skeleton is unavailable.
    big_files = 0
    sk_path = outdir / "skeleton.json"
    if sk_path.is_file():
        try:
            sk = json.loads(sk_path.read_text(encoding="utf-8"))
            big_files = sum(1 for f in sk.get("files", []) if isinstance(f, dict) and f.get("big"))
        except (OSError, ValueError):
            big_files = len({c["file"] for c in candidates if c.get("big_file")})
    else:
        big_files = len({c["file"] for c in candidates if c.get("big_file")})

    print(json.dumps({"candidates": len(candidates), "clusters": len(clusters),
                      "unresolved": len(unresolved), "unresolved_count": len(unresolved),
                      "big_files": big_files,
                      "dotfiles_skipped": dot_skipped[0],
                      "out_of_scope": len(set(out_of_scope)),
                      "truncated": truncated, "scanned": scanned,
                      "partial": False, "resume_hint": "", "cache_hit": r["cache_hit"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
