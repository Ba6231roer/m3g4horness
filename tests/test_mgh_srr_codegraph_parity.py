#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""add-mgh-srr claude<->opencode parity + reuse-not-duplication (R5.8).

SRR is a port-adapter over the /mgh-sra middle engine. This asserts:
  (1) both mgh-srr.md shells agree on the codegraph-enrichment surface they inherit from sra
      (--no-codegraph flag + auto detection; codegraph=on|off signal passed verbatim into the
      REUSED a2/a3 subagent tasks; call-path declared optional/codegraph-gated/non-fatal/
      bounded; manifest call_path counts + the codegraph boundary; block-adhoc-scripts guard
      unchanged — no new hook);
  (2) REUSE NOT DUPLICATION — both shells reference the SAME sra-clarify / sra-augment /
      sra-consistency stage prompts + security-dimensions.md + codegraph-hint.md fragments,
      and MUST NOT invent srr-* stage prompts (zero new prompts is the design contract);
  (3) codegraph on/off behavior equivalence — `--no-codegraph` / unavailable detection
      reproduces pre-codegraph behavior (the reused prompts' codegraph=off path).

Run: py tests/test_mgh_srr_codegraph_parity.py
"""
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLAUDE_SHELL = ROOT / "releases" / "claude-code" / "commands" / "mgh-srr.md"
OPENCODE_SHELL = ROOT / "releases" / "opencode" / "command" / "mgh-srr.md"
# the sra stage prompts SRR reuses verbatim (single source of truth — not copied)
SRA_PROMPTS = [
    ROOT / "core" / "prompts" / "stages" / "sra-clarify.md",
    ROOT / "core" / "prompts" / "stages" / "sra-augment.md",
    ROOT / "core" / "prompts" / "stages" / "sra-consistency.md",
]
DIMENSIONS_FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "security-dimensions.md"
HINT_FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "codegraph-hint.md"


class TestShellCodegraphParity(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLAUDE_SHELL.is_file(), f"{CLAUDE_SHELL} missing")
        self.assertTrue(OPENCODE_SHELL.is_file(), f"{OPENCODE_SHELL} missing")
        self.claude = CLAUDE_SHELL.read_text(encoding="utf-8")
        self.opend = OPENCODE_SHELL.read_text(encoding="utf-8")

    def _assert_both(self, needle):
        self.assertIn(needle, self.claude, f"claude shell missing: {needle!r}")
        self.assertIn(needle, self.opend, f"opencode shell missing: {needle!r}")

    def test_both_declare_no_codegraph_flag(self):
        self._assert_both("--no-codegraph")
        self._assert_both("auto")  # default detection mode

    def test_both_declare_detection_stanza(self):
        self._assert_both("command -v codegraph")
        self._assert_both("codegraph=on|off")

    def test_both_pass_signal_into_a2_a3_tasks(self):
        # orchestrator passes codegraph=on|off verbatim into the reused sra-clarify/sra-augment
        self._assert_both("codegraph 信号")

    def test_both_declare_call_path_semantics(self):
        self._assert_both("call_path")
        self._assert_both("non-fatal")
        self._assert_both("bounded")

    def test_both_declare_manifest_call_path_counts(self):
        self._assert_both("call_path_confirmed")
        self._assert_both("call_path_residual")

    def test_both_declare_no_hook_change(self):
        # codegraph_explore/codegraph explore do not hit block-adhoc-scripts
        self._assert_both("block-adhoc-scripts")
        self._assert_both("无 hook 改动")

    def test_both_declare_off_equivalence(self):
        self._assert_both("codegraph=off")


class TestReuseNotDuplication(unittest.TestCase):
    """SRR reuses the sra stage prompts verbatim — both shells MUST point at the same sra-*
    prompts + shared fragments, and MUST NOT invent srr-* stage prompts."""

    def setUp(self):
        self.claude = CLAUDE_SHELL.read_text(encoding="utf-8")
        self.opend = OPENCODE_SHELL.read_text(encoding="utf-8")

    def test_reused_sra_prompts_exist(self):
        for p in SRA_PROMPTS:
            self.assertTrue(p.is_file(), f"reused prompt missing: {p}")

    def test_both_reference_reused_sra_prompts(self):
        for needle in ("sra-clarify", "sra-augment", "sra-consistency"):
            self.assertIn(needle, self.claude, f"claude shell not reusing {needle}")
            self.assertIn(needle, self.opend, f"opencode shell not reusing {needle}")

    def test_both_reference_shared_fragments(self):
        for needle in ("security-dimensions.md", "codegraph-hint.md"):
            self.assertIn(needle, self.claude)
            self.assertIn(needle, self.opend)

    def test_no_duplicated_srr_stage_prompts(self):
        # the design contract is ZERO new stage prompts — srr-* prompts MUST NOT exist
        for fab in ("srr-clarify", "srr-augment", "srr-consistency"):
            self.assertNotIn(fab, self.claude, f"claude shell invents {fab} (duplication)")
            self.assertNotIn(fab, self.opend, f"opencode shell invents {fab} (duplication)")
        # and no srr-* prompt files were created under core/prompts/stages/
        stages = ROOT / "core" / "prompts" / "stages"
        srr_prompts = [p.name for p in stages.glob("srr-*.md")] if stages.is_dir() else []
        self.assertEqual(srr_prompts, [], f"unexpected srr-* stage prompts: {srr_prompts}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
