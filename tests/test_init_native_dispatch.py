#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Static shape anchors for the mgh-init native-dispatch faces
(fix-mgh-init-native-scout-dispatch + the aggregate-layer extension
fix-mgh-init-native-aggregate-dispatch). These are deliberately
BEHAVIOR-ANCHOR tests: every load-bearing sentence / field / wiring of the
faces is pinned by an assertIn over the real shipped file, so deleting or
softening any one of them turns CI red:

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
AGG_FRAGMENT = (ROOT / "core" / "prompts" / "fragments"
                / "init-aggregate-native-dispatch.md")
AGG_TWINS = {
    "init-induct-native": "init-induct-fanout",
    "init-synthesis-native": "init-synthesis-fanout",
    "init-scout-merge-native": "init-scout-merge-fanout",
    "init-rulewriter-native": "init-rulewriter-fanout",
}
EMIT_NATIVE_PLAN = ROOT / "core" / "scripts" / "emit_native_plan.py"
T1_STAGE = ROOT / "core" / "prompts" / "fragments" / "init-stage" / "t1.md"
T2_STAGE = ROOT / "core" / "prompts" / "fragments" / "init-stage" / "t2.md"
T3_STAGE = ROOT / "core" / "prompts" / "fragments" / "init-stage" / "t3.md"
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
                       "init-scout-native-dispatch.md",
                       "init-aggregate-native-dispatch.md", "emit_native_plan",
                       "t1/t2/t3/scout-merge 四个聚合层的 map 派发段",
                       "mgh_dispatch", "native_plan_<tier>.json",
                       "\"dispatch_mode\":\"runner\"", "claude/dsh",
                       "init-induct-native", "init-synthesis-native",
                       "init-scout-merge-native", "init-rulewriter-native"):
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
                       'INIT_NATIVE_AGENTS = (INIT_NATIVE_AGENT, "init-induct-native",',
                       'INIT_AGGREGATE_FRAGMENT_REL',
                       '"init": INIT_NATIVE_AGENT_RELS + (INIT_NATIVE_FRAGMENT_REL,',
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
        self.assertIn("init-aggregate-native-dispatch.md", t)
        for twin in AGG_TWINS:
            self.assertIn(twin, t, twin)

    def test_shared_scout_task_template_shape_anchors(self):
        # the subprocess template keeps its reference-only failed-marker line
        # byte-for-byte — the native form's self-write lives ONLY in the twin.
        t = _read(SCOUT_TASK)
        self.assertIn("reference only; the dispatcher writes it", t)
        self.assertNotIn("init-scout-native", t)

class AggregateFragmentAnchors(unittest.TestCase):
    """The aggregate-layer discipline fragment carries every load-bearing rule
    of the t1/t2/t3/scout-merge native map stages (channel B default, channel
    A fallback, per-layer invariants, page loop, retry, marker truth)."""

    def setUp(self):
        self.t = _read(AGG_FRAGMENT)

    def test_scope_and_prerequisites(self):
        for needle in ("consumer=init", "四个聚合层的 map 派发段", "t1", "t2",
                       "scout-merge", "t3", "needs_reduce", "rollup",
                       "fold-in", 'dispatch_mode:"runner"', "claude/dsh",
                       "不原生化"):
            self.assertIn(needle, self.t, needle)

    def test_watchdog_shared_with_scout_layer(self):
        for needle in ("看门狗先行", "native_watchdog.py", "--run-dir",
                       "Start-Process", "同一看门狗", "自退", "NEVER"):
            self.assertIn(needle, self.t, needle)

    def test_per_layer_materialization_lines_and_plan_names(self):
        for needle in ("emit_native_plan.py", "--tier t1", "--clusters",
                       "--candidates", "--tier t2", "--budget",
                       "--tier scout-merge", "--tier t3", "--inventory",
                       "--rules-dir", "--check", "重物化即修复",
                       "native_plan_t1.json", "native_plan_t2.json",
                       "native_plan_t3.json", "native_plan_scout-merge.json",
                       "--pack-bytes", "--pack-max"):
            self.assertIn(needle, self.t, needle)

    def test_channel_b_default_call_form(self):
        for needle in ("通道 B(默认)", "mgh_dispatch", "plan", "本页全部波次",
                       "零 LLM 波次回合", "NEVER", "自建波次循环", "闭集"):
            self.assertIn(needle, self.t, needle)

    def test_channel_a_fallback_disclosed(self):
        for needle in ("通道 A(回退,工具缺席时)", "同一条 assistant 消息",
                       "init-induct-native", "mgh-dispatch: plan=",
                       "task_file", "绝对路径", "NEVER",
                       "静默换子进程形态", "回退事实"):
            self.assertIn(needle, self.t, needle)

    def test_per_layer_invariants(self):
        for needle in ("pack 打包摊薄透传", "成员级 `.done`",
                       "scout 完成闸门", "validate_t1_records",
                       "零派发", "不产计划、不建会话", "manifest 文件先行",
                       "summary_paths", "不 rollup", "瘦身投影",
                       "正向 marker 路径计算", "assemble_rules.py --check",
                       "唯一带写权限"):
            self.assertIn(needle, self.t, needle)

    def test_retry_and_rate_limit_and_marker_truth(self):
        for needle in ("至多重派", "一轮", "--retry-failed", "接受缺口",
                       "限流", "429", "quota", "等满", "窗口",
                       "唯一写者是子代理自身", "unit_id", "reason",
                       "reference only; the dispatcher writes it"):
            self.assertIn(needle, self.t, needle)

    def test_honest_boundaries(self):
        for needle in ("诚实边界", "波次粒度", "父会话是单点", "页", "错抄"):
            self.assertIn(needle, self.t, needle)


