#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Static shape anchors for the mgh-init scout native-dispatch face
(fix-mgh-init-native-scout-dispatch). These are deliberately BEHAVIOR-ANCHOR
tests: every load-bearing sentence / field / wiring of the new face is pinned
by an assertIn over the real shipped file, so deleting or softening any one of
them turns CI red:

  - the wave-discipline fragment carries watchdog-first, page loop
    (units_total == 0), same-message wave dispatch, token-line task bodies +
    legacy fallback, marker truth source (subagents are the ONLY writers),
    at-most-one retry round, rate-limit window wait, honest boundaries;
  - the native twin agent's frontmatter mirrors init-scout's permission block
    and pins `doom_loop: deny` (mode: subagent, not hidden);
  - the three command faces disclose their dispatch-form divergence (opencode
    native default pointer; claude/dsh subprocess-only lines);
  - the contracts name the native step shape / dispatch field /
    scout.dispatch optional field / the init consumer in the resolver table;
  - the scripts + assets wiring: env_profile consumer=init + surface gate,
    list_steps/resume_state consume consumer="init", install.sh self-check
    lists the twin agent + fragment.

Run: py tests/test_init_native_dispatch.py
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRAGMENT = ROOT / "core" / "prompts" / "fragments" / "init-scout-native-dispatch.md"
TWIN = ROOT / "releases" / "opencode" / "agent" / "init-scout-native.md"
SCOUT_STAGE = ROOT / "core" / "prompts" / "fragments" / "init-stage" / "scout.md"
SHELL_OC = ROOT / "releases" / "opencode" / "command" / "mgh-init.md"
SHELL_CLAUDE = ROOT / "releases" / "claude-code" / "commands" / "mgh-init.md"
SHELL_DSH = ROOT / "releases" / "dsh" / "skills" / "mgh-init" / "SKILL.md"
CONTRACT_STEP = ROOT / "core" / "contracts" / "init" / "step-manifest.md"
CONTRACT_RESUME = ROOT / "core" / "contracts" / "init" / "resume-state.md"
CONTRACT_MANIFEST = ROOT / "core" / "contracts" / "init" / "manifest.md"
CONTRACT_FANOUT = ROOT / "core" / "contracts" / "fanout" / "runtime.md"
ENV_PROFILE = ROOT / "core" / "scripts" / "env_profile.py"
LIST_STEPS = ROOT / "core" / "scripts" / "list_steps.py"
RESUME_STATE = ROOT / "core" / "scripts" / "resume_state.py"
DISCIPLINE = ROOT / "core" / "scripts" / "discipline_core.py"
INSTALL_SH = ROOT / "install.sh"
SCOUT_TASK = ROOT / "core" / "prompts" / "fragments" / "fanout" / "scout-task.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class FragmentWaveDisciplineAnchors(unittest.TestCase):
    """The orchestrator wave-discipline fragment carries every load-bearing
    rule; the sdr fragment's rule set is mirrored per-rule, adapted to the
    init scout page loop."""

    def setUp(self):
        self.t = _read(FRAGMENT)

    def test_watchdog_first_with_run_dir_init(self):
        for needle in ("看门狗先行", "native_watchdog.py", "--run-dir",
                       "Start-Process", "OPENCODE_SESSION_ID", "自退"):
            self.assertIn(needle, self.t, needle)

    def test_materialize_and_check_with_scout_flags(self):
        for needle in ("emit_native_plan.py", "--tier scout", "--scout-plan",
                       "--checkpoints", "--inputs-dir", "--profile", "--check",
                       "重物化即修复"):
            self.assertIn(needle, self.t, needle)

    def test_page_loop_terminates_on_units_total_zero(self):
        for needle in ("units_total", "页语义", "重物化即重枚举", "当前页",
                       "NEVER", "手工翻"):
            self.assertIn(needle, self.t, needle)

    def test_same_message_wave_dispatch_with_token_line(self):
        for needle in ("同一条 assistant 消息", "init-scout-native",
                       "mgh-dispatch: plan=", "unit=<短号>", "逐字",
                       "mgh_dispatch.ts", "令牌展开钩子"):
            self.assertIn(needle, self.t, needle)

    def test_legacy_fallback_without_expansion_hook(self):
        self.assertIn("回退", self.t)
        self.assertIn("task_file", self.t)
        self.assertIn("绝对路径", self.t)

    def test_marker_truth_source_sole_writer(self):
        for needle in ("唯一写者是子代理自身", "NEVER", "unit_id", "reason",
                       "reference only; the dispatcher writes it"):
            self.assertIn(needle, self.t, needle)

    def test_at_most_one_retry_round(self):
        for needle in ("至多重派", "一轮", "--retry-failed", "接受缺口",
                       "NEVER", "无限重派"):
            self.assertIn(needle, self.t, needle)

    def test_rate_limit_window_wait(self):
        for needle in ("限流", "429", "quota", "等满", "窗口"):
            self.assertIn(needle, self.t, needle)

    def test_merge_transition_and_honest_boundaries(self):
        for needle in ("scout-merge", "fold-in", "诚实边界", "波次粒度",
                       "父会话是单点", "错抄"):
            self.assertIn(needle, self.t, needle)

    def test_scope_disclosure_scout_layer_only(self):
        # the fragment must say the native form covers ONLY the scout reader
        # batches — scout-merge/audit/fold-in stay subprocess.
        self.assertIn("只覆盖 scout", self.t)

    def test_runner_and_other_faces_out_of_scope(self):
        for needle in ("dispatch_mode:\"runner\"", "claude/dsh"):
            self.assertIn(needle, self.t, needle)


