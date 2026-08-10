#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ut-init ack-contract: (A) ut stage prompts + agent defs carry the bounded-ack /
Return-to-orchestrator guardrails; (B) the ut shells' script flags are ALL declared in the
scripts' --help (R5.1, enforced mechanically by tools/check_contracts.py)."""

import subprocess, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROMPTS = ROOT / "core" / "prompts" / "stages"
CLAUDE_AGENTS = ROOT / "releases" / "claude-code" / "agents"
OPENCODE_AGENTS = ROOT / "releases" / "opencode" / "agent"
CHECK_CONTRACTS = ROOT / "tools" / "check_contracts.py"
WRITE_UT_RUNCONFIG = ROOT / "core" / "scripts" / "write_ut_runconfig.py"
UT_SHELLS = [ROOT / "releases" / "claude-code" / "commands" / "mgh-ut-init.md",
             ROOT / "releases" / "opencode" / "command" / "mgh-ut-init.md"]
PY = sys.executable

STAGES = ["ut-extract", "ut-synthesize", "ut-rulewriter", "ut-rules-consistency"]
FAN_OUT_STAGES = ["ut-extract", "ut-rulewriter"]   # bounded-ack fan-out tiers
WHOLE_STAGES = ["ut-synthesize", "ut-rules-consistency"]


class TestUtInitAckContract(unittest.TestCase):
    def test_stages_have_ack_guardrails(self):
        for s in STAGES:
            text = (PROMPTS / f"{s}.md").read_text(encoding="utf-8")
            self.assertIn("Return-to-orchestrator", text, f"{s}: missing Return-to-orchestrator")
            self.assertIn("ok", text, f"{s}: missing ok ack")
            self.assertIn("failed", text, f"{s}: missing failed ack")
            self.assertIn("NEVER", text, f"{s}: missing NEVER")
            # bounded ack: MUST NOT echo record bodies / source back into the orchestrator.
            self.assertRegex(text, r"NEVER.*回显|NEVER 回显", f"{s}: missing bounded-ack guardrail")

    def test_fan_out_stages_write_output_and_touch_done(self):
        # ut-extract writes checkpoint_path (observation record); ut-rulewriter writes
        # rule_path (the rule file). Both touch done_marker and carry the .failed contract.
        out_field = {"ut-extract": "checkpoint_path", "ut-rulewriter": "rule_path"}
        for s in FAN_OUT_STAGES:
            text = (PROMPTS / f"{s}.md").read_text(encoding="utf-8")
            self.assertIn(out_field[s], text, f"{s}: missing {out_field[s]}")
            self.assertIn("done_marker", text, f"{s}: missing done_marker")
            self.assertIn(".failed", text, f"{s}: missing .failed marker contract")

    def test_agent_defs_point_at_stage_prompt(self):
        for s in STAGES:
            for d in (CLAUDE_AGENTS / f"{s}.md", OPENCODE_AGENTS / f"{s}.md"):
                self.assertTrue(d.is_file(), f"missing agent def: {d}")
                text = d.read_text(encoding="utf-8")
                self.assertIn("回传有界 ack", text, f"{d}: missing bounded-ack contract")
                self.assertIn(f"prompts/stages/{s}.md", text, f"{d}: missing stage-prompt pointer")

    def test_shell_flags_all_declared_in_help(self):
        # (B) R5.1: every `py .../script.py --flag` in the ut shells MUST be declared in that
        # script's --help (the contract surface). Enforced mechanically by check_contracts.py.
        r = subprocess.run([PY, str(CHECK_CONTRACTS), "--shells", *[str(p) for p in UT_SHELLS]],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, f"ut shell flags NOT all declared in --help:\n{r.stderr}")

    def test_shells_do_not_advertise_language_or_config(self):
        # F3/F4: the ut shells MUST NOT advertise --language / --config (no backing flag in
        # classify_tests.py / no ut profile) — the Parse-args section is the contract surface
        # an agent reads; a dangling declaration routes the agent into argparse exit 2.
        for shell in UT_SHELLS:
            text = shell.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"--language\b", f"{shell}: still advertises --language")
            self.assertNotRegex(text, r"--config\b", f"{shell}: still advertises --config")

    def test_write_ut_runconfig_keeps_language_reserved(self):
        # --language stays in write_ut_runconfig.py (default JVM, reserved, NOT advertised in
        # the shells) so check_contracts' write_ut_runconfig flag assertion still holds.
        r = subprocess.run([PY, str(WRITE_UT_RUNCONFIG), "--help"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--language", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
