#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Dev tool: generate the pure-md lens skills for the Claude shell.

Each lens skill is skill-creator compliant (frontmatter name+description,
progressive disclosure) and POINTS to the verbatim prompt in core/prompts/ —
the shell never duplicates prompt content (single source of truth).

Run: py tools/gen_lens_skills.py
"""
from pathlib import Path

HEADER = """<!--
  Lens content is the verbatim ported prompt in {prompt} — referenced, not
  duplicated, so the core is the single source of truth. See
  core/docs/prompt-provenance.md.
-->
"""

LENS = {
    "sast-attack-surface": (
        "s1 attack-surface lens — explore the codebase (or the in-scope file set) "
        "and map the attack surface: file inventory, textual call graph, entry "
        "points, unsafe sinks.",
        "core/prompts/stages/s1-survey.md", "s1 survey lens"),
    "sast-threat-model": (
        "s2 threat-modeling lens — model assets, trust boundaries, and ranked "
        "STRIDE/OWASP threats against the s1 attack surface.",
        "core/prompts/stages/s2-threat-model.md", "s2 threat-model lens"),
    "sast-decompose": (
        "s3 decompose lens — turn the attack surface + threats into analysis "
        "chunks with a per-chunk research lens and hunting hypothesis.",
        "core/prompts/stages/s3-decompose.md", "s3 decompose lens"),
    "sast-adversarial-verify": (
        "s6 adversarial-verify lens — second-opinion review of a candidate "
        "finding; decide TRUE vs FALSE_POSITIVE and assign a CVSS 3.1 vector.",
        "core/prompts/stages/s6-verify.md", "s6 verify lens"),
    "sast-exploit-chain": (
        "s8 exploit-chain lens — construct multi-hop exploit chains from "
        "verified findings and re-rank severity.",
        "core/prompts/stages/s8-chain.md", "s8 chain lens"),
    "sast-lens-crypto": (
        "s4 specialist lens — weak/missing crypto, key & secret handling.",
        "core/prompts/lenses/specialist-hints.md", "crypto specialist lens"),
    "sast-lens-logic": (
        "s4 specialist lens — business-logic flaws, race conditions, TOCTOU.",
        "core/prompts/lenses/specialist-hints.md", "logic-bug specialist lens"),
    "sast-lens-access-control": (
        "s4 specialist lens — authZ, IDOR, privilege escalation, forced browsing.",
        "core/prompts/lenses/specialist-hints.md", "access-control specialist lens"),
    "sast-lens-batch-iac": (
        "s4 specialist lens — batch/ETL data-flow + IaC (Terraform/Dockerfile/"
        "k8s/Helm/GH-Actions/Ansible) misconfiguration.",
        "core/prompts/lenses/specialist-hints.md", "batch-etl + iac specialist lens"),
}

BASE = Path("releases/claude-code/skills")


def main():
    for name, (desc, prompt, short) in LENS.items():
        d = BASE / name
        d.mkdir(parents=True, exist_ok=True)
        body = f"""---
name: {name}
description: {desc}
license: Apache-2.0
---

# {short}

{HEADER.format(prompt=prompt)}Apply the ported prompt at **{prompt}** as your
lens for this stage. It is a verbatim port from vvaharness (Apache-2.0) — use it
unchanged to keep scanning effectiveness aligned with the original pipeline.
"""
        (d / "SKILL.md").write_text(body, encoding="utf-8")
        print(f"  wrote {name}/SKILL.md")
    print(f"[ok] {len(LENS)} lens skills generated")


if __name__ == "__main__":
    main()
