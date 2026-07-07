# Tasks — harden-mgh-sast-orchestration-discipline

> 依赖顺序(镜像 `harden-mgh-init`):补扇出枚举脚本(L2,最低风险,先填真实缺口)→ 确定性阶段
> `--check`(R5.9)→ 双壳信息流固化(L1)→ subagent 白名单(L4)→ hook(L3,复用既有、扩激活域)→
> AGENTS.md 措辞(L5)→ 回归 + 端到端。每条可独立验收。遵守 AGENTS.md R1–R5(零依赖、移植提示词
> 正文不改、复用导入、R5.1 CLI lint、R5.8 回归、R5.10 分发纯净)。新脚本 MUST 经
> `tools/check_contracts.py` 断言其 `--help` 含双壳镜像的所有 flag。

## 1. 补扇出 pending-list 脚本空洞(L2 / FD2;闭合 s4/s6 与 mgh-init T1 的不对称)

- [x] 1.1 `core/scripts/list_chunks.py`:镜像 `list_clusters.py`。读 s3 产物 `chunks[]` + 扫
      `<repo>/security-scan/checkpoints/s4/*.json.done`;stdout `{repo,total,done,pending[],truncated}`,
      `pending[]` 每项 `{chunk_id,files[],threat_id,hypothesis}`;stderr 仅诊断;退出码 `0/1/2`。
      自定位 `sys.path`、utf-8、零依赖、任意 cwd。
- [x] 1.2 `core/scripts/list_verify_jobs.py`:读 s5 产物 `findings[]` + 扫
      `checkpoints/s6/*.json.done`;stdout `{repo,total,done,pending[],truncated}`,`pending[]` 每项
      `{finding_id,file,line,vuln_class,source_ref,sink_ref}`。同 1.1 契约。
- [x] 1.3 两份 `mgh-sast.md`:s4 扇出段与 s6 扇出段的「fan out per chunk / per finding」前插入
      「先 `list_chunks.py` / `list_verify_jobs.py` 取 pending,再迭代」;`--resume` 段同步。
- [x] 1.4 确认/补 s3/s5 产物的稳定字段名(`chunk_id`/`finding_id`)与 checkpoint 目录约定
      (`checkpoints/s4/<id>.json.done`、`checkpoints/s6/<id>.json.done`);落
      `core/contracts/sast/fanout-enumeration.md` 作 pending 清单 stdout 的唯一 I/O 契约。

## 2. 确定性阶段 --check(R5.9 / FD5;泛化 mgh-init assemble_rules --check 范式)

- [x] 2.1 `core/scripts/prefilter.py`:增 `--check <s5_filtered.json>`,断言每条 finding 有
      `file`/`line`/`vuln_class`/`source_ref`/`sink_ref`;退出码 0 ok / 2 违例。
- [x] 2.2 `core/scripts/dedup.py`:增 `--check <s7_findings.json>`,断言无明显近重复簇(复用其
      既有 Jaccard/proximity 阈值,仅校验产物不重算)。
- [x] 2.3 `core/scripts/emit_sarif.py`:增 `--check <report.sarif>`,断言 SARIF 2.1.0 合法 + 每条
      `run.invocation` 存在。
- [x] 2.4 两份 `mgh-sast.md`:每个确定性阶段产物步骤后插「跑 `<producer> --check`,失败退出码 2
      → 回退重跑」。
- [x] 2.5 (次要/open)评估 `diff_seed.py`/`expand_scope.py` 是否加 `--check`(scope_manifest 已有
      `unresolved[]` 披露);收益小则记 open 不做。

## 3. 双壳信息流固化(L1 / FD1+FD7;刚性三元组 + implementation-intention)

- [x] 3.1 两份 `mgh-sast.md`:顶部增「编排器 = 宿主 agent,非写成代码」+ 三条 `NEVER` 明线
      ((a) `Write` 任何 `.py`(`mgh_sast.py`/`_prep_chunks.py`/`_aggregate_verify.py`);(b) `py -c`
      内省 `checkpoints/**`/`scope_manifest.json`;(c) `Read` 叶子 `.py` 源码)。
- [x] 3.2 两壳编排流:s4/s6 fan-out 改刚性三元组 `[输入产物::字段] → script/subagent →
      [输出产物::字段]`;doubt 时刻内联 1 行 shape。
- [x] 3.3 两壳:声明 `s5_filtered.json` / `s7_findings.json` 为**终态**(不再二次聚合/重切)。
- [x] 3.4 两壳:implementation-intention 段(需工作清单→`list_chunks`/`list_verify_jobs`;瞄结构→
      `describe_artifact`(复用);派生量→产出者 stdout;NEVER `py -c`)。

## 4. subagent sanctioned-tools 白名单(L4 / FD6;治 subagent 侧写脚本,R1 合规追加)

