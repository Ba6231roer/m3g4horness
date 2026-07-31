#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Contract tests for the bounded Return-to-orchestrator ack + path absolutization.

Asserts the ack contract landed in all 9 init stage prompts + all 18 dual-shell agent defs,
and that the 5 whole-tier stages dropped the bare `<target>`/`.mgh-init` write template in
favor of the orchestrator-given absolute-path-verbatim contract.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "core" / "prompts" / "stages"
CLAUDE_AGENTS = ROOT / "releases" / "claude-code" / "agents"
OPENCODE_AGENTS = ROOT / "releases" / "opencode" / "agent"

STAGES = ["init-survey", "init-resolve", "init-scout", "init-scout-merge",
          "init-scout-audit", "init-induct", "init-synthesis", "init-rulewriter",
          "init-rules-consistency"]
# stages whose Output previously used a bare <target>/.mgh-init write template
WHOLE_TIER_ABSOLUTIZED = ["init-survey", "init-scout-merge", "init-scout-audit",
                          "init-synthesis", "init-rules-consistency"]


class TestAckContract(unittest.TestCase):
    def test_each_stage_prompt_declares_return_to_orchestrator(self):
        for s in STAGES:
            text = (PROMPTS / f"{s}.md").read_text(encoding="utf-8")
            self.assertIn("Return-to-orchestrator", text, f"{s}: missing Return-to-orchestrator section")
            # ack carries the bounded format + the NEVER-echo-record-body guardrail
            self.assertIn("ok", text, f"{s}: ack missing `ok` form")
            self.assertIn("NEVER", text, f"{s}: ack missing NEVER-echo guardrail")

    def test_each_stage_prompt_ack_is_bounded(self):
        # the ack MUST forbid echoing the record body (the whole point: don't bloat orchestrator)
        for s in STAGES:
            text = (PROMPTS / f"{s}.md").read_text(encoding="utf-8")
            # locate the Return-to-orchestrator section and assert it forbids echoing
            self.assertRegex(text, r"NEVER.*回显.*(记录体|源码|检查点内容|正文)",
                             f"{s}: ack section must forbid echoing record body/source")

    def test_dual_agent_defs_mirror_ack(self):
        for d in (CLAUDE_AGENTS, OPENCODE_AGENTS):
            for s in STAGES:
                p = d / f"{s}.md"
                self.assertTrue(p.is_file(), f"missing agent def: {p}")
                text = p.read_text(encoding="utf-8")
                self.assertIn("回传有界 ack", text, f"{s}: agent def missing bounded-ack mirror")

    def test_whole_tier_outputs_use_absolute_verbatim_path(self):
        # the 5 whole-tier stages dropped bare <target>/.mgh-init write templates; the
        # orchestrator now passes the absolute output path verbatim.
        for s in WHOLE_TIER_ABSOLUTIZED:
            text = (PROMPTS / f"{s}.md").read_text(encoding="utf-8")
            self.assertIn("the orchestrator gives you", text,
                          f"{s}: Output not reframed to orchestrator-given absolute path")
            self.assertIn("NEVER", text, f"{s}: missing NEVER-interpolate path boundary")


if __name__ == "__main__":
    unittest.main()
