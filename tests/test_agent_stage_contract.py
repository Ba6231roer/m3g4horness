#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Agent/stage operating-contract congruence (fix-mgh-init-distribution-links 1.5,
fanout-dispatch delta). The stage prompt is the single source of behavioral truth;
a per-host agent definition is its loading shell. Three mechanical assertions:

  ① ack 闭合集同形 — the ack forms a fanout/audit agent enumerates MUST be a subset
     of the forms its stage prompt's Return-to-orchestrator section defines (an agent
     enumerating a stage-undefined form — e.g. scout face `oversize` — leaves the
     orchestrator with no legislature for that ack). The dispatcher's `_parse_ack`
     tolerance is a RUNTIME layer and stays; this is the documentation layer.
  ② 权限钉扎不否定 stage 授权 — a stage that sanctions a script invocation via the
     `py` launcher (needs Bash) MUST NOT be loaded by an agent whose frontmatter pins
     `bash: deny` (init-scout-audit was the proven conflict).
  ③ Input 契约完备 — the agent's Input section carries every orchestrator-transmitted
     field the stage's sanctioned behavior needs (`slice_dir` for the audit's
     chunk_sources `--out`).

Run: py tests/test_agent_stage_contract.py
"""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = {
    "opencode": ROOT / "releases" / "opencode" / "agent",
    "claude": ROOT / "releases" / "claude-code" / "agents",
}
STAGES = ROOT / "core" / "prompts" / "stages"
FANOUT_TEMPLATES = ROOT / "core" / "prompts" / "fragments" / "fanout"

# fanout/audit agent → its behavioral truth source (stage prompt, or the dispatcher
# task template for the sdr reviewer, which is self-contained by design).
PAIRS = {
    ("opencode", "init-scout-fanout"): STAGES / "init-scout.md",
    ("opencode", "init-scout-native"): STAGES / "init-scout.md",
    ("opencode", "init-induct-fanout"): STAGES / "init-induct.md",
    ("opencode", "init-synthesis-fanout"): STAGES / "init-synthesis-partial.md",
    ("opencode", "init-synthesis-rollup"): STAGES / "init-synthesis-rollup.md",
    ("opencode", "init-scout-merge-fanout"): STAGES / "init-scout-merge-partial.md",
    ("opencode", "init-scout-merge-rollup"): STAGES / "init-scout-merge-rollup.md",
    ("opencode", "init-rulewriter-fanout"): STAGES / "init-rulewriter.md",
    ("opencode", "init-scout-audit"): STAGES / "init-scout-audit.md",
    ("opencode", "sdr-review-fanout"): FANOUT_TEMPLATES / "sdr-task.md",
    ("claude", "init-scout-audit"): STAGES / "init-scout-audit.md",
    ("claude", "init-scout-merge-fanout"): STAGES / "init-scout-merge-partial.md",
    ("claude", "sdr-review-fanout"): FANOUT_TEMPLATES / "sdr-task.md",
}

ACK_FORM_RX = re.compile(r"`(ok|oversize|failed)\b[^`]*`")
STAGE_ACK_FORM_RX = re.compile(r"^\s*-\s*`(ok|oversize|failed)\b", re.M)
STAGE_RETURN_HEADERS = ("Return-to-orchestrator", "Final reply")


def agent_ack_forms(text: str) -> set:
    """Form words enumerated in the agent's 回传有界 ack bullet."""
    m = re.search(r"回传有界 ack[^:]*:(.*?)(?:\n- |\n\n)", text, re.S)
    if not m:
        return set()
    return set(ACK_FORM_RX.findall(m.group(1)))


