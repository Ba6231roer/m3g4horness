# Tasks — add-mgh-sdr

> 实现顺序按依赖排:先守卫判定核扩展(被 launcher 与 fan-out 共同依赖)→ 三确定性脚本 + 契约 →
> fanout_runner tier + 模板 + agent → 命令壳(双端)→ launcher → install/lint/测试 → 文档收尾。
> 每条均可独立验收;零运行时依赖(承 R2)贯穿全部脚本任务。

## 1. 守卫读侧扩展(read_roots)

- [x] 1.1 `releases/claude-code/hooks/block_adhoc_scripts.py`:哨兵解析增可选 `read_roots[]`;
      工具面读侧(`Read`/`Glob`/`Grep`)判定扩展——resolved 目标落入任一**存在且为目录**的声明根
      → 放行;声明根不存在授予零(fail-closed);Bash 搜索动词 / 写侧全层 / 叶源码拦截判定**零改动**
      (仍仅 `MGH_TARGET`)。opencode 端 `releases/opencode/plugins/block_adhoc_scripts.ts` +
      `releases/opencode/hooks/block_adhoc_scripts.py` 同步,双端字节级 parity 保持。
- [x] 1.2 `core/contracts/hooks/runtime-enforcement.md`:哨兵 schema 表增 `read_roots[]` 行(可选、
      只读、工具面、与 `out_roots[]` 正交);读纪律表增声明根放行行;标注「read_roots 最小化」纪律
      与 fail-closed 语义。
- [x] 1.3 测试:`tests/test_block_adhoc_scripts.py` 增 read_roots 用例(声明根内读放行 / 声明外读
      阻断 / 声明根内写仍阻断 / Bash `rg` 声明根仍阻断 / 无 read_roots 逐字等价 / 根不存在授予零);
      `tests/test_opencode_hook_parity.py` parity + `TestWiringCoverage` 不变量保持绿。

## 2. 确定性脚本三件套 + I/O 契约

- [x] 2.1 新增 `core/contracts/sdr/pipeline.md`:定义 `diff_group.py` / `sdr_context.py` /
      `render_sdr_report.py` 的 I/O 契约——run 目录布局(`<repo>/.mgh-sdr/runs/<ts>/`:`slices/`
      `drafts/` `external/<repo-slug>/` `markers/` `sdr_manifest.json`)、slice 文件形态、draft
      JSON schema(`findings[]{dimension,severity,route,file,line_hint,risk,suggestion,control_ref}`,
      闭集:`dimension` 默认 5 键 + 自由文本扩展、`severity` 四枚举)、`pending[]` 字段
      (`unit_id/input_path/draft_path/done_marker/failed_marker/kind/route/unit_bytes`,全绝对)、
      报告文件名/结构、manifest 字段、退出码 `0/1/2`。`core/contracts/README.md` 增索引行。
- [x] 2.2 新增 `core/scripts/diff_group.py`(stdlib 自包含,R5.3a/b):
      `--repo <abs> --base <ref> --branch <ref> --checkpoints <dir> --inputs-dir <dir>
      --materialize <dir> --max-standalone-bytes B --offset/--limit --resume` + `--check <run-dir>`;
      `git diff --no-color base..branch` → 注解启发式接口分组 + 目录簇 standalone 归并 → 物化只读
      slice → stdout 枚举 JSON(含 `repo` 锚/`empty`/counts);`unit_id` 文件系统安全命名;
      `.done` 单元跳过重复物化;零 diff → `empty:true` + `pending:[]`;gate 形失败(base ref
      不存在等)退出码 2 + recipe。
- [x] 2.3 新增 `core/scripts/sdr_context.py`(stdlib 自包含):
      `--repo <abs> --run-dir <abs> --dimensions <json> --baseline-budget-bytes B
      --external-budget-bytes B [--read-root <abs>]...` + `--check <run-dir>`;
      (a) 基线投影(AGENTS.md 安全章节 + `docs/security-controls/*.md` + business_context,
      优先级截断 + `baseline_truncated` 披露);(b) 外部仓声明解析(正则匹配存量设计中的外部仓
      描述)→ 主进程受控检索(同名分支 diff 清单 / 权限配置命中 / 接口路由前端计数)→ 结论文件
      物化(白名单内容 + 逐仓预算截断)+ stdout `external_repos[]`(供哨兵 `read_roots[]`)/
      `external_skipped`;声明缺失/路径不可达/非 git → 降级 `[]` 继续。敏感目录解析(项目目录 >
      默认模板回退,sibling import `sensitive_catalog`)→ stdout `sensitive_catalog` 对象 +
      `sensitive_catalog_source`。