class AggregateTwinAnchors(unittest.TestCase):
    """The four aggregate-layer native twins: subagent-mode twins, permission
    mirrors of their subprocess twins (rulewriter is the ONLY one with write
    permission), marker self-write, bounded acks."""

    def _fm(self, name):
        text = _read(ROOT / "releases" / "opencode" / "agent" / f"{name}.md")
        return text, text.split("---")[1]

    def test_mode_subagent_not_hidden_not_primary(self):
        for twin in AGG_TWINS:
            _, fm = self._fm(twin)
            self.assertIn("mode: subagent", fm, twin)
            self.assertNotIn("mode: primary", fm, twin)
            self.assertNotIn("hidden: true", fm, twin)

    def test_permission_mirrors_subprocess_twin(self):
        for twin, base_name in AGG_TWINS.items():
            _, base_fm = self._fm(base_name)
            _, twin_fm = self._fm(twin)
            for line in base_fm.splitlines():
                line = line.strip()
                if ":" in line and not line.startswith("#") \
                        and line.split(":")[0].strip() in (
                            "read", "glob", "grep", "list", "bash", "edit",
                            "question", "external_directory"):
                    self.assertIn(line, [ln.strip() for ln in twin_fm.splitlines()],
                                  f"{twin}: permission drift: {line!r}")

    def test_rulewriter_is_the_only_write_twin(self):
        for twin in AGG_TWINS:
            _, fm = self._fm(twin)
            if twin == "init-rulewriter-native":
                self.assertIn("edit: allow", fm)
            else:
                self.assertIn("edit: deny", fm, twin)
            self.assertIn("doom_loop: deny", fm, twin)

    def test_same_stage_prompt_reference_and_token_form_note(self):
        stage = {"init-induct-native": "init-induct.md",
                 "init-synthesis-native": "init-synthesis-partial.md",
                 "init-scout-merge-native": "init-scout-merge-partial.md",
                 "init-rulewriter-native": "init-rulewriter.md"}
        for twin, prompt in stage.items():
            text = self._fm(twin)[0]
            self.assertIn(f"prompts/stages/{prompt}", text, twin)
            self.assertIn("READ it", text, twin)
            self.assertIn("emit_native_plan.py", text, twin)
            self.assertIn("token-expansion hook", text, twin)

    def test_terminal_marker_self_write_contract(self):
        for twin in AGG_TWINS:
            text = self._fm(twin)[0]
            for needle in ("touch `done_marker`", "自写 `failed_marker`",
                           "unit_id", "reason", "唯一", "终态",
                           "reference only", "子进程形态", "crash ≠ 确认失败"):
                self.assertIn(needle, text, f"{twin}: {needle}")

    def test_bounded_ack_forms_match_stage_forms(self):
        acks = {"init-induct-native": ("`ok <绝对输出路径> <count>`",),
                "init-synthesis-native": ("`ok <绝对 checkpoint_path> <controls数>`",
                                          "`oversize <绝对 checkpoint_path>`"),
                "init-scout-merge-native": ("`ok <绝对 checkpoint_path> <候选数>`",),
                "init-rulewriter-native": ("`ok <绝对输出路径> <count>`",)}
        for twin, forms in acks.items():
            text = self._fm(twin)[0]
            self.assertIn("`failed <原因>`", text, twin)
            for form in forms:
                self.assertIn(form, text, f"{twin}: {form}")
            if not any("oversize" in form for form in forms):
                self.assertNotIn("`oversize", text, twin)

    def test_path_verbatim_and_never_constraints(self):
        for twin in AGG_TWINS:
            text = self._fm(twin)[0]
            for needle in ("NEVER", "绝对路径", "相对路径", "盘符根", "越树读"):
                self.assertIn(needle, text, f"{twin}: {needle}")
            if twin != "init-rulewriter-native":
                self.assertIn("输出路径逐字", text, twin)

    def test_rulewriter_write_face_constraint(self):
        text = self._fm("init-rulewriter-native")[0]
        for needle in ("唯一带写权限", "写面只开规则产物", "越树写会被运行域守卫拦",
                       "NEVER 直写 `AGENTS.md`", "rules-format-claude.md",
                       "rules-format-opencode.md", "Rule-body purity"):
            self.assertIn(needle, text, needle)