def stage_ack_forms(text: str) -> set:
    """Form words defined in the stage's Return-to-orchestrator (or the sdr task
    template's Final reply) section — bullet forms plus inline backticked forms."""
    for header in STAGE_RETURN_HEADERS:
        m = re.search(rf"## {header}[^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m:
            section = m.group(1)
            return (set(STAGE_ACK_FORM_RX.findall(section))
                    | set(ACK_FORM_RX.findall(section)))
    return set()


class TestAckFormsMirrorStageReturn(unittest.TestCase):
    def test_all_pairs_resolve(self):
        for (face, agent), stage in PAIRS.items():
            with self.subTest(pair=f"{face}/{agent}"):
                self.assertTrue((AGENTS[face] / f"{agent}.md").is_file(),
                                f"missing agent file: {face}/{agent}.md")
                self.assertTrue(stage.is_file(), f"missing stage/truth file: {stage}")

    def test_ack_forms_subset_of_stage(self):
        for (face, agent), stage in PAIRS.items():
            with self.subTest(pair=f"{face}/{agent}"):
                a = agent_ack_forms((AGENTS[face] / f"{agent}.md").read_text(encoding="utf-8"))
                s = stage_ack_forms(stage.read_text(encoding="utf-8"))
                self.assertTrue(a, f"{face}/{agent}: no ack enumeration found")
                self.assertTrue(s, f"{stage}: no Return ack forms parsed")
                self.assertFalse(
                    a - s,
                    f"{face}/{agent}: enumerates ack form(s) {sorted(a - s)} its stage "
                    f"({stage.name}) never defines — delete from the agent (stage is "
                    f"the truth source; dispatcher tolerance is a separate layer)")

    def test_scout_failed_ack_semantics_kept_verbatim(self):
        # the scout pair's failure semantics must survive the oversize deletion.
        text = (AGENTS["opencode"] / "init-scout-fanout.md").read_text(encoding="utf-8")
        self.assertIn("touch nothing", text)
        self.assertIn("crash ≠ 确认失败", text)


class TestScoutAuditPinMatchesStageAuthorization(unittest.TestCase):
    def test_stage_sanctions_chunk_sources_invocation(self):
        stage = (STAGES / "init-scout-audit.md").read_text(encoding="utf-8")
        self.assertIn("仅 `chunk_sources.py`", stage,
                      "precondition drifted: the audit stage no longer sanctions the "
                      "chunk_sources invocation — revisit the pin assertion")

    def test_agent_pin_not_negate_stage_authorization(self):
        # opencode dialect: frontmatter permission block; claude dialect: tools:
        # allowlist. Both negate the stage's chunk_sources/Write authorization when
        # Bash / Write are absent-or-denied.
        for face in ("opencode", "claude"):
            with self.subTest(face=face):
                text = (AGENTS[face] / "init-scout-audit.md").read_text(encoding="utf-8")
                fm = text.split("---")[1]
                if face == "opencode":
                    pin = re.search(r"^\s*bash:\s*(\w+)\s*$", fm, re.M)
                    self.assertIsNotNone(pin, "no bash pin in permission block")
                    self.assertNotEqual(
                        pin.group(1), "deny",
                        "init-scout-audit pins bash: deny while its stage sanctions "
                        "the py-launcher chunk_sources call — the pin negates the "
                        "authorization (set bash to the stage-consistent value)")
                else:
                    tools = re.search(r"^tools:\s*(.+)$", fm, re.M)
                    self.assertIsNotNone(tools, "no tools: allowlist line")
                    toolset = {t.strip() for t in tools.group(1).split(",")}
                    self.assertIn("Bash", toolset,
                                  "claude tools: omit Bash — negates the stage's "
                                  "sanctioned chunk_sources invocation")
                    self.assertIn("Write", toolset,
                                  "claude tools: omit Write — negates the stage's "
                                  "mandated audit.json write")

    def test_agent_input_carries_slice_dir(self):
        for face in ("opencode", "claude"):
            with self.subTest(face=face):
                text = (AGENTS[face] / "init-scout-audit.md").read_text(encoding="utf-8")
                input_section = re.search(r"## Input(.*?)(?=\n## )", text, re.S)
                self.assertIsNotNone(input_section, f"{face}: no Input section")
                self.assertIn(
                    "slice_dir", input_section.group(1),
                    f"{face}/init-scout-audit: Input lacks the slice_dir the stage's "
                    f"sanctioned chunk_sources --out needs")


if __name__ == "__main__":
    unittest.main(verbosity=2)