class NativeTwinAgentAnchors(unittest.TestCase):
    """init-scout-native.md: subagent-mode twin, permission mirror of
    init-scout + doom_loop deny, same stage prompt, marker self-write."""

    def setUp(self):
        self.t = _read(TWIN)
        fm = self.t.split("---")[1]
        self.fm = fm

    def test_mode_subagent_not_hidden(self):
        self.assertIn("mode: subagent", self.fm)
        self.assertNotIn("mode: primary", self.fm)
        self.assertNotIn("hidden: true", self.fm)

    def test_permission_block_mirrors_init_scout(self):
        init_scout = _read(ROOT / "releases" / "opencode" / "agent"
                           / "init-scout.md")
        base = init_scout.split("---")[1]
        for line in base.splitlines():
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key = line.split(":")[0].strip()
                if key in ("description",):
                    continue
                self.assertIn(line, [ln.strip() for ln in self.fm.splitlines()],
                              f"permission drift: {line!r} missing from twin")

    def test_doom_loop_deny_pinned(self):
        self.assertIn("doom_loop: deny", self.fm)

    def test_same_stage_prompt_reference(self):
        self.assertIn("prompts/stages/init-scout.md", self.t)
        self.assertIn("READ it", self.t)

    def test_terminal_marker_self_write_contract(self):
        for needle in ("touch `done_marker`", "自写 `failed_marker`",
                       "unit_id", "reason", "唯一", "终态"):
            self.assertIn(needle, self.t, needle)

    def test_bounded_ack_lines_match_stage_forms(self):
        # ack forms stay the stage-defined subset (ok/failed; the stage defines
        # no oversize form for scout batches — they are byte-bounded at plan
        # time, and the clone contract test enforces the subset).
        self.assertIn("`ok <绝对输出路径> <count>`", self.t)
        self.assertIn("`failed <原因>`", self.t)
        self.assertNotIn("`oversize", self.t)

    def test_failed_marker_body_is_self_written_not_dispatchers(self):
        # the twin must explicitly say the shared template's reference-only
        # line describes the SUBPROCESS form, not this one.
        self.assertIn("reference only", self.t)
        self.assertIn("子进程形态", self.t)


class ThreeFaceDisclosureAnchors(unittest.TestCase):
    """opencode shell carries the native main path + only-scout disclosure;
    claude/dsh shells carry the subprocess-only divergence line."""

    def test_opencode_shell_native_pointer(self):
        t = _read(SHELL_OC)
        for needle in ("dispatch", "consumer=init", "缺省原生",
                       "init-scout-native-dispatch.md", "emit_native_plan",
                       "仅 scout 读者批原生", "T1/T2/T3/scout-merge",
                       "\"dispatch_mode\":\"runner\"", "claude/dsh"):
            self.assertIn(needle, t, needle)

    def test_opencode_shell_subagent_inventory_names_the_twin(self):
        # the shell's inventory names every agent it can spawn (install.sh's
        # completeness check greps these tokens) — the twin must be named.
        t = _read(SHELL_OC)
        self.assertIn("`init-scout-native`", t)

    def test_claude_shell_subprocess_only_disclosure(self):
        t = _read(SHELL_CLAUDE)
        self.assertIn("仅子进程形态", t)
        self.assertIn("opencode", t)
        self.assertIn("非镜像断裂", t)

    def test_dsh_shell_subprocess_only_disclosure(self):
        t = _read(SHELL_DSH)
        self.assertIn("仅子进程形态", t)
        self.assertIn("opencode", t)
        self.assertIn("非镜像断裂", t)

    def test_scout_stage_fragment_conditional_pointer(self):
        t = _read(SCOUT_STAGE)
        for needle in ("--consumer init", "form=native", "缺省原生",
                       "init-scout-native-dispatch.md", "units_total==0",
                       "dispatch_mode:\"runner\"", "claude/dsh"):
            self.assertIn(needle, t, needle)


