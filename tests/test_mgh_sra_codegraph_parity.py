#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""improve-mgh-sra-codegraph-enrichment claude<->opencode parity (R5.8).

Asserts both mgh-sra.md shells agree on the codegraph-enrichment surface:
  --no-codegraph flag, codegraph-hint fragment reference, detection stanza
  (after a1, zero LLM token), codegraph=on|off signal passed verbatim into
  a2/a3 subagent tasks, call-path confirmation declared optional/codegraph-gated/
  non-fatal/bounded, manifest call_path counts + 5th boundary; and that the
  sra-augment / sra-clarify / sra-consistency stage prompts + both agent defs
  carry the required hard constraints (Sanctioned-tools allowlist incl. codegraph
  MCP/CLI + Read fallback; draft_path/clarify_path/drafts_dir verbatim;
  call_path advisory-only + confirmed-not-fabricated; NEVER Write .py / py -c).
Also covers cross-change fragment parity (D8): core/prompts/fragments/codegraph-
hint.md is the SAME prescriptive fragment the sibling init change owns, so this
change co-owns it idempotently (no SRA-specific content leaks into it).
Run: py tests/test_mgh_sra_codegraph_parity.py
"""
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLAUDE_SHELL = ROOT / "releases" / "claude-code" / "commands" / "mgh-sra.md"
OPENCODE_SHELL = ROOT / "releases" / "opencode" / "command" / "mgh-sra.md"
AUGMENT_PROMPT = ROOT / "core" / "prompts" / "stages" / "sra-augment.md"
CLARIFY_PROMPT = ROOT / "core" / "prompts" / "stages" / "sra-clarify.md"
CONSISTENCY_PROMPT = ROOT / "core" / "prompts" / "stages" / "sra-consistency.md"
HINT_FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "codegraph-hint.md"
AUG_CONTRACT = ROOT / "core" / "contracts" / "sra" / "augmentation.md"
CLAUDE_AUGMENT_AGENT = ROOT / "releases" / "claude-code" / "agents" / "sra-augment.md"
OPENCODE_AUGMENT_AGENT = ROOT / "releases" / "opencode" / "agent" / "sra-augment.md"
CLAUDE_CLARIFY_AGENT = ROOT / "releases" / "claude-code" / "agents" / "sra-clarify.md"
OPENCODE_CLARIFY_AGENT = ROOT / "releases" / "opencode" / "agent" / "sra-clarify.md"
CLAUDE_CONSISTENCY_AGENT = ROOT / "releases" / "claude-code" / "agents" / "sra-consistency.md"
OPENCODE_CONSISTENCY_AGENT = ROOT / "releases" / "opencode" / "agent" / "sra-consistency.md"


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

    def test_both_reference_hint_fragment(self):
        self._assert_both("codegraph-hint.md")

    def test_both_declare_detection_stanza(self):
        self._assert_both("command -v codegraph")
        self._assert_both("codegraph=on|off")

    def test_both_pass_signal_into_a2_a3_tasks(self):
        # orchestrator passes codegraph=on|off verbatim into sra-clarify/sra-augment
        self._assert_both("codegraph 信号")

    def test_both_declare_call_path_semantics(self):
        # optional / codegraph-gated / non-fatal / bounded advisory
        self._assert_both("call_path")
        self._assert_both("codegraph=on")
        self._assert_both("non-fatal")
        self._assert_both("bounded")

    def test_both_declare_manifest_call_path_counts(self):
        self._assert_both("call_path_confirmed")
        self._assert_both("call_path_residual")

    def test_both_declare_no_hook_change(self):
        # codegraph_explore/codegraph explore do not hit block-adhoc-scripts
        self._assert_both("block-adhoc-scripts")
        self._assert_both("无 hook 改动")


class TestSraAugmentPrompt(unittest.TestCase):
    def test_required_sections_present(self):
        self.assertTrue(AUGMENT_PROMPT.is_file(), f"{AUGMENT_PROMPT} missing")
        text = AUGMENT_PROMPT.read_text(encoding="utf-8")
        # codegraph=on stanza + fragment reference
        self.assertIn("codegraph enrichment", text)
        self.assertIn("codegraph-hint.md", text)
        self.assertIn("codegraph_explore", text)
        self.assertIn("codegraph explore", text)
        # call-path confirmation (4 facets); call_path is the only structured field
        self.assertIn("Task 3", text)
        self.assertIn("call-path", text)
        self.assertIn("data-flow", text)
        self.assertIn("liveness", text)
        self.assertIn("domain-sibling", text)
        self.assertIn("call_path", text)
        self.assertIn("confirmed", text)   # true|false|null tri-state
        # bounded + fail-soft + advisory-only
        self.assertIn("Bounded", text)
        self.assertIn("MUST NOT", text)
        # Sanctioned-tools allowlist incl. codegraph MCP/CLI + Read fallback
        self.assertIn("Sanctioned tools", text)
        # draft_path verbatim; NEVER Write .py / py -c
        self.assertIn("draft_path", text)
        self.assertIn("NEVER", text)
        self.assertIn("py -c", text)

    def test_off_behavior_byte_identical_note(self):
        # codegraph=off -> no call_path field, no advisory, main flow unaffected
        text = AUGMENT_PROMPT.read_text(encoding="utf-8")
        self.assertIn("codegraph=off", text)


class TestSraClarifyPrompt(unittest.TestCase):
    def test_codegraph_advisory_callers_stanza(self):
        self.assertTrue(CLARIFY_PROMPT.is_file(), f"{CLARIFY_PROMPT} missing")
        text = CLARIFY_PROMPT.read_text(encoding="utf-8")
        self.assertIn("codegraph enrichment", text)
        self.assertIn("codegraph-hint.md", text)
        # advisory pre-resolution reduces questions, never overrides user/code,
        # never writes codegraph-derived memory
        self.assertIn("减问", text)
        self.assertIn("MUST NOT", text)
        self.assertIn("codegraph=off", text)


class TestSraConsistencyPrompt(unittest.TestCase):
    def test_call_path_pass_through_no_recompute(self):
        self.assertTrue(CONSISTENCY_PROMPT.is_file(), f"{CONSISTENCY_PROMPT} missing")
        text = CONSISTENCY_PROMPT.read_text(encoding="utf-8")
        # a4 passes through + normalizes call_path wording, NEVER recomputes (no codegraph)
        self.assertIn("call_path", text)
        self.assertIn("NEVER", text)
        self.assertIn("重算", text)


class TestAugmentationContract(unittest.TestCase):
    def test_call_path_field_documented(self):
        self.assertTrue(AUG_CONTRACT.is_file(), f"{AUG_CONTRACT} missing")
        text = AUG_CONTRACT.read_text(encoding="utf-8")
        # optional draft field; render-time advisory; absence (codegraph=off) valid
        self.assertIn("call_path", text)
        self.assertIn("advisory", text)
        self.assertIn("codegraph=off", text)
        # manifest counts + 5th boundary, existing 4 intact
        self.assertIn("call_path_confirmed", text)
        self.assertIn("call_path_residual", text)
        self.assertIn("全确认", text)  # the "do not claim 全确认" boundary


class TestAgentDefParity(unittest.TestCase):
    def test_both_augment_defs_carry_call_path_constraints(self):
        for f in (CLAUDE_AUGMENT_AGENT, OPENCODE_AUGMENT_AGENT):
            self.assertTrue(f.is_file(), f"{f} missing")
            text = f.read_text(encoding="utf-8")
            self.assertIn("codegraph=on", text)
            self.assertIn("codegraph_explore", text)   # MCP primary
            self.assertIn("codegraph explore", text)    # CLI fallback
            self.assertIn("call_path", text)            # advisory field
            self.assertIn("confirmed", text)            # not fabricated
            self.assertIn("advisory", text)
            self.assertIn("py -c", text)                # NEVER Write .py / py -c
            self.assertIn("draft_path", text)           # verbatim absolute path

    def test_both_clarify_defs_carry_advisory_callers(self):
        for f in (CLAUDE_CLARIFY_AGENT, OPENCODE_CLARIFY_AGENT):
            self.assertTrue(f.is_file(), f"{f} missing")
            text = f.read_text(encoding="utf-8")
            self.assertIn("codegraph=on", text)
            self.assertIn("减问", text)
            self.assertIn("MUST NOT", text)

    def test_both_consistency_defs_carry_pass_through(self):
        for f in (CLAUDE_CONSISTENCY_AGENT, OPENCODE_CONSISTENCY_AGENT):
            self.assertTrue(f.is_file(), f"{f} missing")
            text = f.read_text(encoding="utf-8")
            self.assertIn("call_path", text)
            self.assertIn("NEVER", text)
            self.assertIn("重算", text)

    def test_claude_augment_frontmatter_preserved(self):
        text = CLAUDE_AUGMENT_AGENT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: sra-augment", text)
        self.assertIn("Bash", text)   # CLI codegraph explore fallback needs Bash

    def test_opencode_augment_yaml_frontmatter(self):
        text = OPENCODE_AUGMENT_AGENT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "opencode agent must start with YAML frontmatter")
        self.assertIn("mode: subagent", text)
        self.assertIn("bash: allow", text)


class TestHintFragmentParity(unittest.TestCase):
    """Cross-change fragment parity (D8): the codegraph-hint fragment is co-owned
    by the sibling init change. It MUST exist and be the same prescriptive fragment
    (no SRA-specific content), so apply order does not matter."""

    def test_fragment_exists_and_is_prescriptive(self):
        self.assertTrue(HINT_FRAGMENT.is_file(), f"{HINT_FRAGMENT} missing")
        text = HINT_FRAGMENT.read_text(encoding="utf-8")
        # prescriptive steering (SHALL prefer), not permissive ("you may")
        self.assertIn("SHALL", text)
        self.assertIn("codegraph=on", text)
        self.assertIn("codegraph=off", text)
        # Read fallback triggers (the four codegraph-uncovered cases)
        self.assertIn("--big-file-bytes", text)
        self.assertIn("pending", text)
        self.assertIn("codegraph_explore", text)
        self.assertIn("codegraph explore", text)

    def test_fragment_has_no_sra_specific_content(self):
        # the fragment is generic steering; SRA call_path semantics live in the
        # sra-augment stanza, NOT here (D8). call_path must not leak into it.
        text = HINT_FRAGMENT.read_text(encoding="utf-8")
        self.assertNotIn("call_path", text)
        self.assertNotIn("sra-augment", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