class AggregateStageFragmentAnchors(unittest.TestCase):
    """t1/t2/t3 stage fragments carry the conditional native pointer
    (gate/zero-dispatch/plan-name discipline per layer)."""

    def test_t1_stage_native_pointer(self):
        t = _read(T1_STAGE)
        for needle in ("--consumer init", "form=native", "缺省原生",
                       "init-aggregate-native-dispatch.md", "--tier t1",
                       "native_plan_t1.json", "通道 B", "通道 A",
                       "--pack-bytes", "4b", 'dispatch_mode:"runner"',
                       "claude/dsh"):
            self.assertIn(needle, t, needle)

    def test_t2_stage_native_pointer_zero_dispatch(self):
        t = _read(T2_STAGE)
        for needle in ("init-aggregate-native-dispatch.md", "(a) 段",
                       "needs_reduce=false", "零派发不变", "不产计划",
                       "single-context `init-synthesis`", "native_plan_t2.json",
                       "summary_paths"):
            self.assertIn(needle, t, needle)

    def test_t3_stage_native_pointer(self):
        t = _read(T3_STAGE)
        for needle in ("init-aggregate-native-dispatch.md", "native_plan_t3.json",
                       "init-rulewriter-native", "唯一带写权限",
                       "正向判定 / 孤儿审计", "assemble_rules"):
            self.assertIn(needle, t, needle)

    def test_scout_stage_merge_segment_points_at_aggregate(self):
        t = _read(SCOUT_STAGE)
        for needle in ("map 分片段同形态下走原生",
                       "init-aggregate-native-dispatch.md",
                       "native_plan_scout-merge.json", "rollup / audit / fold-in 不变"):
            self.assertIn(needle, t, needle)


class AggregateContractAnchors(unittest.TestCase):
    """Contracts name the aggregate native shapes so implementation and
    documentation cannot drift apart silently."""

    def test_step_manifest_aggregate_step_shapes(self):
        t = _read(CONTRACT_STEP)
        for needle in ("聚合层原生步形", "native_plan_t1.json",
                       "native_plan_t2.json", "native_plan_t3.json",
                       "native_plan_scout-merge.json", "mgh_dispatch",
                       "aggregate_agents", "aggregate_plan_present",
                       "init-induct-native", "init-synthesis-native",
                       "init-rulewriter-native", "零派发", "通道 B", "通道 A",
                       "pack"):
            self.assertIn(needle, t, needle)

    def test_resume_state_contract_aggregate_arc(self):
        t = _read(CONTRACT_RESUME)
        for needle in ("聚合层(t1/t2/t3)原生 next_action", "aggregate_fragment",
                       "aggregate_plan_present", "通道 B(默认)",
                       "零派发", "闸门先行", "AT MOST ONE more"):
            self.assertIn(needle, t, needle)

    def test_manifest_contract_aggregate_dispatch(self):
        t = _read(CONTRACT_MANIFEST)
        for needle in ("aggregate_dispatch", "channel", "tool|waves",
                       "zero_dispatch", "fallback_events", "NEVER",
                       "未发生的通道"):
            self.assertIn(needle, t, needle)

    def test_fanout_runtime_contract_aggregate_consumers(self):
        t = _read(CONTRACT_FANOUT)
        for needle in ("四个聚合层(t1/t2/t3/scout-merge)", "init-aggregate-native-dispatch",
                       "init-induct-native", "init-rulewriter-native",
                       "原生 subagent 孪生名", "native_plan_<tier>.json",
                       "零派发不变量", "--pack-bytes"):
            self.assertIn(needle, t, needle)


