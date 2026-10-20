#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sdr native-dispatch shape anchors (fix-mgh-sdr-native-dispatch task 4.3).

Static document anchors for the native-dispatch face: every load-bearing line
of the new opencode shell step, the wave-discipline fragment, the native agent
twin, the three-face divergence disclosures, and the two contracts. Deleting
any anchor turns this file red — that is the point: the native face is wired by
documents an orchestrator reads, so a silently dropped line is a silently
dropped defense. The dynamic faces (step manifest / resume derivation / report
disclosure) live in their own test files; here only the static shapes.

Run: py tests/test_sdr_native_dispatch.py
"""
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

OPENCODE_SHELL = ROOT / "releases" / "opencode" / "command" / "mgh-sdr.md"
CLAUDE_SHELL = ROOT / "releases" / "claude-code" / "commands" / "mgh-sdr.md"
DSH_SHELL = ROOT / "releases" / "dsh" / "skills" / "mgh-sdr" / "SKILL.md"
FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "sdr-native-dispatch.md"
NATIVE_AGENT = ROOT / "releases" / "opencode" / "agent" / "sdr-review-native.md"
FANOUT_AGENT = ROOT / "releases" / "opencode" / "agent" / "sdr-review-fanout.md"
SDR_TASK = ROOT / "core" / "prompts" / "fragments" / "fanout" / "sdr-task.md"
SDR_PIPELINE = ROOT / "core" / "contracts" / "sdr" / "pipeline.md"
FANOUT_RUNTIME = ROOT / "core" / "contracts" / "fanout" / "runtime.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _frontmatter(text: str) -> str:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, f"no frontmatter in {text[:40]!r}"
    return m.group(1)


def _output_schema_block(text: str) -> str:
    """The twin agent's Output schema paragraph — the clone-parity anchor runs
    byte-verbatim between the two agent definitions."""
    m = re.search(r'\{"unit": "<unit_id verbatim>".*?"control_ref\|null"\}\]\}', text, re.S)
    assert m, "Output schema block not found"
    return m.group(0)


class OpencodeShellAnchors(unittest.TestCase):
    def test_step0_profile_read_with_fail_closed_stop(self):
        t = _read(OPENCODE_SHELL)
        self.assertIn("env_profile.py", t)
        self.assertIn("dispatch_mode == \"native\"", t)
        self.assertIn("STOP", t)  # corrupt profile -> stop, never run past it
        self.assertIn("缺省零变化", t)

    def test_fanout_step_native_conditional(self):
        t = _read(OPENCODE_SHELL)
        self.assertIn("sdr-native-dispatch.md", t)
        self.assertIn("emit_native_plan.py", t)
        self.assertIn("sdr-review-native", t)
        self.assertIn("同一条 assistant 消息", t)
        self.assertIn("runner 子流程不适用", t)

    def test_three_face_divergence_disclosure_opencode_claim(self):
        t = _read(OPENCODE_SHELL)
        self.assertIn("派发形态支持面", t)
        self.assertIn('dispatch_mode:"native"', t)
        self.assertIn("claude/dsh", t)


class SiblingShellDisclosureAnchors(unittest.TestCase):
    def test_claude_shell_subprocess_only_claim(self):
        t = _read(CLAUDE_SHELL)
        self.assertIn("派发形态", t)
        self.assertIn("仅子进程形态", t)
        self.assertIn("仅 opencode 面支持", t)
        self.assertNotIn("sdr-native-dispatch.md", t)

    def test_dsh_shell_subprocess_only_claim(self):
        t = _read(DSH_SHELL)
        self.assertIn("派发形态", t)
        self.assertIn("仅子进程形态", t)
        self.assertIn("仅 opencode 面支持", t)
        self.assertNotIn("sdr-native-dispatch.md", t)


class FragmentAnchors(unittest.TestCase):
    def test_install_mirror_header_and_activation_premise(self):
        t = _read(FRAGMENT)
        self.assertIn("ORCHESTRATOR discipline fragment", t)
        self.assertIn("sdr-native-dispatch.md", t)  # install mirror path
        self.assertIn('dispatch_mode == "native"', t)
        self.assertIn("回到命令壳的子进程派发行", t)

    def test_watchdog_first_section(self):
        t = _read(FRAGMENT)
        self.assertIn("native_watchdog.py", t)
        self.assertIn("'--run-dir'", t)
        # the Windows-host launch is Start-Process (survives the tool call);
        # the bare POSIX `&` form is explicitly NEVER on PowerShell hosts
        self.assertIn("Start-Process", t)
        self.assertIn("-PassThru", t)
        self.assertIn("PowerShell", t)
        self.assertIn("OPENCODE_SESSION_ID", t)
        self.assertIn("自退", t)
        self.assertIn("NEVER", t)  # foreground / replacing the watchdog are NEVERs

    def test_wave_loop_recipe(self):
        t = _read(FRAGMENT)
        self.assertIn("emit_native_plan.py", t)
        self.assertIn("--check", t)
        self.assertIn("同一条 assistant 消息", t)
        self.assertIn("逐字", t)
        self.assertIn("重枚举", t)
        self.assertIn("NEVER", t)

    def test_marker_truth_source_and_retry_once(self):
        t = _read(FRAGMENT)
        self.assertIn("唯一写者", t)
        self.assertIn("至多重派", t)
        self.assertIn("--retry-failed", t)
        self.assertIn("接受缺口", t)
        self.assertIn("限流", t)
        self.assertIn("无限重派循环", t)


class NativeAgentTwinAnchors(unittest.TestCase):
    def test_frontmatter_subagent_not_hidden_permissions_mirror(self):
        native = _frontmatter(_read(NATIVE_AGENT))
        fanout = _frontmatter(_read(FANOUT_AGENT))
        self.assertIn("mode: subagent", native)
        self.assertNotIn("hidden:", native)
        # the permission block is cloned verbatim from the fanout twin
        def _perm(fm):
            m = re.search(r"permission:\n((?:  .*\n)+)", fm + "\n")
            assert m, "permission block not found"
            return m.group(1)
        self.assertEqual(_perm(native), _perm(fanout))

    def test_output_schema_block_byte_identical_to_fanout_twin(self):
        self.assertEqual(_output_schema_block(_read(NATIVE_AGENT)),
                         _output_schema_block(_read(FANOUT_AGENT)))

    def test_marker_self_write_and_ack_contract(self):
        t = _read(NATIVE_AGENT)
        self.assertIn("touch `done_marker`", t)
        self.assertIn("failed_marker", t)
        self.assertIn('"unit_id"', t)
        self.assertIn('"reason"', t)
        self.assertIn("`ok <draft_path> <n findings>`", t)
        self.assertIn("`oversize <draft_path>`", t)
        self.assertIn("`failed <原因>`", t)
        self.assertIn("只信磁盘标记", t)  # orchestrator trusts disk, not the ack

    def test_fanout_twin_writer_semantics_unchanged(self):
        # the twin pair diverges EXACTLY on the failed-marker writer: the fanout
        # twin keeps dispatcher-writes, the native twin self-writes
        fan = _read(FANOUT_AGENT)
        self.assertIn("dispatcher 据此写该单元 `.failed` marker", fan)
        self.assertNotIn("自写 `failed_marker`", fan)
        nat = _read(NATIVE_AGENT)
        self.assertIn("自写 `failed_marker`", nat)
        self.assertNotIn("dispatcher 据此写该单元", nat)

    def test_shared_task_template_writer_line_unchanged(self):
        # the double-face template keeps its subprocess writer comment untouched
        t = _read(SDR_TASK)
        self.assertIn("failed_marker (reference only; the dispatcher writes it on a "
                      "failed ack)", t)


class ContractAnchors(unittest.TestCase):
    def test_sdr_pipeline_native_section(self):
        t = _read(SDR_PIPELINE)
        self.assertIn("原生派发形态", t)
        for needle in ("dispatch_mode", "native_plan.json", "sdr-review-native",
                       "唯一写者", "至多重派一轮", "OPENCODE_SESSION_ID",
                       "三面分歧", "版本矩阵", "sdr-native-dispatch.md"):
            self.assertIn(needle, t, needle)

    def test_fanout_runtime_names_sdr_first_consumer(self):
        t = _read(FANOUT_RUNTIME)
        self.assertIn("首个消费方", t)
        self.assertIn("/mgh-sdr", t)
        self.assertIn("永久回退", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
