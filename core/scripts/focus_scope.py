#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
focus_scope — closed-set security-dimension focus registry + parse/validate/render.

Single source of truth for the 9 security dimensions (mirroring
core/prompts/fragments/security-dimensions.md) and their optional per-dimension
facets. Powers the `--focus` narrowing flag for /mgh-sra (a1 prepare_augment) and
/mgh-srr (r1 ingest_requirements): a focus spec is parsed + closed-set-validated +
rendered into a deterministic 简体中文 directive, BEFORE any LLM subagent runs.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/sys/pathlib). Self-locating
(sys.path.insert(0, dir-of-__file__)) so the sibling import from prepare_augment /
ingest_requirements resolves under any cwd. Reads any focus file with
encoding="utf-8". Idempotent + side-effect-free (--list/--parse/--render/--check
write nothing to disk).

CLI contract (`--help` is the contract surface, R5.1):
  py focus_scope.py --list
  py focus_scope.py --parse <inline-json|path>
  py focus_scope.py --render <inline-json|path>
  py focus_scope.py --check <inline-json|path>

  --list                enumerate the registry (9 dimensions + facet keys + labels)
  --parse <json|path>   parse + closed-set-validate + render resolved focus object
                        ({"dimensions":[],"facets":{},"directive":"<简体中文>"} or null)
  --render <json|path>  alias of the render portion (identical to --parse)
  --check <json|path>   validate only (no render, no side effects)

Input form: an argument beginning with `{` is inline JSON; any other value is a
UTF-8 JSON file path (a leading `@` is tolerated and stripped; missing/unreadable
file exits 1). dimensions is a closed-set list of the 9 keys (or `"*"` / omitted =
all 9). facets is an optional {dimension: [facet, ...]} whitelist.

stdout = structured JSON (registry / resolved focus / check verdict); stderr =
diagnostics/progress only (R5.3b). Exit codes: 0 ok · 1 file missing / JSON
malformed · 2 misuse (argparse) or closed-set validation violation (R5.3b).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# Self-locate so the sibling import (prepare_augment / ingest_requirements) resolves
# under any cwd / host-agent invocation (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── closed-set registry: single source of truth (mirrors security-dimensions.md) ──
# Keys are in lockstep with the dimension catalog; adding a dimension or facet is a
# registry + catalog co-change (closed-set, never free-text).
DIMENSION_KEYS = [
    "sensitive-data", "injection", "horizontal-authz", "vertical-authz",
    "authentication", "integrity", "audit", "rate-limiting", "secrets",
]
DIMENSION_LABELS = {
    "sensitive-data": "敏感数据",
    "injection": "注入",
    "horizontal-authz": "横向越权·IDOR",
    "vertical-authz": "纵向越权",
    "authentication": "认证",
    "integrity": "完整性·关键操作",
    "audit": "审计",
    "rate-limiting": "限流·滥用",
    "secrets": "密钥·配置",
}
# Facets defined ONLY for dimensions whose catalog enumerates discrete sub-categories.
FACETS = {
    "sensitive-data": ["id-card", "bank-card", "phone", "email", "password", "token"],
    "injection": ["sqli", "xss", "command-injection", "path-traversal", "ssrf",
                  "deserialization", "xxe"],
}
FACET_LABELS = {
    "sensitive-data": {
        "id-card": "身份证号", "bank-card": "银行卡号", "phone": "手机号",
        "email": "邮箱", "password": "密码", "token": "token",
    },
    "injection": {
        "sqli": "SQL 注入", "xss": "XSS", "command-injection": "命令注入",
        "path-traversal": "路径穿越", "ssrf": "SSRF",
        "deserialization": "反序列化", "xxe": "XXE",
    },
}


class FocusInputError(Exception):
    """File missing / unreadable / JSON malformed → exit 1 (a read/parse failure)."""


