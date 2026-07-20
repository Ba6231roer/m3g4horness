#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
sensitive_catalog — project-level sensitive-data catalog: closed-set category +
mask registry + parse/validate/render.

Single source of truth for the 10 PIPL / GB-T 35273 sensitive-data categories and
the `mask` level enum. Powers the `--sensitive-catalog` company masking-policy flag
for /mgh-sra (a1 prepare_augment) and /mgh-srr (r1 ingest_requirements): a catalog
is parsed + closed-set-validated + rendered into a deterministic 简体中文 policy
directive, BEFORE any LLM subagent runs. Orthogonal to `--focus` — focus narrows
*which dimensions to scan*; the catalog declares *which field types must be masked*
and extends sensitive-data recognition beyond the legacy 6 facets.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/re/sys/pathlib). Self-locating
(sys.path.insert(0, dir-of-__file__)) so the sibling import from prepare_augment /
ingest_requirements resolves under any cwd. Reads any catalog file with
encoding="utf-8". Idempotent + side-effect-free (--list/--parse/--check write
nothing to disk).

CLI contract (`--help` is the contract surface, R5.1):
  py sensitive_catalog.py --list
  py sensitive_catalog.py --parse <inline-json|@path|->
  py sensitive_catalog.py --check <inline-json|@path|->

  --list                 enumerate the closed-set categories + the PIPL/GB-T 35273
                         37-item default template (label/mask/rule per item)
  --parse <json|@path|-> parse + closed-set-validate + render the resolved catalog
                         ({version, source, categories[], items[], counts{}, directive})
  --check <json|@path|-> validate only (no render, no side effects)

Input form (unambiguous): an argument beginning with `{` is inline JSON; `-` is
stdin; any other value is a UTF-8 JSON file path (a leading `@` is tolerated and
stripped; missing/unreadable file exits 1). Catalog schema:
  {"version": <int>, "items": {"<category>/<field-type>": {label, mask, rule}, ...}}
category ∈ closed-set 10; mask ∈ {full, partial}; field-type = open company vocab.

stdout = structured JSON (resolved catalog / default template / check verdict);
stderr = diagnostics/progress only (R5.3b). Exit codes: 0 ok · 1 file missing /
stdin unread / JSON malformed · 2 misuse (argparse) or closed-set validation
violation (unknown category / illegal mask / malformed key or shape) (R5.3b).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

# Self-locate so the sibling import (prepare_augment / ingest_requirements) resolves
# under any cwd / host-agent invocation (R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── closed-set registry: single source of truth (PIPL / GB-T 35273 categories) ──
# Adding a category is a registry + catalog co-change (closed-set, never free-text).
CATEGORIES = [
    "identity-doc", "biometric", "health", "financial", "location",
    "communication", "device", "vehicle", "general-pii", "legal",
]
CATEGORY_LABELS = {
    "identity-doc": "身份证件",
    "biometric": "生物识别",
    "health": "健康生理",
    "financial": "金融账号",
    "location": "位置轨迹",
    "communication": "通信",
    "device": "设备标识",
    "vehicle": "车辆",
    "general-pii": "一般 PII",
    "legal": "法律",
}
MASK_LEVELS = ("full", "partial")

# field-type key regex (category-validated separately); open company vocab.
_KEY_RX = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")

