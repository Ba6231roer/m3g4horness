#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Dev-time prompt extractor for mgh-sast (BUILD TOOL — not shipped to .claude/.opencode).

Reads the vvaharness source tree with the stdlib `ast` module and emits the
prompt constants verbatim into core/prompts/*.md with an Apache-2.0 header and a
source pointer. This guarantees faithful porting WITHOUT a runtime dependency on
vvaharness (we never import it; we parse its source text).

Run:  py tools/extract_prompts.py [--vvaharness PATH] [--out PATH]
  default --vvaharness = C:/DEV/visa-vulnerability-agentic-harness/vvaharness
            --out      = ./core/prompts
"""
from __future__ import annotations
import ast
import sys
import argparse
import textwrap
from pathlib import Path

HEADER = """<!--
  Ported from vvaharness (Visa, Inc. / Project Glasswing), Apache-2.0.
  Source: {src}
  Fidelity: {fidelity}
  Extracted verbatim by tools/extract_prompts.py (content-only; no
  runtime dependency on vvaharness). See core/docs/NOTICE and
  core/docs/prompt-provenance.md.
-->

"""


def render(node, fidelity_box):
    """Render an ast value node to text. fidelity_box is a 1-element list to
    return the assigned fidelity label."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        fidelity_box[0] = "verbatim"
        return node.value
    if isinstance(node, ast.JoinedStr):
        # f-string: reconstruct literal text, keeping {expr} placeholders.
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue):
                out.append("{" + ast.unparse(part.value) + "}")
            else:
                out.append("{" + ast.unparse(part) + "}")
        fidelity_box[0] = "verbatim (f-string; interpolation placeholders preserved)"
        return "".join(out)
    if isinstance(node, ast.Dict):
        lines = []
        for k, v in zip(node.keys, node.values):
            kk = ast.literal_eval(k) if k else "<dyn>"
            try:
                vv = ast.literal_eval(v)
            except Exception:
                vv = ast.unparse(v)
            if isinstance(vv, (list, tuple)):
                vv = "\n".join(f"    - {x}" for x in vv)
            lines.append(f"### {kk}\n{vv}")
        fidelity_box[0] = "verbatim (dict literal rendered as markdown)"
        return "\n\n".join(lines)
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [ast.literal_eval(e) for e in node.elts
                 if isinstance(e, ast.Constant)]
        fidelity_box[0] = "verbatim (list literal)"
        return "\n".join(f"- {x}" for x in items)
    fidelity_box[0] = f"light-adapt (unhandled node: {type(node).__name__})"
    return ast.unparse(node)


def extract_const(src_path: Path, name: str):
    """Return (text, source_ref, fidelity) for top-level assignment `name`."""
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))
    assigns = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                assigns.append((tgt, node.value))
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assigns.append((node.target, node.value))
    for tgt, val in assigns:
        if isinstance(tgt, ast.Name) and tgt.id == name:
            fid = [None]
            text = render(val, fid)
            rel = f"{src_path.relative_to(REPO_ROOT).as_posix()}::{name}"
            return text, rel, fid[0]
    return None, None, None


def write_prompt(out_root: Path, rel_path: str, text: str, src: str, fidelity: str):
    p = out_root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(HEADER.format(src=src, fidelity=fidelity) + text.rstrip() + "\n",
                 encoding="utf-8")
    print(f"  wrote {p.relative_to(out_root)}  [{fidelity}]")


# (module rel-path, const name, output rel-path) — s4 SYSTEM is hand-composed.
TARGETS = [
    ("vvaharness/pipeline/stages/s1_preprocess.py", "SYSTEM", "stages/s1-survey.md"),
    ("vvaharness/pipeline/stages/s2_threatmodel.py", "SYSTEM", "stages/s2-threat-model.md"),
    ("vvaharness/pipeline/stages/s2_threatmodel.py", "_BASELINES", "baselines/s2-baselines.md"),
    ("vvaharness/pipeline/stages/s2_threatmodel.py", "_STRIDE_BY_KIND", "baselines/s2-stride-by-kind.md"),
    ("vvaharness/pipeline/stages/s3_decompose.py", "SYSTEM", "stages/s3-decompose.md"),
    ("vvaharness/pipeline/stages/s4_deepdive.py", "_QUALITY_BAR", "stages/s4-quality-bar.md"),
    ("vvaharness/pipeline/stages/s4_deepdive.py", "_OUTPUT_SCHEMA", "stages/s4-output-schema.md"),
    ("vvaharness/pipeline/stages/s6_verify.py", "SYSTEM", "stages/s6-verify.md"),
    ("vvaharness/pipeline/stages/s7_dedup.py", "SYSTEM", "stages/s7-dedup.md"),
    ("vvaharness/pipeline/stages/s8_chain.py", "SYSTEM", "stages/s8-chain.md"),
    ("vvaharness/lang/hints.py", "SPECIALIST_HINTS", "lenses/specialist-hints.md"),
    ("vvaharness/util/prompts.py", "EXCLUSION_RULES", "fragments/exclusion-rules.md"),
    ("vvaharness/util/prompts.py", "SELF_VERIFICATION", "fragments/self-verification.md"),
    ("vvaharness/util/prompts.py", "EXHAUSTIVENESS", "fragments/exhaustiveness.md"),
    ("vvaharness/util/prompts.py", "SEVERITY_GUIDANCE", "fragments/severity-guidance.md"),
]

REPO_ROOT: Path


def main():
    global REPO_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--vvaharness", default="C:/DEV/visa-vulnerability-agentic-harness/vvaharness")
    ap.add_argument("--out", default="./core/prompts")
    ap.add_argument("--repo-root", default=".")
    args = ap.parse_args()
    REPO_ROOT = Path(args.repo_root).resolve()
    vva = Path(args.vvaharness).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(f"extracting from {vva} -> {out}")
    missing = []
    for mod_rel, const, out_rel in TARGETS:
        src_path = (REPO_ROOT / mod_rel) if (REPO_ROOT / mod_rel).exists() else (vva.parent.parent / mod_rel)
        if not src_path.exists():
            src_path = vva.parent / "pipeline/stages" / Path(mod_rel).name  # fallback
        text, src, fid = extract_const(src_path, const)
        if text is None:
            missing.append(f"{mod_rel}::{const}")
            continue
        write_prompt(out, out_rel, text, src, fid)
    if missing:
        print("\nWARN — could not extract (manual port needed):")
        for m in missing:
            print(f"  - {m}")
        return 1
    print("\n[ok] extraction complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
