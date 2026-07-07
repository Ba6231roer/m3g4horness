# Tasks — add-mgh-sast-design-controls

> 依赖顺序:契约锁 shape → intake 脚本(`load_controls.py` + `--check`)→ 双壳 flag + 注入 →
> fragment + 诚实边界 → 单测 + 契约 lint → 端到端。每条可独立验收。遵守 AGENTS.md R1–R5
> (零依赖、移植提示词正文不改、复用导入、R5.1 CLI lint、R5.8 回归、R5.10 分发纯净)。新脚本
> MUST 经 `tools/check_contracts.py` 断言其 `--help` 含双壳镜像的所有 flag。

## 1. 契约锁 shape(D2 / D3)

- [x] 1.1 `core/contracts/sast/controls-intake.md`:`load_controls.py` stdout shape
      (`controls_bundle = {source, inventory_path, total, in_scope_count, out_of_scope_count,
      in_scope[]}`)+ 每条 in-scope 控制摘要字段(`name/kind/protects/evidence/usage/gaps`)+
      `--check` 校验项。字段对齐 `core/contracts/init/inventory.md` 的 `Control` 元素 schema。
- [x] 1.2 该契约显式声明:控制走**任务消息**注入(非提示词正文)、注入 s2/s3/s4/s6/s8、投影为
      relevance hint(保留 out_of_scope 计数)。

## 2. intake + scope 投影脚本(D2 / D3)

- [x] 2.1 `core/scripts/load_controls.py`:`--inventory <p> --repo <r> [--in-scope <file>]`;
      intake 校验(wrapper + 每条 `name`/`kind`(6 枚举或别名归一)/`evidence` 锚点/`protects`
      fnmatch);scope 投影(每条标 `in_scope`);stdout `controls_bundle` JSON;stderr 诊断;
      退出码 `0/1/2`。自定位 `sys.path`、utf-8、零依赖、任意 cwd。
- [x] 2.2 `load_controls.py --check <inventory>`:well-formed + vvah `design_controls` 兼容字段
      + 每条 evidence 锚点 + kind 枚举/归一;失败退出码 2。MUST NOT `import validate_inventory`。
- [x] 2.3 `kind` 别名归一(`authn`/`authz`/`rbac`/`iam`/`sso`→`auth`;`waf`/`validation`/
      `sanitization`/`encoding`→`input-validation`;`seccomp`/`container`/`isolation`→`sandbox`)
      与 `inventory.md:45-48` 一致;归一表抽常量、可单测。

## 3. 双壳 flag + 注入点(D1 / D4)

- [x] 3.1 两份 `mgh-sast.md`(claude + opencode)flag 表增 `--controls <path>`(可选、advisory);
      `--help`/无参 flag 表同步;语义逐字镜像。
- [x] 3.2 两壳编排流:scope 解析后、s1 前,插 intake 步骤
      `[controls_inventory.json] → load_controls.py --check → load_controls.py --inventory .. --repo ..
      --in-scope .. → [stdout controls_bundle]`(失败退码 2 → 回退「无控制」advisory)。
- [x] 3.3 两壳 s2/s3/s4/s6/s8 subagent spawn 段:把 `controls_bundle` + inline
      `core/prompts/fragments/controls-context.md` 放进任务消息;**不**改 `stages/*.md` 正文。
- [x] 3.4 两壳:无 `--controls` 时跳过 intake,manifest 标 `controls.source="none"`。

## 4. fragment + 诚实边界(D6)

- [x] 4.1 `core/prompts/fragments/controls-context.md`(rewrite-original):subagent 如何消费
      `controls_bundle`(s2 降 likelihood / s3 chunk 排序 / s4 上游排除 / s6 中和型 FP / s8 chain
      阻断);**evidence-grounded** 中和判定(控制 evidence 须在数据流上游,否则只降权);
      诚实边界(存在≠有效,CVE-2025-41248);被控制下架的 finding 须单列。
- [x] 4.2 `run_manifest.json` 增 `controls` 段(`source`/`inventory_path`/`in_scope_count`/
      `out_of_scope_count`/`total`);`report.md` 头部边界增控制来源 + 「存在≠有效」+ scope 真实数字。

## 5. 单测 + 契约 lint(R5.1 / R5.8)

- [x] 5.1 `tests/test_load_controls.py`:intake 校验(正常退出 0、破损退出 2);scope 投影
      (in_scope 命中/全仓/under-filter 保留 out_of_scope);kind 别名归一;自定位/任意 cwd 子进程。
- [x] 5.2 `tools/check_contracts.py`:扩到 `load_controls.py` + `--controls` flag;断言双壳 MD 里
      每个 `*.py --flag` / `--controls` 在 `--help` 存在。
- [x] 5.3 `tools/check_distributed_purity.py`:覆盖新 fragment `controls-context.md` + 契约
      `controls-intake.md`(承 R5.10);零依赖 AST 扫描扩到 `load_controls.py`。

## 6. 端到端验证

- [x] 6.1 `py tests/`(含新测)绿;`tools/check_contracts.py` 0 违例;零依赖 AST 扫描无输出;
      `check_distributed_purity.py` 0 命中。
- [x] 6.2 合成仓:先 `/mgh-init --format claude` 产 inventory,再 `/mgh-sast --repo . --controls
      ./.mgh-init/controls_inventory.json`:s2/s6/s8 收到 `controls_bundle`,被控制下架的 finding
      单列;无 `--controls` 时行为同旧版本**(本机)**。
      > 兑现范围:`load_controls.py --check` + `--inventory/--repo/--in-scope` 在合成仓
      > (`/tmp/synth-svc`,schema 精确对齐 `inventory.md` 的 inventory)上确定性 intake + scope
      > 投影 e2e 验证通过(kind 归一、summary 字段、out_of_scope hint、破损退码 2 回退)。
      > **未执行**:agentic LLM 阶段(`/mgh-init` 实跑产 inventory、`/mgh-sast` s2/s6/s8 实消费
      > bundle)——非确定性、需 install + 多 subagent,不在本 apply 会话内跑;消费语义由双壳
      > 注入契约 + `controls-context.md` fragment 结构性接线,经 lint 守护。
- [x] 6.3 回滚演练:改动面清单(脚本/双壳/fragment/契约/manifest/测试),全部 additive,无 schema
      迁移;移除 flag/脚本即回退。