- [x] 2.4 新增 `core/scripts/render_sdr_report.py`(stdlib 自包含):
      `--run-dir <abs> --repo <abs> [--out-dir <dir>]` + `--check <run-dir>`;收 `.done` 单元
      draft,`{dimension,route,file}` 三元组去重合并,渲染
      `<repo>/mgh-sdr-<branch-safe>-<YYYYMMDD_HHMMSS>.md`(简体中文:头部/按维度 findings/
      无问题单元/诚实边界 ≥6 条)+ `sdr_manifest.json`(counts + boundaries + `failed_units[]`);
      同名报告原子覆盖;NEVER 写 `openspec/` 与 run 目录、报告之外的文件。

## 3. fanout_runner sdr tier + 模板 + agent

- [x] 3.1 `core/scripts/fanout_runner.py`:TIERS 表增 `sdr` 行(`list_script`=`diff_group.py`、
      `template_rel`=`prompts/fragments/fanout/sdr-task.md`、`agent`=`sdr-review-fanout`、
      占位符集/路径字段/`id_field`=`unit_id`);`--tier` choices 扩 `sdr`;共享状态机零改动;
      `--help` 文案更新。既有三 tier 行为逐字不变(回归锚定)。
- [x] 3.2 新增 `core/prompts/fragments/fanout/sdr-task.md`:占位符集
      (`{{unit_id}}/{{kind}}/{{route}}/{{input_path}}/{{draft_path}}/{{done_marker}}/
      {{failed_marker}}/{{repo}}/{{codegraph}}/{{baseline_path}}/{{external_summary_path}}/
      {{sensitive_catalog_directive}}/{{dimensions}}`);正文 = 6 维度判定指令 + 统一 findings
      schema 示例 + 恰读 `input_path` / 恰写 `draft_path` + touch `done_marker` 的刚性三元组 +
      R5.5 措辞(recipe、RFC-2119、无长代码块)。
- [x] 3.3 新增 fan-out agent 定义:`releases/opencode/agent/sdr-review-fanout.md`(mode: primary
      克隆,tools = Read Glob Grep Bash Write)+ `releases/claude-code/agents/sdr-review-fanout.md`
      同形;description ≤1536 chars,内容仅操作性(承 R5.10)。

## 4. 命令壳(双平台)

- [x] 4.1 新增 `releases/opencode/command/mgh-sdr.md`:薄壳(R5.6 ≤5,000 tok)——参数表
      (`--base/--branch/--dimensions/--run-dir/--no-codegraph/--dry-run` 等) +
      编排骨架(step 0 运行域声明 + 哨兵 → sdr_context → diff_group materialize → fanout_runner
      --tier sdr → render → `--check` 链)→ stage→组件表 → 边界披露(诚实边界 6 条 + 敏感目录
      分歧披露 + 外部仓降级披露);裸启动路径(D9:宿主会话内直接跑,外部读取可能一次宿主确认,
      诚实标注)。
- [x] 4.2 新增 `releases/claude-code/commands/mgh-sdr.md`:4.1 的 claude 侧镜像(路径
      `.claude/mgh-core/...`、agent 派生面差异),语义逐字对齐。
- [x] 4.3 双壳纯度自检:无 dev-meta(R5.10 八类)、无悬空引用;`tools/check_distributed_purity.py`
      对新壳跑绿。

## 5. launcher