class FocusViolation(Exception):
    """Closed-set validation violation → exit 2. Carries a list of messages."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = list(messages)


def _load_input(spec_str):
    """Return the parsed JSON object, or raise FocusInputError.

    An argument beginning with `{` is inline JSON; otherwise it is a file path (a
    leading `@` is tolerated and stripped). Missing/unreadable/malformed → exit 1.
    """
    s = spec_str.strip()
    if s.startswith("{"):
        try:
            return json.loads(s)
        except ValueError as e:
            raise FocusInputError(f"malformed inline JSON: {e}")
    if s.startswith("@"):
        s = s[1:]
    p = Path(s)
    if not p.is_file():
        raise FocusInputError(f"focus file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FocusInputError(f"could not read focus file {p}: {e}")


def _render_directive(dims, facets):
    """Deterministic 简体中文 directive. dims/facets already registry-ordered & valid."""
    is_full = set(dims) == set(DIMENSION_KEYS)
    parts = []
    for d in DIMENSION_KEYS:  # registry order, not input order
        if d not in dims:
            continue
        label = DIMENSION_LABELS[d]
        fl = facets.get(d)
        if fl:
            facet_labels = "、".join(FACET_LABELS[d][fc] for fc in fl)
            parts.append(f"{label}({facet_labels})")
        else:
            parts.append(label)
    if is_full:
        # all 9 in scope; narrowing is facet-level only (edge case: "*" + facets)
        return (f"本次安全评审全量扫描 9 个维度,但对以下维度收窄 facet:{'、'.join(parts)}。"
                f"未在括号内列出的 facet 不产该维度缺口、不发相关澄清。")
    return ("本次安全评审仅聚焦以下维度:" + "、".join(parts)
            + "。范围外维度不产安全缺口、不发澄清。")


def _validate_and_build(raw):
    """Validate a parsed spec dict; return resolved focus object or None.

    Raises FocusViolation (closed-set) / FocusInputError (structural, treated as 1).
    None = all 9 + no facets (the no-narrowing default).
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # syntactically valid JSON but wrong shape → closed-set/shape violation (exit 2),
        # not a read/parse failure (exit 1).
        raise FocusViolation(["focus spec must be a JSON object {dimensions, facets}"])
    violations = []

    # --- dimensions ---
    dims_field = raw.get("dimensions", "*")
    if dims_field is None:
        dims_field = "*"
    if dims_field == "*":
        resolved_dims = list(DIMENSION_KEYS)
    elif isinstance(dims_field, list):
        resolved_dims = []
        for d in dims_field:
            if not isinstance(d, str):
                violations.append(f"`dimensions` entry not a string: {d!r}")
                continue
            if d not in DIMENSION_KEYS:
                violations.append(
                    f"unknown dimension key {d!r}; allowed: {', '.join(DIMENSION_KEYS)}")
                continue
            resolved_dims.append(d)
        if not dims_field:
            violations.append("empty `dimensions` list would review nothing; "
                              "omit it or use \"*\" for all 9")
        # de-dup + re-order by REGISTRY order (not input order) → deterministic output
        present = set(resolved_dims)
        resolved_dims = [d for d in DIMENSION_KEYS if d in present]
    else:
        violations.append("`dimensions` must be a list of keys or the literal \"*\"")
        resolved_dims = []

    # --- facets ---
    facets_field = raw.get("facets", {})
    if facets_field is None:
        facets_field = {}
    resolved_facets = {}
    if not isinstance(facets_field, dict):
        violations.append("`facets` must be an object {dimension: [facet, ...]}")
    else:
        for dim, fl in facets_field.items():
            if dim not in resolved_dims:
                violations.append(
                    f"facets entry for {dim!r} but it is not in `dimensions`")
                continue
            if dim not in FACETS:
                violations.append(
                    f"facets entry for {dim!r} but it has no facets "
                    f"(whole-dimension focus only)")
                continue
            if not isinstance(fl, list):
                violations.append(f"facets[{dim!r}] must be a list of facet keys")
                continue
            allowed = FACETS[dim]
            clean = []
            for fc in fl:
                if not isinstance(fc, str):
                    violations.append(f"facets[{dim!r}] entry not a string: {fc!r}")
                    continue
                if fc not in allowed:
                    violations.append(
                        f"unknown facet {fc!r} for {dim!r}; "
                        f"allowed: {', '.join(allowed)}")
                    continue
                clean.append(fc)
            # de-dup + re-order by REGISTRY facet order (not input order) → deterministic
            present = set(clean)
            ordered = [fc for fc in allowed if fc in present]
            if ordered:
                resolved_facets[dim] = ordered

    if violations:
        raise FocusViolation(violations)

    # all 9 dimensions + no facet narrowing = the no-op default → null
    if set(resolved_dims) == set(DIMENSION_KEYS) and not resolved_facets:
        return None
    directive = _render_directive(resolved_dims, resolved_facets)
    return {"dimensions": resolved_dims, "facets": resolved_facets, "directive": directive}


