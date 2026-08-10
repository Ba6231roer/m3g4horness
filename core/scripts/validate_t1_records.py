#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
validate_t1_records — boundary validator for checkpoints/t1/*.json (T1→T2 gate).

Mirrors validate_inventory.py's T2-boundary role at the EARLIER T1 boundary. T1
records are Written by LLM subagents (init-induct); when their output drifts
(e.g. a nested controls[] holding evidence/anchor/confidence instead of
root-level fields), T2 synthesis reads by contract field and silently drops the
record. This validator fails loud at the T1 boundary instead, so the violating
cluster is re-spawned — never carried broken into T2.

--check (default, read-only): for each *.json, strip a leading UTF-8 BOM IN
MEMORY before json.loads (so a BOM is not misread as a shape error), assert
root-level contract fields + no nested controls[] drift signature, emit
violations[]; exit 0 ok / 1 checkpoints dir missing / 2 violation.

--strip-bom: losslessly rewrite each *.json as UTF-8 no-BOM (idempotent; a
no-BOM file is left byte-identical). A leading UTF-8 BOM is a host/Write-tool
artifact (RFC 8259 non-conformance but lossless), so it is deterministically
stripped rather than treated as a shape violation. The orchestrator ALWAYS runs
--strip-bom before --check, so --check never sees a BOM in practice; the in-memory
strip keeps direct/manual --check robust.

Asserts (root-level object, one record per cluster):
  - cluster_id (non-empty string), name (non-empty string);
  - category ∈ canonical 8 (init_tier.INIT_CATEGORIES);
  - kind ∈ vvah 6-enum (auth|sandbox|input-validation|aslr|cfi|other);
  - category→kind matches the deterministic normalization map (init_tier.KIND);
  - evidence is a non-empty list of non-empty string anchors;
  - entry_points is a list; confidence is a number;
  - a root-level controls[] key = "nested controls[] drift" violation
    (the observed scout-cluster drift signature).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/sys/pathlib).

CLI contract (`--help` is the contract surface):
  py validate_t1_records.py --checkpoints <t1-checkpoints-dir> [--check | --strip-bom]

stdout (--check):  {"check":"t1","ok":bool,"records":N,"bom":[files],"violations":[{"file","cluster_id","issue"}]}
stdout (--strip-bom): {"strip-bom":true,"records":N,"stripped":[files]}
stderr = diagnostics. Exit codes: 0 ok · 1 checkpoints dir missing · 2 violation.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

# Self-locate this script's dir so the sibling import resolves under any cwd /
# host-agent invocation (direct `py`/`python`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Canonical 8 categories + category->kind map (single source of truth: init_tier).
from init_tier import KIND, INIT_CATEGORIES  # noqa: E402

VVAH_KINDS = {"auth", "sandbox", "input-validation", "aslr", "cfi", "other"}
_BOM = b"\xef\xbb\xbf"


def _strip_bom_bytes(raw: bytes) -> tuple[bytes, bool]:
    """Remove a leading UTF-8 BOM (EF BB BF). Returns (bytes, had_bom).

    Shared by --check (in-memory) and --strip-bom (disk) so both behaviors agree
    on exactly what 'strip the BOM' means."""
    if raw.startswith(_BOM):
        return raw[len(_BOM):], True
    return raw, False


def _validate_record(rec):
    """Assert contract shape. Returns (cluster_id_or_None, [issue strings]).

    Asserts structural load-bearing fields only; prose fields
    (description/usage/gaps/protects) are NOT asserted (wide legal variance)."""
    if not isinstance(rec, dict):
        return None, ["record not a JSON object"]
    cid = rec.get("cluster_id")
    name = rec.get("name")
    cat = rec.get("category")
    kind = rec.get("kind")
    ev = rec.get("evidence")
    ep = rec.get("entry_points")
    conf = rec.get("confidence")
    cid_s = cid if isinstance(cid, str) and cid.strip() else None
    issues = []
    # Observed scout-cluster drift: evidence/anchor/confidence nested under
    # controls[n] instead of root-level. Defense-in-depth on the known signature;
    # the positive contract (root-level fields present) is the primary guard.
    if isinstance(rec.get("controls"), list):
        issues.append("nested controls[] drift")
    if not cid_s:
        issues.append("missing/empty cluster_id")
    if not (isinstance(name, str) and name.strip()):
        issues.append("missing/empty name")
    if kind not in VVAH_KINDS:
        issues.append(f"kind {kind!r} not in vvah 6-enum")
    if cat not in INIT_CATEGORIES:
        issues.append(f"category {cat!r} not in init 8")
    elif kind and kind != KIND[cat]:
        issues.append(f"category {cat!r} maps to kind {KIND[cat]!r}, got {kind!r}")
    if not isinstance(ev, list) or not ev:
        issues.append("evidence must be a non-empty list")
    else:
        for j, a in enumerate(ev):
            if not isinstance(a, str) or not a.strip():
                issues.append(f"evidence[{j}] anchor must be a non-empty string")
    if not isinstance(ep, list):
        issues.append("entry_points must be a list")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        issues.append("confidence must be a number")
    return cid_s, issues


def _check(files, cp_dir: Path) -> int:
    violations = []
    bom = []
    for f in files:
        try:
            raw = f.read_bytes()
        except OSError as e:
            print(f"warn: unreadable {f}: {e}", file=sys.stderr)
            violations.append({"file": str(f), "cluster_id": None,
                               "issue": "unreadable file"})
            continue
        body, had_bom = _strip_bom_bytes(raw)
        if had_bom:
            bom.append(str(f))
        try:
            rec = json.loads(body.decode("utf-8"))
        except (OSError, ValueError) as e:
            violations.append({"file": str(f), "cluster_id": None,
                               "issue": f"malformed JSON: {e}"})
            continue
        cid, rec_issues = _validate_record(rec)
        for issue in rec_issues:
            violations.append({"file": str(f), "cluster_id": cid, "issue": issue})
    ok = not violations
    print(f"[validate_t1_records] {cp_dir}: records={len(files)}, "
          f"bom={len(bom)}, {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "t1", "ok": ok, "records": len(files),
                      "bom": bom, "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def _strip_bom_mode(files, cp_dir: Path) -> int:
    stripped = []
    for f in files:
        try:
            raw = f.read_bytes()
        except OSError as e:
            print(f"warn: unreadable {f}, skipped: {e}", file=sys.stderr)
            continue
        body, had_bom = _strip_bom_bytes(raw)
        if not had_bom:
            continue  # no BOM → byte-identical, untouched
        try:
            body.decode("utf-8")  # guard: non-UTF-8 skipped, not mangled
        except UnicodeDecodeError as e:
            print(f"warn: {f} not valid UTF-8 after BOM strip, skipped: {e}",
                  file=sys.stderr)
            continue
        tmp = f.parent / (f.name + ".tmp")
        try:
            tmp.write_bytes(body)
            os.replace(tmp, f)
        except OSError as e:
            print(f"warn: failed to rewrite {f}, skipped: {e}", file=sys.stderr)
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            continue
        stripped.append(str(f))
    print(f"[validate_t1_records] --strip-bom {cp_dir}: records={len(files)}, "
          f"stripped={len(stripped)}", file=sys.stderr)
    print(json.dumps({"strip-bom": True, "records": len(files),
                      "stripped": stripped}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="validate checkpoints/t1/*.json at the T1 boundary (T1→T2 gate)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="read-only shape validation (default when no mode given)")
    mode.add_argument("--strip-bom", action="store_true",
                      help="losslessly rewrite each file as UTF-8 no-BOM (idempotent)")
    ap.add_argument("--checkpoints", required=True,
                    help="dir holding checkpoints/t1/*.json")
    args = ap.parse_args()

    cp_dir = Path(args.checkpoints)
    if not cp_dir.is_dir():
        print(f"error: checkpoints dir not found: {cp_dir}", file=sys.stderr)
        return 1

    files = sorted(cp_dir.glob("*.json"))
    if args.strip_bom:
        return _strip_bom_mode(files, cp_dir)
    return _check(files, cp_dir)


if __name__ == "__main__":
    sys.exit(main())
