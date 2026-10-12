#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
gen_dsh_tiers — compile the dsh-dialect agent definitions (`releases/dsh/agents/*.md`)
into the two dsh mounting artifacts (build/install-time peer of gen_release_shells.py;
NOT an /mgh-* orchestrator):

  1. per-tier headless mount files  ->  <out>/<tier>.yml
     (install lands these at <target>/mgh-core/dsh/tiers/; the fanout dispatcher
      references one per spawn via `--patch`, so a missing/stale mount is fatal HERE
      at install time, never at runtime — R5.9 boundary validation);
  2. one delegates patch fragment   ->  <delegates-out>
     (the named interactive delegation instances, `- insert:` rows for the mgh
      profile's managed block; consumed by install wiring, never run directly).

Definition frontmatter (minimal YAML subset, parsed by this file only — stdlib,
no pip deps, per the zero-runtime-dependency product property):
  kind: fanout | delegate
  prompt: <repo-relative leaf SYSTEM prompt path>   (optional — absent = persona
          is fully self-contained in the definition body, e.g. the sdr tier)
  tool_name: <snake_case>                           (delegate only)
  tool_filter: [dsh, tool, names]                   (delegate only)
  description: <one line>
The definition body references the leaf prompt BY PATH (never copies it); this
generator INLINES the leaf prompt text into the mount's persona at compile time
(embedded persona prefix), which is the a-tier mounting shape locked by the
2026-09-23 spike on dsh 0.1.5-rc.2.

CLI (`--help` is the contract surface):
  py gen_dsh_tiers.py --agents <dir> --out <dir> [--delegates-out <file>]
                      [--check]

Fail-loud (exit 2, stderr; R5.3b): a fanout tier in the closed tier set with no
definition or no leaf prompt file; duplicate/missing delegate tool_name; unknown
kind; residual/unknown frontmatter keys; `--check` drift (would-write != exists
for ANY artifact). `--check` NEVER writes.

stdout (R5.3b): {"tiers": [...], "delegates": [...], "action": "written|present"}
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# closed tier set — must equal fanout_runner.TIERS keys (asserted by tests;
# a new tier there without a definition here fails install --check, by design)
REQUIRED_TIERS = ("scout", "scout-merge", "t1", "t2", "t3", "sdr")

# dsh tool plugin modules shipped by the base bundle (measured ids on 0.1.5-rc.2).
# Top-level patching is whole-plugin granularity (no per-tool allow/deny exists on
# the headless face), so tier mounts keep this whitelist and disable the rest.
BASE_TOOL_MODULES = (
    "tool-fs", "tool-fs-search", "tool-bash", "tool-pwsh",
    "tool-web", "tool-jobs", "tool-todo", "tool-goal", "tool-skill",
    "tool-present", "tool-ralph", "tool-workflow", "tool-subagent",
    "tool-subagent-control", "tool-ask-user",
)
TIER_KEEP = ("tool-fs", "tool-fs-search", "tool-bash", "tool-pwsh")

SUBAGENT_PKG = "@deepseek-ai/dsh-tool-subagent"
HEADLESS_PKG = "@deepseek-ai/dsh-headless"
ALLOWED_KEYS = {"kind", "prompt", "tool_name", "tool_filter", "description"}
KNOWN_KINDS = {"fanout", "delegate"}

PERSONA_LEAF_HEADER = (
    "## Stage system prompt (embedded verbatim by the mgh installer)\n\n")
PERSONA_SEP = "\n\n---\n\n## Role addendum (host-dialect mounting)\n\n"


def _die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def _parse_def(path: Path, repo_root: Path):
    """Parse one definition file -> (frontmatter dict, body str). Fail-loud on
    every shape problem (missing fences, unknown/dup/absent keys, bad lists)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        _die(f"{path}: definition must open with a '---' frontmatter fence")
    end = text.find("\n---\n", 3)
    if end == -1:
        _die(f"{path}: unterminated frontmatter fence")
    fm_lines = text[4:end].splitlines()
    body = text[end + 5:].lstrip("\n")
    fm: dict = {}
    for line in fm_lines:
        if not line.strip():
            continue
        if line[:1] in (" ", "\t"):
            _die(f"{path}: indented frontmatter lines are unsupported: {line!r}")
        if ":" not in line:
            _die(f"{path}: frontmatter line without 'key: value': {line!r}")
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if key not in ALLOWED_KEYS:
            _die(f"{path}: unknown frontmatter key {key!r} "
                 f"(allowed: {', '.join(sorted(ALLOWED_KEYS))})")
        if key in fm:
            _die(f"{path}: duplicate frontmatter key {key!r}")
        fm[key] = val
    kind = fm.get("kind")
    if kind not in KNOWN_KINDS:
        _die(f"{path}: kind must be one of {sorted(KNOWN_KINDS)}, got {kind!r}")
    if not fm.get("description"):
        _die(f"{path}: description is required")
    if not body.strip():
        _die(f"{path}: definition body is empty")
    if kind == "delegate":
        tn = fm.get("tool_name", "")
        if not tn or tn != tn.strip():
            _die(f"{path}: delegate needs a non-empty tool_name")
        if not tn.replace("_", "").isalnum() or tn != tn.lower():
            _die(f"{path}: tool_name must be lowercase snake_case, got {tn!r}")
        tf = fm.get("tool_filter", "")
        if not (tf.startswith("[") and tf.endswith("]")):
            _die(f"{path}: delegate needs tool_filter as an inline list [a, b]")
        names = [t.strip() for t in tf[1:-1].split(",") if t.strip()]
        if not names or any(not t.replace("_", "").isalnum() for t in names):
            _die(f"{path}: tool_filter entries must be bare tool names, got {tf!r}")
        fm["tool_filter"] = names
    if "prompt" in fm and fm["prompt"] == "none":
        del fm["prompt"]
    if "prompt" in fm:
        leaf = repo_root / fm["prompt"]
        if not leaf.is_file():
            _die(f"{path}: referenced leaf prompt not found: {leaf}")
        fm["_leaf_text"] = leaf.read_text(encoding="utf-8")
    return fm, body


def _persona(fm: dict, body: str) -> str:
    leaf = fm.get("_leaf_text")
    if leaf:
        return PERSONA_LEAF_HEADER + leaf.rstrip() + PERSONA_SEP + body.rstrip() + "\n"
    return body.rstrip() + "\n"


def _tier_mount(tier: str, persona: str) -> str:
    lines = [
        "- id: headless-runner",
        f"  name: '{HEADLESS_PKG}'",
        "  inject: [headlessStartup]",
        "  config:",
        "    task: !!js process.env.MGH_TASK_TEXT",
        "- id: system-prompt",
        "  config:",
        f"    personaPrefix: {json.dumps(persona, ensure_ascii=False)}",
        "- id: tool-bash",
        "  config:",
        "    enableRunInBackground: false",
        "- id: tool-pwsh",
        "  config:",
        "    enableRunInBackground: false",
    ]
    for mod in BASE_TOOL_MODULES:
        if mod in TIER_KEEP:
            continue
        lines.append(f"- id: {mod}")
        lines.append("  disabled: true")
    header = (f"# mgh dsh tier mount: {tier} — GENERATED by tools/gen_dsh_tiers.py"
              " from releases/dsh/agents/ (do not edit; reinstall regenerates)\n")
    return header + "\n".join(lines) + "\n"


def _delegate_rows(delegates) -> str:
    """delegates: list of (tool_name, persona, tool_filter list) sorted by name."""
    header = ("# mgh dsh named delegation instances — GENERATED by"
              " tools/gen_dsh_tiers.py from releases/dsh/agents/ (do not edit;"
              " install wiring embeds these rows into the mgh profile's managed block)\n")
    out = [header]
    for tool_name, persona, tools in delegates:
        out.append("- insert:")
        out.append(f"    - id: {tool_name.replace('_', '-')}")
        out.append(f"      name: '{SUBAGENT_PKG}'")
        out.append("      config:")
        out.append("        provider: spawn")
        out.append(f"        toolName: {tool_name}")
        out.append(f"        persona: {json.dumps(persona, ensure_ascii=False)}")
        out.append("        toolFilter:")
        out.append(f"          allow: [{', '.join(tools)}]")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(
        description="compile dsh agent definitions into tier mount files + a delegates"
                    " patch fragment (build/install-time generator)")
    ap.add_argument("--agents", required=True,
                    help="directory of dsh-dialect agent definitions (releases/dsh/agents)")
    ap.add_argument("--out", required=True,
                    help="directory for the generated per-tier mount files")
    ap.add_argument("--delegates-out",
                     help="write the named-delegation patch fragment to this file")
    ap.add_argument("--check", action="store_true",
                    help="validate generation + on-disk artifacts are current WITHOUT writing"
                         " (drift/missing -> exit 2)")
    args = ap.parse_args()

    agents_dir = Path(args.agents)
    out_dir = Path(args.out)
    repo_root = Path(__file__).resolve().parent.parent
    if not agents_dir.is_dir():
        _die(f"agents directory not found: {agents_dir}")

    defs = {}
    for path in sorted(agents_dir.glob("*.md")):
        fm, body = _parse_def(path, repo_root)
        defs[path.stem] = (fm, body)

    seen_tool_names = {}
    mounts = {}
    delegates = []
    for name, (fm, body) in defs.items():
        persona = _persona(fm, body)
        if fm["kind"] == "fanout":
            if name not in REQUIRED_TIERS:
                _die(f"{agents_dir / name}.md: fanout tier {name!r} is not in the"
                     f" closed tier set {list(REQUIRED_TIERS)}")
            mounts[name] = _tier_mount(name, persona)
        else:
            tn = fm["tool_name"]
            if tn in seen_tool_names:
                _die(f"duplicate delegate tool_name {tn!r}"
                     f" ({seen_tool_names[tn]} and {name})")
            seen_tool_names[tn] = name
            delegates.append((tn, persona, fm["tool_filter"]))

    missing = [t for t in REQUIRED_TIERS if t not in mounts]
    if missing:
        _die(f"missing fanout tier definition(s): {missing}"
             f" (every tier the dispatcher can run needs releases/dsh/agents/<tier>.md)")

    # fanout tiers must carry a leaf prompt OR a self-contained body; the sdr tier
    # is the documented self-contained one — enforce: prompt absent only for sdr.
    for t in mounts:
        if "prompt" not in defs[t][0] and t != "sdr":
            _die(f"{agents_dir / t}.md: fanout tier {t!r} must reference a leaf"
                 " prompt (only 'sdr' is self-contained by contract)")

    delegates.sort(key=lambda d: d[0])
    want = {out_dir / f"{t}.yml": mounts[t] for t in sorted(mounts)}
    delegate_file = Path(args.delegates_out) if args.delegates_out else None
    if delegate_file is not None:
        want[delegate_file] = _delegate_rows(delegates)

    action = "written"
    if args.check:
        action = "present"
        for path, content in want.items():
            if not path.is_file():
                _die(f"--check: artifact missing: {path}"
                     " (run the generator without --check)")
            if path.read_text(encoding="utf-8") != content:
                _die(f"--check: artifact stale (definitions changed since last"
                     f" generation): {path} — reinstall")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        for path, content in want.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            # LF-pinned: dsh's js-yaml reads either, but byte-stable artifacts make
            # --check drift detection meaningful across platforms.
            path.write_bytes(content.encode("utf-8"))

    print(json.dumps({
        "tiers": sorted(mounts),
        "delegates": [tn for tn, _, _ in delegates],
        "action": action,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