def resolve(spec_str):
    """Parse + validate + render a focus spec string. Returns focus object or None.

    Sibling-import entry point for prepare_augment / ingest_requirements. Raises
    FocusInputError (exit 1) on read/parse failure, FocusViolation (exit 2) on a
    closed-set violation.
    """
    raw = _load_input(spec_str)
    return _validate_and_build(raw)


def validate_resolved(focus):
    """Validate an already-resolved focus field's shape (for --check on change_context).

    Returns a list of violation strings (empty = ok). None / null is valid (= all 9).
    Used by the adapters' --check to reject a malformed `focus` field.
    """
    if focus is None:
        return []
    if not isinstance(focus, dict):
        return ["focus must be an object or null"]
    violations = []
    dims = focus.get("dimensions")
    if not isinstance(dims, list) or not dims:
        violations.append("focus.dimensions must be a non-empty list of dimension keys")
        dim_set = set()
    else:
        dim_set = set()
        for d in dims:
            if not isinstance(d, str) or d not in DIMENSION_KEYS:
                violations.append(
                    f"focus.dimensions unknown key {d!r}; "
                    f"allowed: {', '.join(DIMENSION_KEYS)}")
            else:
                dim_set.add(d)
    facets = focus.get("facets", {})
    if facets is None:
        facets = {}
    if not isinstance(facets, dict):
        violations.append("focus.facets must be an object")
    else:
        for dim, fl in facets.items():
            if dim not in FACETS:
                violations.append(f"focus.facets unknown dimension or facet-less "
                                  f"dimension {dim!r}")
                continue
            if dim not in dim_set:
                violations.append(f"focus.facets[{dim!r}] not listed in focus.dimensions")
                continue
            if not isinstance(fl, list):
                violations.append(f"focus.facets[{dim!r}] must be a list")
                continue
            for fc in fl:
                if not isinstance(fc, str) or fc not in FACETS[dim]:
                    violations.append(
                        f"focus.facets[{dim!r}] unknown facet {fc!r}; "
                        f"allowed: {', '.join(FACETS[dim])}")
    return violations


def registry_listing():
    """The --list payload: 9 dimensions with labels + facet keys/labels (or empty)."""
    dims = []
    for key in DIMENSION_KEYS:
        dims.append({
            "key": key,
            "label": DIMENSION_LABELS[key],
            "facets": [{"key": f, "label": FACET_LABELS[key][f]} for f in FACETS.get(key, [])],
        })
    return {"dimensions": dims}


def _do_resolve(spec_str):
    try:
        focus = resolve(spec_str)
    except FocusInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FocusViolation as v:
        for msg in v.messages:
            print(f"error: {msg}", file=sys.stderr)
        return 2
    kind = "null (all 9 dimensions, no narrowing)" if focus is None else "narrowed"
    print(f"[focus_scope] resolved focus: {kind}", file=sys.stderr)
    print(json.dumps(focus, ensure_ascii=False, indent=2))
    return 0


def _do_check(spec_str):
    try:
        resolve(spec_str)
    except FocusInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except FocusViolation as v:
        summary = {"check": "focus-scope", "ok": False, "violations": v.messages}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        for msg in v.messages:
            print(f"error: {msg}", file=sys.stderr)
        print(f"[focus_scope] --check: ok=False violations={len(v.messages)}",
              file=sys.stderr)
        return 2
    summary = {"check": "focus-scope", "ok": True, "violations": []}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("[focus_scope] --check: ok=True violations=0", file=sys.stderr)
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="closed-set security-dimension focus registry + parse/validate/render "
                    "(--focus backing for /mgh-sra + /mgh-srr)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="enumerate the registry (9 dimensions + facets)")
    mode.add_argument("--parse", metavar="INLINE-JSON|PATH",
                      help="parse + closed-set-validate + render resolved focus (object or null)")
    mode.add_argument("--render", metavar="INLINE-JSON|PATH", help="alias of --parse (render resolved focus)")
    mode.add_argument("--check", metavar="INLINE-JSON|PATH", help="validate only (no render, no side effects)")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(registry_listing(), ensure_ascii=False, indent=2))
        print("[focus_scope] --list: 9 dimensions", file=sys.stderr)
        return 0
    if args.parse is not None:
        return _do_resolve(args.parse)
    if args.render is not None:
        return _do_resolve(args.render)
    if args.check is not None:
        return _do_check(args.check)
    # no actionable mode → print the flag table and STOP (spend no tokens)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