- [x] 4.1 `core/prompts/stages/s4-system.md`:追加 Sanctioned-tools 段(Read/Glob/Grep 自由、脚本
      仅 `chunk_sources.py`、NEVER `Write .py`/`py -c`、输入产物为终态)。**只追加、不改 vvah 正文
      与 `Source:` 溯源注释**。
- [x] 4.2 同上追加到 `s1-survey.md`/`s2-threat-model.md`/`s3-decompose.md`/`s6-verify.md`/`s8-chain.md`
      (LLM 阶段;s5/s7/s9 确定性阶段免)。
- [x] 4.3 双壳 `agents/sast-*.md`(claude + opencode 镜像):Hard constraints 段同步「NEVER Write .py
      / py -c」(双重防线)。

## 5. 运行时强制 hook(L3 / FD4;复用既有,扩激活域,兑现 R5.7)

- [x] 5.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:激活条件从 `MGH_INIT_ACTIVE=="1"`
      扩为 `MGH_INIT_ACTIVE=="1" or MGH_SAST_ACTIVE=="1"`(同一正则/白名单);recipe 增列 sast 合法
      出口(`list_chunks`/`list_verify_jobs`/`describe_artifact`)。零依赖。
- [x] 5.2 `install.sh`:确认 hook 注入幂等(已由 mgh-init 注入,不重复加 matcher);`--no-enforce-hook`
      opt-out 行为不变;无需新注入逻辑。
- [x] 5.3 两份 `mgh-sast.md`:编排器起步 `Bash: export MGH_SAST_ACTIVE=1`(声明运行域);壳顶部声明
      hook 存在及 opt-out。
- [x] 5.4 `tests/test_block_adhoc_scripts.py`:扩 `MGH_SAST_ACTIVE` 双栏断言——放行 `py <path>/prefilter.py …`;
      拦截 `py -c "import json; json.load(open('security-scan/checkpoints/s5_filtered.json'))"`、
      `Write _prep_chunks.py`。既存 `MGH_INIT_ACTIVE` 用例不回归。

## 6. AGENTS.md 措辞 sharpen(L5 / FD8)

- [x] 6.1 R5.7「当前兑现」行:从 `/mgh-init` 扩为 `/mgh-init + /mgh-sast`(`block-adhoc-scripts.py`
      覆盖双命令 #1 违例=微脚本内省)。
- [x] 6.2 R5.9「当前覆盖」行:增 `prefilter`/`dedup`/`emit_sarif` `--check`。
- [x] 6.3 确认 R5.2/R5.3 条文已命令通用(无需改),仅在 R5.7/R5.9 兑现清单反映 sast。

## 7. 契约 lint + 回归单测(R5.1 / R5.8)

- [x] 7.1 `tools/check_contracts.py`:扩到 `list_chunks`/`list_verify_jobs` + 既有脚本新 `--check`
      flag + `--controls`(若 add-mgh-sast-design-controls 已合);断言双壳 MD 里每个 `*.py --flag`
      在 `--help` 存在。
- [x] 7.2 `tests/test_list_chunks.py`:resume-aware pending(部分 `.done` → pending 仅含未完成);
      空/截断不静默;wrapper 误判防护。
- [x] 7.3 `tests/test_list_verify_jobs.py`:同 7.2 形态。
- [x] 7.4 `tests/test_stage_check.py`:扩 `prefilter`/`dedup`/`emit_sarif` `--check`(正常产物退出 0、
      破损产物退出 2)。
- [x] 7.5 既有 R5.8 回归扩面:新脚本在**非脚本目录 cwd** 子进程跑(导入鲁棒)、零依赖 AST 扫描、
      `--help` 即契约、性能不退化。

## 8. 端到端验证

- [x] 8.1 `py tests/`(全部,含新测试)绿;`tools/check_contracts.py` 0 违例;零依赖 AST 扫描无输出;
      `tools/check_distributed_purity.py` 0 命中。
- [x] 8.2 双壳 install 自检通过(`./install.sh --claude <tmp>` / `--opencode <tmp>`):脚本就位、
      hook 注入幂等、opt-out 生效 **(本机)**。
- [ ] 8.3 合成中仓跑 `/mgh-sast --repo .`:编排器全程**不出现** `py -c` 内省 / `Write _*.py`;s4 走
      `list_chunks.py`、s6 走 `list_verify_jobs.py`、瞄结构走 `describe_artifact.py`;各 `--check` 通过;
      hook 不误伤合法叶子调用 **(本机)**。
- [ ] 8.4 真机大仓复跑 `/mgh-sast`:s4/s6 扇出走枚举脚本、无微脚本内省;mgh-init FD1 失败形状不在
      sast 复现 **(待用户真机)**。
- [x] 8.5 回滚演练:改动面清单(脚本新增/改、hook 改、双壳改、prompt 追加、AGENTS.md 改、契约改、
      测试新增);无 schema/数据迁移;opt-out 可完全回退 hook 层;移除新脚本/`--check`/overlay 即回退。
