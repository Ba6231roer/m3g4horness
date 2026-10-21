#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Test helper: build a TEMP opencode install mirror.

The dispatch-form resolver judges the host face from the INSTALL PATH of the
copy that is running (`<...>/.opencode/mgh-core/scripts/...` => opencode). Test
suites that exercise the opencode-default native form therefore run the real
leaf scripts from a mirrored tree instead of the dev tree (`core/scripts/`,
which is the `other` face).

The mirror is deliberately a full copy of `core/scripts/*.py` (small files): the
step manifest derives sibling `script_abs` paths, so a partial copy would turn
half the manifest into `None`s. Native assets are opt-in so the missing-asset
fail-loud path can be exercised too.

Not collected by unittest (filename does not match `test_*.py`).
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE_SCRIPTS = ROOT / "core" / "scripts"
AGENT_SRC = ROOT / "releases" / "opencode" / "agent"
NATIVE_AGENT_SRC = AGENT_SRC / "sdr-review-native.md"
NATIVE_FRAGMENT_SRC = (ROOT / "core" / "prompts" / "fragments"
                       / "sdr-native-dispatch.md")
INIT_AGENT_SRC = AGENT_SRC / "init-scout-native.md"
INIT_FRAGMENT_SRC = (ROOT / "core" / "prompts" / "fragments"
                     / "init-scout-native-dispatch.md")
# fix-mgh-init-native-aggregate-dispatch: the init surface widened to five
# twins + two fragments (scout layer; the four aggregate-layer map stages).
INIT_AGG_AGENT_SRCS = tuple(AGENT_SRC / f"{a}.md" for a in (
    "init-induct-native", "init-synthesis-native",
    "init-scout-merge-native", "init-rulewriter-native"))
INIT_AGGREGATE_FRAGMENT_SRC = (ROOT / "core" / "prompts" / "fragments"
                               / "init-aggregate-native-dispatch.md")


def build_opencode_mirror(tmp_root: Path, agent: bool = True,
                          fragment: bool = True, init_agent: bool = True,
                          init_fragment: bool = True,
                          agg_agents: bool = True,
                          agg_fragment: bool = True) -> Path:
    """Create `<tmp>/.opencode/mgh-core/scripts/` with every core script copied.
    `agent`/`fragment` toggle the sdr native assets, `init_agent`/`init_fragment`
    the init scout ones, `agg_agents`/`agg_fragment` the init aggregate-layer
    ones (present = real file copied from the repo; absent = left out so that
    surface's missing-asset fail-closed path can be exercised).
    Returns the mirrored scripts dir."""
    mgh_core = Path(tmp_root) / ".opencode" / "mgh-core"
    scripts = mgh_core / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for src in sorted(CORE_SCRIPTS.glob("*.py")):
        shutil.copy2(src, scripts / src.name)
    if fragment or init_fragment or agg_fragment:
        frag_dir = mgh_core / "prompts" / "fragments"
        frag_dir.mkdir(parents=True, exist_ok=True)
        if fragment:
            shutil.copy2(NATIVE_FRAGMENT_SRC,
                         frag_dir / "sdr-native-dispatch.md")
        if init_fragment:
            shutil.copy2(INIT_FRAGMENT_SRC,
                         frag_dir / "init-scout-native-dispatch.md")
        if agg_fragment:
            shutil.copy2(INIT_AGGREGATE_FRAGMENT_SRC,
                         frag_dir / "init-aggregate-native-dispatch.md")
    agent_files = []
    if agent:
        agent_files.append((NATIVE_AGENT_SRC, "sdr-review-native.md"))
    if init_agent:
        agent_files.append((INIT_AGENT_SRC, "init-scout-native.md"))
    if agg_agents:
        agent_files += [(src, src.name) for src in INIT_AGG_AGENT_SRCS]
    if agent_files:
        agent_dir = mgh_core.parent / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        for src, name in agent_files:
            shutil.copy2(src, agent_dir / name)
    return scripts


def build_claude_mirror(tmp_root: Path) -> Path:
    """Create `<tmp>/.claude/mgh-core/scripts/` with every core script copied —
    the claude-face consumer boundary (must stay subprocess/runner)."""
    mgh_core = Path(tmp_root) / ".claude" / "mgh-core"
    scripts = mgh_core / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for src in sorted(CORE_SCRIPTS.glob("*.py")):
        shutil.copy2(src, scripts / src.name)
    return scripts