# ── PIPL / GB-T 35273 default template: 37 items across the 10 categories ──
# mask: full = 不可展示原始值;partial = 保留 rule 描述的部分。公司可裁剪/加严。
# Provenance: PIPL(《个人信息保护法》)+ GB-T 35273《个人信息安全规范》个人敏感信息分类。
DEFAULT_TEMPLATE = {
    "version": 1,
    "provenance": "PIPL(个人信息保护法) / GB-T 35273(个人信息安全规范)个人敏感信息分类 + 公司合规加严",
    "items": {
        # 身份证件 (8)
        "identity-doc/id-number": {"label": "身份证号", "mask": "partial", "rule": "保留前6后4位"},
        "identity-doc/officer-number": {"label": "军官号", "mask": "partial", "rule": "保留末2位"},
        "identity-doc/passport-number": {"label": "护照号", "mask": "partial", "rule": "保留末2位"},
        "identity-doc/driver-license-number": {"label": "驾照档案号", "mask": "partial", "rule": "保留末4位"},
        "identity-doc/housing-fund-account": {"label": "公积金账号", "mask": "partial", "rule": "保留末4位"},
        "identity-doc/social-security-number": {"label": "社保号", "mask": "partial", "rule": "保留末4位"},
        "identity-doc/residence-permit-number": {"label": "居住证号", "mask": "partial", "rule": "保留末4位"},
        "identity-doc/other-id": {"label": "其他证件信息", "mask": "full", "rule": None},
        # 生物识别 (10)
        "biometric/photo": {"label": "照片", "mask": "partial", "rule": "模糊面部区域"},
        "biometric/iris": {"label": "虹膜", "mask": "full", "rule": None},
        "biometric/fingerprint": {"label": "指纹", "mask": "full", "rule": None},
        "biometric/palmprint": {"label": "掌纹", "mask": "full", "rule": None},
        "biometric/voiceprint": {"label": "声纹", "mask": "full", "rule": None},
        "biometric/ear-shape": {"label": "耳廓", "mask": "full", "rule": None},
        "biometric/face-features": {"label": "面部识别特征", "mask": "full", "rule": None},
        "biometric/genetic-data": {"label": "个人基因识别数据", "mask": "full", "rule": None},
        "biometric/genetic-disease": {"label": "遗传疾病(个人生物特征)", "mask": "full", "rule": None},
        "biometric/other": {"label": "其他生物特征信息", "mask": "full", "rule": None},
        # 健康生理 (2)
        "health/health-info": {"label": "健康生理信息", "mask": "partial", "rule": "脱敏为健康类别"},
        "health/fertility": {"label": "生育情况", "mask": "partial", "rule": "脱敏为是否生育"},
        # 金融账号 (4)
        "financial/card-no": {"label": "银行卡卡号", "mask": "partial", "rule": "保留后4位"},
        "financial/card-expiry": {"label": "银行卡有效期", "mask": "partial", "rule": "仅保留到期月"},
        "financial/asset-account": {"label": "金融资产账号", "mask": "partial", "rule": "保留末4位"},
        "financial/credit-info": {"label": "征信信息", "mask": "partial", "rule": "脱敏为信用等级"},
        # 位置轨迹 (2)
        "location/precise": {"label": "精确定位信息", "mask": "partial", "rule": "降精度至行政区"},
        "location/trajectory": {"label": "行踪轨迹", "mask": "full", "rule": None},
        # 通信 (2)
        "communication/records": {"label": "通信记录和内容", "mask": "partial", "rule": "保留元数据、脱敏正文"},
        "communication/net-account": {"label": "网络账号", "mask": "partial", "rule": "保留平台名、掩账号"},
        # 设备标识 (4)
        "device/mac": {"label": "MAC 地址", "mask": "partial", "rule": "保留厂商前缀"},
        "device/device-id": {"label": "设备号(device id)", "mask": "partial", "rule": "保留末4位"},
        "device/imei": {"label": "IMEI", "mask": "partial", "rule": "保留末4位"},
        "device/idfa": {"label": "IDFA", "mask": "partial", "rule": "保留末4位"},
        # 车辆 (2)
        "vehicle/plate": {"label": "车牌号", "mask": "partial", "rule": "保留省份与序号段"},
        "vehicle/vin": {"label": "车辆识别码(车架号)", "mask": "partial", "rule": "保留末4位"},
        # 一般 PII (2)
        "general-pii/name": {"label": "姓名", "mask": "partial", "rule": "保留姓"},
        "general-pii/address": {"label": "详细地址", "mask": "partial", "rule": "截到行政区"},
        # 法律 (1)
        "legal/undisclosed-record": {"label": "未公开的违法和犯罪记录", "mask": "full", "rule": None},
    },
}


class CatalogInputError(Exception):
    """File missing / unreadable / stdin error / JSON malformed → exit 1."""