class ContractAnchors(unittest.TestCase):
    """Contracts name the native shapes so implementation and documentation
    cannot drift apart silently."""

    def test_step_manifest_native_step_shape(self):
        t = _read(CONTRACT_STEP)
        for needle in ("scout 原生步形", "emit_native_plan.py", "--tier scout",
                       "native_arc", "materialize", "waves", "merge",
                       "init-scout-native", "页语义", "units_total",
                       "scout-merge", "plan_present"):
            self.assertIn(needle, t, needle)

    def test_resume_state_contract_dispatch_field(self):
        t = _read(CONTRACT_RESUME)
        for needle in ("\"dispatch\"", "consumer=\"init\"", "init-scout-native",
                       "init-scout-native-dispatch.md", "plan_present",
                       "host-default", "native_plan.json", "mgh-dispatch: plan=",
                       "native 仅 opencode" if False else "原生仅 opencode"):
            self.assertIn(needle, t, needle)

    def test_manifest_contract_optional_scout_dispatch(self):
        t = _read(CONTRACT_MANIFEST)
        for needle in ("scout.dispatch", "\"form\": \"native\"",
                       "init-scout-native", "plan_path", "plan_present",
                       "字段缺席 = 子进程"):
            self.assertIn(needle, t, needle)

    def test_fanout_runtime_contract_second_consumer(self):
        t = _read(CONTRACT_FANOUT)
        for needle in ("第二个消费方", "scout 读者批", "consumer=init",
                       "{sdr, init}", "--consumer <sdr|init|generic>", "页语义",
                       "init-scout-native", "init-scout-native-dispatch"):
            self.assertIn(needle, t, needle)


class ScriptWiringAnchors(unittest.TestCase):
    """The resolver / step / resume scripts + install self-check carry the
    init consumer wiring; the shared template stays zero-changed."""

    def test_env_profile_init_consumer_and_surface_gate(self):
        t = _read(ENV_PROFILE)
        for needle in ('CONSUMERS = ("sdr", "init", "generic")',
                       'NATIVE_DEFAULT_CONSUMERS = ("sdr", "init")',
                       'INIT_NATIVE_AGENT = "init-scout-native"',
                       '"init": (INIT_NATIVE_AGENT_REL, INIT_NATIVE_FRAGMENT_REL)',
                       "def missing_native_assets(mgh_core_root, surface",
                       "surface: str = DEFAULT_SURFACE"):
            self.assertIn(needle, t, needle)

    def test_list_steps_consumes_init_consumer(self):
        t = _read(LIST_STEPS)
        for needle in ('env_profile.resolve(target, consumer="init")',
                       'surface="init"', "native_plan.json",
                       "_native_scout_step", "only on the opencode face"):
            self.assertIn(needle, t, needle)

    def test_resume_state_consumes_init_consumer(self):
        t = _read(RESUME_STATE)
        for needle in ('env_profile.resolve(target, consumer="init")',
                       'surface="init"', "native_plan.json",
                       "only on the opencode face", "AT MOST ONE more"):
            self.assertIn(needle, t, needle)

    def test_discipline_core_has_init_native_scout_table(self):
        t = _read(DISCIPLINE)
        for needle in ('_DISCIPLINE_INIT_NATIVE_SCOUT', 'domain="init"',
                       'form="native"', '"init-native-wave"',
                       '"init-native-marker"', '"init-native-retry"',
                       '"init-native-watchdog"', "units_total==0"):
            self.assertIn(needle, t, needle)

    def test_install_sh_self_check_lists_init_native_assets(self):
        t = _read(INSTALL_SH)
        self.assertIn("init-scout-native", t)
        self.assertIn("init-scout-native-dispatch.md", t)

    def test_shared_scout_task_template_zero_changed(self):
        # the subprocess template keeps its reference-only failed-marker line
        # byte-for-byte — the native form's self-write lives ONLY in the twin.
        t = _read(SCOUT_TASK)
        self.assertIn("reference only; the dispatcher writes it", t)
        self.assertNotIn("init-scout-native", t)


if __name__ == "__main__":
    unittest.main(verbosity=2)