class AggregateScriptWiringAnchors(unittest.TestCase):
    """emit_native_plan carries the per-tier plan naming, the native-twin
    agent mapping, the t1 pack passthrough, and the zero-dispatch guard;
    discipline_core carries the t1/t2/t3 native variants; the shared task
    templates stay zero-changed."""

    def test_emit_native_plan_per_tier_names_and_agent_mapping(self):
        t = _read(EMIT_NATIVE_PLAN)
        for needle in ('AGGREGATE_TIERS = ("t1", "t2", "t3", "scout-merge")',
                       'NATIVE_AGENTS = {',
                       '"t1": "init-induct-native"',
                       '"t2": "init-synthesis-native"',
                       '"scout-merge": "init-scout-merge-native"',
                       '"t3": "init-rulewriter-native"',
                       '"scout": "init-scout-native"',
                       '"sdr": "sdr-review-native"',
                       "def plan_filename(tier_id: str) -> str:",
                       'return f"native_plan_{tier_id}.json"'):
            self.assertIn(needle, t, needle)

    def test_emit_native_plan_zero_dispatch_guard(self):
        t = _read(EMIT_NATIVE_PLAN)
        for needle in ('args.tier in ("t2", "scout-merge")',
                       "no plan artifact is", "Zero-dispatch invariant"):
            self.assertIn(needle, t, needle)

    def test_emit_native_plan_pack_passthrough(self):
        t = _read(EMIT_NATIVE_PLAN)
        for needle in ("--pack-bytes", "--pack-max", "t1-only", "list_args"):
            self.assertIn(needle, t, needle)

    def test_discipline_core_has_aggregate_native_tables(self):
        t = _read(DISCIPLINE)
        for needle in ("_DISCIPLINE_INIT_NATIVE_T1", "_DISCIPLINE_INIT_NATIVE_T2",
                       "_DISCIPLINE_INIT_NATIVE_T3", "_init_agg_native_wave_recipe",
                       "mgh_dispatch", "通道 A", "native_plan_t1.json",
                       'step == "t1" and form == "native"',
                       'step == "t2" and form == "native"',
                       'step == "t3" and form == "native"',
                       "init-aggregate-native-dispatch"):
            self.assertIn(needle, t, needle)

    def test_shared_aggregate_task_templates_shape_anchors(self):
        for name in ("t1", "t2", "t3", "scout-merge"):
            t = _read(ROOT / "core" / "prompts" / "fragments" / "fanout"
                      / f"{name}-task.md")
            self.assertIn("reference only; the dispatcher writes it", t, name)
            for twin in AGG_TWINS:
                self.assertNotIn(twin, t, f"{name}: {twin}")


class TaskTemplateValidationAnchors(unittest.TestCase):
    """All five tier task templates carry the sanctioned read-only JSON syntax
    validation channel (`py -m json.tool`) + the failure disposition (unit
    failure, NEVER touch .done, NEVER rewrite to pass); t1-task additionally
    carries the pack-ledger prohibition and the record_missing re-induce
    exception. Deleting any pinned line turns these red."""

    def test_all_five_templates_carry_validation_channel(self):
        for name in ("scout", "t1", "t2", "t3", "scout-merge"):
            t = _read(ROOT / "core" / "prompts" / "fragments" / "fanout"
                      / f"{name}-task.md")
            self.assertIn("py -m json.tool", t, name)      # the channel
            self.assertIn("check pass", t, name)           # disposition clause
            self.assertIn("NEVER touch", t, name)
            self.assertIn("NEVER rewrite", t, name)

    def test_json_record_templates_validate_the_checkpoint(self):
        # the four JSON-record templates point the check at the checkpoint
        # placeholder; t3's product is markdown (its line scopes to JSON
        # records only — no checkpoint placeholder exists there)
        for name in ("scout", "t1", "t2", "scout-merge"):
            t = _read(ROOT / "core" / "prompts" / "fragments" / "fanout"
                      / f"{name}-task.md")
            self.assertIn("validate its JSON syntax READ-ONLY", t, name)
            self.assertIn("<checkpoint_path>", t, name)

    def test_t1_task_pack_ledger_prohibition(self):
        t = _read(ROOT / "core" / "prompts" / "fragments" / "fanout"
                  / "t1-task.md")
        self.assertIn("NEVER write any pack-level ledger/inventory/manifest file",
                      t)
        self.assertIn("pack_manifests", t)

    def test_t1_task_record_missing_reinduce_exception(self):
        # a pack member whose record was lost after its marker is re-induced,
        # not skipped (marker-without-record reconciliation)
        t = _read(ROOT / "core" / "prompts" / "fragments" / "fanout"
                  / "t1-task.md")
        self.assertIn("record_missing: true", t)
        self.assertIn("NOT skipped", t)


if __name__ == "__main__":

    unittest.main(verbosity=2)