class CatalogViolation(Exception):
    """Closed-set / shape validation violation → exit 2. Carries a list of messages."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = list(messages)


def _load_input(spec_str):
    """Return (parsed JSON object, source_str). Raise CatalogInputError on read/parse failure.

    An argument beginning with `{` is inline JSON; `-` is stdin; otherwise a file
    path (a leading `@` is tolerated and stripped). Missing/unreadable/malformed → exit 1.
    """
    s = spec_str.strip()
    if s == "-":
        try:
            return json.loads(sys.stdin.read()), "stdin"
        except ValueError as e:
            raise CatalogInputError(f"malformed stdin JSON: {e}")
    if s.startswith("{"):
        try:
            return json.loads(s), "inline"
        except ValueError as e:
            raise CatalogInputError(f"malformed inline JSON: {e}")
    if s.startswith("@"):
        s = s[1:]
    p = Path(s)
    if not p.is_file():
        raise CatalogInputError(f"catalog file not found: {p}")
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except (OSError, ValueError) as e:
        raise CatalogInputError(f"could not read catalog file {p}: {e}")


def _render_directive(cats, items, full, partial):
    """Deterministic 简体中文 policy directive. cats/items already registry-ordered."""
    cat_phrase = "、".join(CATEGORY_LABELS[c] for c in cats)
    return (
        f"本次据公司敏感数据目录评审:覆盖 {len(cats)} 个类别({cat_phrase})、"
        f"{len(items)} 个必屏蔽字段类型(全屏蔽 {full} 项、部分屏蔽 {partial} 项)。"
        f"须按各项 mask 规则在 at-rest / in-transit / log / response 四处脱敏;"
        f"未按规则脱敏的字段即记一条 sensitive-data 缺口并标 catalog_key。"
        f"无目录时仅按现行 6 facet(id-card/bank-card/phone/email/password/token)识别敏感数据。")


def _validate_and_build(raw, source):
    """Validate a parsed catalog dict; return the resolved catalog object.

    Raises CatalogViolation (closed-set/shape → exit 2). Returns the resolved object
    {version, source, categories[], items[], counts{}, directive}.
    """
    if not isinstance(raw, dict):
        raise CatalogViolation(["catalog must be a JSON object {version, items}"])
    violations = []
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        violations.append("`version` must be an integer (e.g. 1)")
    items_field = raw.get("items")
    if not isinstance(items_field, dict) or not items_field:
        violations.append(
            "`items` must be a non-empty object {\"<category>/<field-type>\": {label, mask, rule}}")
    if violations:
        raise CatalogViolation(violations)

    clean = {}
    violations = []
    for key, entry in items_field.items():
        if not isinstance(key, str) or not _KEY_RX.match(key):
            violations.append(
                f"item key {key!r} must be `<category>/<field-type>` (lowercase kebab); "
                f"allowed categories: {', '.join(CATEGORIES)}")
            continue
        cat = key.split("/", 1)[0]
        if cat not in CATEGORIES:
            violations.append(
                f"item key {key!r}: unknown category {cat!r}; allowed: {', '.join(CATEGORIES)}")
        if not isinstance(entry, dict):
            violations.append(f"item {key!r}: entry must be an object with label/mask/rule")
            continue
        label = entry.get("label")
        if not isinstance(label, str) or not label.strip():
            violations.append(f"item {key!r}: `label` must be a non-empty string")
        mask = entry.get("mask")
        if mask not in MASK_LEVELS:
            violations.append(
                f"item {key!r}: `mask` must be one of {', '.join(MASK_LEVELS)} (got {mask!r})")
        rule = entry.get("rule")
        if not (rule is None or isinstance(rule, str)):
            violations.append(f"item {key!r}: `rule` must be a string or null")
        if cat in CATEGORIES and mask in MASK_LEVELS:
            clean[key] = {"label": label, "mask": mask, "rule": rule}
    if violations:
        raise CatalogViolation(violations)

    # de-dup (dict keys unique by construction) + re-order by REGISTRY category order
    # then field-type → deterministic output (not input order).
    def _sort_key(k):
        cat, ftype = k.split("/", 1)
        return (CATEGORIES.index(cat), ftype)

    items = []
    for k in sorted(clean.keys(), key=_sort_key):
        cat = k.split("/", 1)[0]
        e = clean[k]
        items.append({"key": k, "category": cat, "label": e["label"],
                      "mask": e["mask"], "rule": e["rule"]})
    cats_present = [c for c in CATEGORIES if any(it["category"] == c for it in items)]
    full = sum(1 for it in items if it["mask"] == "full")
    partial = sum(1 for it in items if it["mask"] == "partial")
    counts = {"items": len(items), "full": full, "partial": partial,
              "categories": len(cats_present)}
    directive = _render_directive(cats_present, items, full, partial)
    return {"version": version, "source": source, "categories": cats_present,
            "items": items, "counts": counts, "directive": directive}


def resolve(spec_str):
    """Parse + validate + render a catalog spec string. Returns the resolved object.

    Sibling-import entry point for prepare_augment / ingest_requirements. Raises
    CatalogInputError (exit 1) on read/parse failure, CatalogViolation (exit 2) on a
    closed-set/shape violation.
    """
    raw, source = _load_input(spec_str)
    return _validate_and_build(raw, source)


def validate_resolved(catalog):
    """Validate an already-resolved `sensitive_catalog` field's shape (for --check on
    change_context). Returns a list of violation strings (empty = ok). None = valid
    (= no catalog, legacy 6 facets). Used by the adapters' --check."""
    if catalog is None:
        return []
    if not isinstance(catalog, dict):
        return ["sensitive_catalog must be an object or null"]
    v = []
    version = catalog.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        v.append("sensitive_catalog.version must be an integer")
    cats = catalog.get("categories")
    if not isinstance(cats, list):
        v.append("sensitive_catalog.categories must be a list")
        cat_count = 0
    else:
        cat_count = len(cats)
        for c in cats:
            if c not in CATEGORIES:
                v.append(f"sensitive_catalog.categories unknown key {c!r}; "
                         f"allowed: {', '.join(CATEGORIES)}")
    items = catalog.get("items")
    if not isinstance(items, list):
        v.append("sensitive_catalog.items must be a list")
        items = []
    full = partial = 0
    for it in items:
        if not isinstance(it, dict):
            v.append("sensitive_catalog.items entry must be an object")
            continue
        key = it.get("key")
        cat = it.get("category")
        if not isinstance(key, str) or not _KEY_RX.match(key):
            v.append(f"sensitive_catalog item key invalid: {key!r}")
        elif key.split("/", 1)[0] != cat:
            v.append(f"sensitive_catalog item {key!r}: category mismatch (got {cat!r})")
        if cat not in CATEGORIES:
            v.append(f"sensitive_catalog item {key!r}: unknown category {cat!r}")
        label = it.get("label")
        if not isinstance(label, str) or not label.strip():
            v.append(f"sensitive_catalog item {key!r}: label must be non-empty")
        mask = it.get("mask")
        if mask not in MASK_LEVELS:
            v.append(f"sensitive_catalog item {key!r}: mask must be full|partial (got {mask!r})")
        elif mask == "full":
            full += 1
        else:
            partial += 1
        rule = it.get("rule")
        if not (rule is None or isinstance(rule, str)):
            v.append(f"sensitive_catalog item {key!r}: rule must be string|null")
    counts = catalog.get("counts")
    if not isinstance(counts, dict):
        v.append("sensitive_catalog.counts must be an object")
    else:
        if counts.get("items") != len(items):
            v.append(f"sensitive_catalog.counts.items mismatch "
                     f"(got {counts.get('items')}, expected {len(items)})")
        if counts.get("full") != full:
            v.append(f"sensitive_catalog.counts.full mismatch (got {counts.get('full')}, expected {full})")
        if counts.get("partial") != partial:
            v.append(f"sensitive_catalog.counts.partial mismatch (got {counts.get('partial')}, expected {partial})")
        if counts.get("categories") != cat_count:
            v.append(f"sensitive_catalog.counts.categories mismatch "
                     f"(got {counts.get('categories')}, expected {cat_count})")
    return v