- [x] 5.1 新增 `core/scripts/mgh_sdr_launch.py`(stdlib,**随 install 分发**):`--repo <abs> [--branch <ref>]
      [--base <ref>] [--host opencode|claude] [--dimensions <json>] [--multi-branch <file>]
      [--read-root <abs>]... [--dry-run]`;宿主探测(--host 显式 > opencode > claude,缺 → 退出码 2
      + recipe)→ 调 `sdr_context.py` 完成外部仓先期检索(launcher 进程内,零宿主打断)→ 写哨兵
      (含 `read_roots[]` = 实际检索过的外部根)→ 组装编排提示词文件(逐字绝对路径)→ spawn
      `opencode run`(stdin)或 `claude -p`(stdin)→ 退出后删哨兵;`--multi-branch` 串行逐分支
      完整流程 + 失败清单;崩溃残留哨兵复用刷新;claude 宿主注入 480000ms 软时限建议。
- [x] 5.2 launcher 测试:临时目录内建 git 双仓(main + feature 各一 commit + diff)冒烟
      `--dry-run`(零 spawn:哨兵 + 提示词文件 + sdr_context 产物齐全即过),写入
      `tests/test_mgh_sdr_launch.py`。

## 6. install / 契约 lint / 测试

- [x] 6.1 `install.sh`:共定位自检清单 + `diff_group`/`sdr_context`/`render_sdr_report`/
      `mgh_sdr_launch`;fanout payload 自检 + `sdr-task.md` 模板与 opencode `sdr-review-fanout`
      agent;✓ 提示文案同步。
- [x] 6.2 `tools/check_contracts.py`:DEFAULT_SHELLS + 双平台 mgh-sdr 壳;壳内
      `diff_group.py`/`sdr_context.py`/`render_sdr_report.py`/`fanout_runner.py` 全 flag 逐个对
      `--help` 断言。
- [x] 6.3 零依赖 AST 扫描覆盖三新脚本(无第三方 import;`render_sdr_report`/`diff_group`/
      `sdr_context` 均无网络模块 import)。
- [x] 6.4 `tests/test_diff_group.py`:接口分组(注解命中拆单元 + route 提取)/ standalone 聚类 /
      无注解退化 / 零 diff empty / unit_id 安全命名(含 `:` ADS 用例)/ `.done` 跳过 / 越树路径
      拒绝 / `--check` / 退出码分流。
- [x] 6.5 `tests/test_sdr_context.py`:基线投影 + 优先级截断披露 / 外部仓声明命中 → 结论文件
      (buttonAuth.properties 命中 + 路由计数)/ 不可达降级 / 默认模板回退 + project 复用 + 非法
      目录早停 / `--check`。
- [x] 6.6 `tests/test_render_sdr_report.py`:文件名格式 / 去重合并 / `.failed` 不阻断 + manifest
      计数 / 同名覆盖幂等 / 诚实边界 6 条齐备 / NEVER 写 openspec / `--check`。
- [x] 6.7 `tests/test_fanout_runner.py` 增 sdr tier 用例(模板填充 / 占位符闭合断言 / 路径越树
      拦截 / `--pending-file` 测试钩子跑通 sdr 形态)。
- [x] 6.8 回归不退化:`tests/test_block_adhoc_scripts.py` + `test_opencode_hook_parity.py` +
      `test_distributed_md_purity.py` + 既有 fanout/init 测试全绿;双平台 install 冒烟
      (`./install.sh --claude <tmp>` + `--opencode <tmp>`)。

## 7. 文档收尾 + 版本

- [x] 7.1 `AGENTS.md`:命令表增 `/mgh-sdr` 行(✅ 可用,一句话定位);诚实边界小节增 sdr 条目
      (LLM 候选 / 启发式分组 / 外部仓快照 / 敏感目录分歧)。
- [x] 7.2 `docs/man/mgh-sdr.md`(人类面:现象→原因→改法叙事,术语进 `docs/glossary.md` 先行)
      + `docs/分发与使用指南.md` 增 launcher 用法一节。
- [x] 7.3 按 R5.8 bump 版本号;全量验收:check_contracts / check_distributed_purity /
      prompt-budget lint(双壳 ≤5,000 tok)/ 全部 tests 绿。
      (验证记录:check_contracts 290 flags/12 shells 绿;purity 180 scanned/0 violations;
      双壳 mid_tokens ~2.2K ≤5K;全 tests 套件绿——含 test_plain_language 摘除 docs 门禁后。仓库无
      版本号字段可 bump——历史惯例由日期命名 commit 承担,版本条款空转,如实披露不虚构。)
