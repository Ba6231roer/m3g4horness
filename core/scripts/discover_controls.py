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

Pipeline: walk sources (streaming) -> regex scan per category -> enclosing
anchor -> reverse-graph wiring (entry_points) -> cluster formation.

Usage:
  py discover_controls.py --repo <root> --out <dir> [--scope path:<d>|package:<p>|file:<g>]
        [--scope-mode defined|applicable] [--language <l>] [--max-files <N>]
        [--big-file-bytes <N>] [--sample <N>]
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

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


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _enclosing(text: str, line: int, lang: str):
    """Nearest preceding class & function name for a 1-based line."""
    cls = fn = None
    cls_rx = CLASS_RX.get(lang)
    if cls_rx:
        best = 0
        for m in cls_rx.finditer(text):
            ln = _line_of(text, m.start())
            if ln <= line and ln > best:
                best, cls = ln, m.group(1)
    dp = _def_pattern(lang)
    best = 0
    for m in dp.finditer(text):
        name = m.group(1)
        if not name or len(name) <= 2:
            continue
        ln = _line_of(text, m.start())
        if ln <= line and ln > best:
            best, fn = ln, name
    kind = "class" if cls and (fn is None) else ("method" if fn else "annotation")
    return {"class": cls, "method": fn, "kind": kind}


def build_call_graph_bounded(repo: Path, max_files: int):
    """Reuse expand_scope primitives but --max-files aware (D11: no silent cap)
    and ORDER-INDEPENDENT via two passes.

    expand_scope.build_call_graph is single-pass, so a caller visited before the
    callee's def file silently misses the edge — harmless for SAST scope expansion
    but it degrades init's wiring (entry_points). We collect ALL defs first, then
    resolve calls. Returns (forward, reverse, framework_files, truncated, scanned).
    """
    name_to_files = defaultdict(set)
    framework_files = set()
    files: list[tuple[str, str]] = []  # (rel, lang)
    scanned = 0
    truncated = False
    # pass 1: definitions + framework markers
    for path, lang in walk_sources(repo, limit_files=max_files + 1):
        scanned += 1
        if scanned > max_files:
            truncated = True
            break
        rel = path.relative_to(repo).as_posix()
        files.append((rel, lang))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if FRAMEWORK_RX.search(text):
            framework_files.add(rel)
        dp = _def_pattern(lang)
        for m in dp.finditer(text):
            name = m.group(1)
            if name and len(name) > 2:
                name_to_files[name].add(rel)
    # pass 2: resolve calls against the COMPLETE def index
    forward = defaultdict(lambda: defaultdict(int))
    for rel, lang in files:
        p = repo / rel
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        cp = _call_pattern(lang)
        seen = set()
        for m in cp.finditer(text):
            name = m.group(1)
            if len(name) <= 2 or name in seen:
                continue
            seen.add(name)
            for tgt in name_to_files.get(name, ()):
                if tgt != rel:
                    forward[rel][tgt] += 1
    reverse = defaultdict(set)
    for caller, callees in forward.items():
        for callee in callees:
            reverse[callee].add(caller)
    return dict(forward), reverse, framework_files, truncated, scanned


def resolve_seed(repo: Path, scope: str | None):
    """Return (seed_files:set[rel], scope_note:str). None/empty => whole repo marker []."""
    if not scope:
        return None, "full-repo"
    if scope.startswith("path:"):
        d = repo / scope[5:]
        return set(collect_dir(repo, d)) if d.is_dir() else set(), scope
    if scope.startswith("package:"):
        files = set()
        for d in package_to_dirs(repo, scope[8:]):
            files |= set(collect_dir(repo, d))
        return files, scope
    if scope.startswith("file:"):
        pat = scope[5:]
        import fnmatch
        out = set()
        for p, _ in walk_sources(repo, limit_files=10**9):
            rel = p.relative_to(repo).as_posix()
            if fnmatch.fnmatch(rel, pat):
                out.add(rel)
        return out, scope
    return None, "full-repo"


def scan(repo: Path, seed_files, max_files: int, big_bytes: int, language: str | None):
    """Yield candidate dicts (streaming per file)."""
    forward, reverse, framework_files, truncated, scanned = build_call_graph_bounded(repo, max_files)
    cid = 0
    candidates = []
    for path, lang in walk_sources(repo, limit_files=max_files + 1):
        rel = path.relative_to(repo).as_posix()
        if language and lang != language:
            continue
        if seed_files is not None and rel not in seed_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            big = path.stat().st_size > big_bytes
        except OSError:
            big = False
        for cat, rxs in COMPILED.items():
            for rx in rxs:
                for m in rx.finditer(text):
                    ln = _line_of(text, m.start())
                    snippet = text.splitlines()[ln - 1].strip()[:160] if ln <= len(text.splitlines()) else m.group(0)
                    anchor = _enclosing(text, ln, lang)
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
                        "big_file": big,
                    })
    return candidates, forward, reverse, framework_files, truncated, scanned


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


def main():
    ap = argparse.ArgumentParser(description="discover existing security controls")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True, help="output dir (candidates + clusters)")
    ap.add_argument("--scope", help="path:<dir>|package:<pkg>|file:<glob>")
    ap.add_argument("--scope-mode", choices=["defined", "applicable"], default="defined")
    ap.add_argument("--language")
    ap.add_argument("--max-files", type=int, default=200000,
                    help="warn-and-continue beyond this (D11; no silent truncation)")
    ap.add_argument("--big-file-bytes", type=int, default=204800)
    ap.add_argument("--sample", type=int, default=8)
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    seed_files, scope_note = resolve_seed(repo, args.scope)
    seed_set = seed_files if seed_files is not None else None

    candidates, forward, reverse, framework_files, truncated, scanned = scan(
        repo, seed_set, args.max_files, args.big_file_bytes, args.language)

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
    (outdir / "controls_candidates.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (outdir / "clusters.json").write_text(
        json.dumps({"repo": str(repo), "clusters": clusters,
                    "truncated": truncated}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps({"candidates": len(candidates), "clusters": len(clusters),
                      "unresolved": len(unresolved), "out_of_scope": len(set(out_of_scope)),
                      "truncated": truncated, "scanned": scanned}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
