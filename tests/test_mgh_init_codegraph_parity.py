#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""improve-mgh-init-codegraph-enrichment claude<->opencode parity (R5.8).

Asserts both mgh-init.md shells agree on the codegraph-enrichment surface:
  --no-codegraph flag, codegraph-hint fragment reference, init-resolve stage
  declared optional/codegraph-gated/non-fatal/bounded, init-resolve in the
  Stage->component map, detection stanza, codegraph manifest block; and that the
  init-resolve stage prompt + both agent defs carry the required hard constraints
  (Sanctioned tools allowlist incl. codegraph MCP/CLI + Read fallback;
  checkpoint_path/done_marker verbatim; source:"codegraph"; NEVER Write .py / py -c).
  Run: py tests/test_mgh_init_codegraph_parity.py
"""
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLAUDE_SHELL = ROOT / "releases" / "claude-code" / "commands" / "mgh-init.md"
OPENCODE_SHELL = ROOT / "releases" / "opencode" / "command" / "mgh-init.md"
RESOLVE_PROMPT = ROOT / "core" / "prompts" / "stages" / "init-resolve.md"
HINT_FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "codegraph-hint.md"
CLAUDE_AGENT = ROOT / "releases" / "claude-code" / "agents" / "init-resolve.md"
OPENCODE_AGENT = ROOT / "releases" / "opencode" / "agent" / "init-resolve.md"


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

    def test_both_reference_hint_fragment(self):
        self._assert_both("codegraph-hint.md")

    def test_both_reference_init_resolve_prompt(self):
        self._assert_both("init-resolve.md")

    def test_both_declare_detection_stanza(self):
        self._assert_both("command -v codegraph")
        self._assert_both("codegraph=on|off")

    def test_both_declare_init_resolve_stage_semantics(self):
        # rigid triple + optional/codegraph-gated/non-fatal/bounded semantics
        self._assert_both("init-resolve")
        self._assert_both("codegraph-gated")
        self._assert_both("non-fatal")
        self._assert_both("describe_artifact.py --field")
        self._assert_both("resolved.json")

    def test_both_list_init_resolve_in_component_map(self):
        self._assert_both("resolve (opt)")

    def test_both_declare_codegraph_manifest_block(self):
        self._assert_both("resolved_count")
        self._assert_both("unresolved_residual")


class TestInitResolvePrompt(unittest.TestCase):
    def test_required_sections_present(self):
        self.assertTrue(RESOLVE_PROMPT.is_file(), f"{RESOLVE_PROMPT} missing")
        text = RESOLVE_PROMPT.read_text(encoding="utf-8")
        # Sanctioned-tools allowlist incl. codegraph MCP/CLI + Read fallback
        self.assertIn("Sanctioned tools", text)
        self.assertIn("codegraph_explore", text)
        self.assertIn("codegraph explore", text)
        # checkpoint_path / done_marker verbatim (never interpolated)
        self.assertIn("checkpoint_path", text)
        self.assertIn("done_marker", text)
        self.assertIn("NEVER", text)
        # output structural tag + resolved path
        self.assertIn("codegraph", text)
        self.assertIn("resolved_path", text)
        self.assertIn("unresolved_residual", text)
        # hard boundary: NEVER Write .py / py -c
        self.assertIn("py -c", text)

    def test_hint_fragment_is_prescriptive(self):
        self.assertTrue(HINT_FRAGMENT.is_file(), f"{HINT_FRAGMENT} missing")
        text = HINT_FRAGMENT.read_text(encoding="utf-8")
        # prescriptive steering (SHALL prefer), not permissive ("you may")
        self.assertIn("SHALL", text)
        self.assertIn("codegraph=on", text)
        self.assertIn("codegraph=off", text)
        # Read fallback triggers (the four codegraph-uncovered cases)
        self.assertIn("--big-file-bytes", text)
        self.assertIn("pending", text)


class TestInitResolveAgentDefs(unittest.TestCase):
    def test_both_agent_defs_carry_hard_constraints(self):
        for f in (CLAUDE_AGENT, OPENCODE_AGENT):
            self.assertTrue(f.is_file(), f"{f} missing")
            text = f.read_text(encoding="utf-8")
            self.assertIn("codegraph_explore", text)   # MCP primary
            self.assertIn("codegraph explore", text)    # CLI fallback
            self.assertIn("py -c", text)                # NEVER Write .py / py -c
            self.assertIn("checkpoint_path", text)      # verbatim absolute path
            self.assertIn("codegraph", text)            # source:"codegraph"
            self.assertIn("resolved_path", text)

    def test_claude_agent_frontmatter_and_tools(self):
        text = CLAUDE_AGENT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: init-resolve", text)
        # Bash is required so the CLI `codegraph explore` fallback is usable
        self.assertIn("Bash", text)

    def test_opencode_agent_yaml_frontmatter(self):
        text = OPENCODE_AGENT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"), "opencode agent must start with YAML frontmatter")
        self.assertIn("mode: subagent", text)
        self.assertIn("bash: allow", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