def default_listing():
    """The --list payload: closed-set categories + mask levels + the default template."""
    return {
        "categories": [{"key": c, "label": CATEGORY_LABELS[c]} for c in CATEGORIES],
        "mask_levels": list(MASK_LEVELS),
        "default_template": DEFAULT_TEMPLATE,
    }


def _do_parse(spec_str):
    try:
        catalog = resolve(spec_str)
    except CatalogInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except CatalogViolation as v:
        for msg in v.messages:
            print(f"error: {msg}", file=sys.stderr)
        return 2
    print(f"[sensitive_catalog] resolved catalog: {catalog['counts']['items']} items "
          f"({catalog['counts']['categories']} categories, "
          f"full={catalog['counts']['full']} partial={catalog['counts']['partial']})",
          file=sys.stderr)
    print(json.dumps(catalog, ensure_ascii=False, indent=2))
    return 0


def _do_check(spec_str):
    try:
        resolve(spec_str)
    except CatalogInputError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except CatalogViolation as v:
        summary = {"check": "sensitive-catalog", "ok": False, "violations": v.messages}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        for msg in v.messages:
            print(f"error: {msg}", file=sys.stderr)
        print(f"[sensitive_catalog] --check: ok=False violations={len(v.messages)}",
              file=sys.stderr)
        return 2
    summary = {"check": "sensitive-catalog", "ok": True, "violations": []}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("[sensitive_catalog] --check: ok=True violations=0", file=sys.stderr)
    return 0


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="project-level sensitive-data catalog: closed-set category + mask "
                    "registry + parse/validate/render (--sensitive-catalog backing for "
                    "/mgh-sra + /mgh-srr)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true",
                      help="enumerate the closed-set categories + PIPL/GB-T 35273 37-item default template")
    mode.add_argument("--parse", metavar="INLINE-JSON|@PATH|-",
                      help="parse + closed-set-validate + render resolved catalog object")
    mode.add_argument("--check", metavar="INLINE-JSON|@PATH|-",
                      help="validate only (no render, no side effects)")
    args = ap.parse_args()

    if args.list:
        print(json.dumps(default_listing(), ensure_ascii=False, indent=2))
        print(f"[sensitive_catalog] --list: {len(CATEGORIES)} categories, "
              f"{len(DEFAULT_TEMPLATE['items'])}-item default template", file=sys.stderr)
        return 0
    if args.parse is not None:
        return _do_parse(args.parse)
    if args.check is not None:
        return _do_check(args.check)
    # no actionable mode → print the flag table and STOP (spend no tokens)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
