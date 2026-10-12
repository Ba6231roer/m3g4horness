# dsh-agent-surface Specification

## Purpose

规定 mgh 子代理资产(交互式 stage 定义与 fan-out tier 克隆)在 deepseek-harness(dsh)宿主
上的承载形态:定义文本的第三方言、tier 装载文件的生成与挂载语义、具名派发的对等合同,以及
宿主超时语义与长跑纪律的调平。

## Requirements

### Requirement: Agent definitions have a third-dialect source compiled to tier mounts

Each fan-out tier and each interactive stage agent SHALL have a dsh-dialect definition under
`releases/dsh/agents/`, mirroring the existing opencode `*-fanout` clones and sast stage agents
(the leaf SYSTEM prompt is shared by path reference, not copied). The installer SHALL compile
each definition into a per-tier mount artifact under `<target>/mgh-core/dsh/tiers/` that the
dispatcher can reference by tier id. Reinstall SHALL regenerate mounts idempotently. A missing
or stale mount for a tier the dispatcher is asked to run SHALL fail loud before any spawn.

#### Scenario: tier mount regeneration on reinstall
- **WHEN** 修改 scout 定义后重跑 `install.sh --dsh <target>`
- **THEN** `<target>/mgh-core/dsh/tiers/` 内 scout 装载文件更新,其余 tier 不重复堆积

#### Scenario: unknown tier fails before spawn
- **WHEN** dispatcher 被要求派发一个没有装载文件的 tier
- **THEN** 退出码 2 + stderr recipe,零子进程被 spawn

### Requirement: Leaf prompt and tool-whitelist mounting follows the spike-locked tier

The mount SHALL deliver the leaf's SYSTEM prompt and tool surface to the headless run by one of
two admitted shapes, locked by measured spike: (a) host-side composition — the tier mount
names the prompt content and restricts tools through the host's own agent/preset configuration;
or (b) task-prepended composition — the dispatcher's fixed template prepends the referenced
prompt file content to the stdin task (still zero-LLM-turn construction), with tool
confinement carried solely by the three-face guard plus host approval. Shape (b) SHALL only be
adopted if (a) is measured unavailable, and the choice SHALL be recorded in the fan-out runtime
contract so shells and tests agree on one form.

#### Scenario: single locked shape across a run
- **WHEN** 任一 tier 在 dsh 上派发
- **THEN** 装载形态恒为定案档位,同一次 run 内不混用;任务文本由固定模板逐字构造

### Requirement: Interactive stage delegation is by named tool instances

On dsh, the orchestrator's non-fan-out stage delegation (e.g. sast per-stage subagents) SHALL
be served by named delegation tool instances composed through the mgh profile/preset — one
per stage, tool-name addressing mirroring the claude side's pick-by-name model. Stage shells'
dsh dialect SHALL reference those names verbatim; the orchestrator SHALL NOT improvise
generic delegation without the declared instance.

#### Scenario: named stage tool drives per-stage isolation
- **WHEN** dsh 上运行 `/mgh-sast` 至需要某 stage 子代理
- **THEN** 编排器调用该 stage 对应的具名委派工具,子代理以自身提示词与工具面白名单运行

### Requirement: Host background-promotion timeout is levelled to the terminate-on-timeout contract

Long-run deterministic leaf discipline assumes a per-call shell timeout terminates the call
(R5.4 权威处). Where the dsh host's shell tool by default promotes a timed-out foreground
command to a background job instead, the tier composition SHALL disable that promotion so the
timeout contract matches claude/opencode; if the host cannot be configured, the dsh shell
dialect SHALL add the explicit `kill the promoted job` step to its long-run recipe and the fan-out
runtime contract records the divergence. Silent divergence (job alive after "timeout") SHALL NOT
be left open on any shipped path.

#### Scenario: timed-out discover run is actually terminated
- **WHEN** dsh 扇出单元内叶脚本 shell 调用超出配置超时
- **THEN** 该调用终止(或按定案方言其晋升 job 被显式回收),单元按既有 stall/重派语义处理,
  不留隐形活口
