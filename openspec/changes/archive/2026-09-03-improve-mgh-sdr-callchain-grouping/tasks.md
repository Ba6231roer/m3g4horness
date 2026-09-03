# Tasks — improve-mgh-sdr-callchain-grouping

> 实现顺序:`diff_group.py` 分组算法升级(变更符号提取 → 调用边并查集 → 物化)→ 契约补节 →
> 模板占位符语义 → 回归测 → 版本。零运行时依赖贯穿(R2);CLI flag 面与 `pending[]` shape 零变
> (R5.3a/b),下游派发/渲染零改动。前置:`add-mgh-sdr` 已 apply + archive。

## 1. `diff_group.py` 分组算法升级

- [x] 1.1 变更符号提取:`git diff --name-only` → 逐文件 diff hunk 映射到包住它的方法/接口
      (注解启发式;codegraph 可用时 `codegraph node --file --symbols-only` 取符号边界);无法映射
      的 hunk 归文件级变更。单测:hunk→符号映射(注解命中 / 多方法文件 / 无符号文件)。
- [x] 1.2 codegraph 探测 + 调用边采集:probe `<repo>/.codegraph/` 存在 ∧ PATH 有 `codegraph`;
      对每个变更符号跑 `codegraph callers --json` / `callees --json`(subprocess,`--path <repo>`,
      `--limit` 可调),parse JSON;任一失败降级。单测:probe 三态(codegraph 有 / 仅目录无命令 /
      均无)。
- [x] 1.3 并查集连通分量:变更符号集建图(仅保留两端均在变更集内的边),并查集求连通分量;
      含 ≥1 路由注解符号 → interface,其余 → standalone。单测:同链合并 / 反射孤立 / 共享下游。
- [x] 1.4 单元物化:interface 单元 slice = 分量内全部变更符号 hunk + 类级注解上下文 + 权限注解
      命中;standalone = 目录簇 + `--max-standalone-bytes` 超限拆分;共享下游按接口拆、受
      `unit_bytes` 预算;`--check` 覆盖分组自洽。单测:slice 内容 / 预算 / 路径越树拒绝。
- [x] 1.5 退化路径:无 codegraph → 注解+目录(与 add-mgh-sdr D2 逐字等价);stdout `codegraph:
      false`。单测:无 codegraph 时输出与现状逐字等价。

## 2. 契约 + 模板

- [x] 2.1 `core/contracts/sdr/pipeline.md` 增「变更符号提取 + 调用链分组 + 共享下游」小节;
      `pending[]` 字段 shape 不变,stdout 增 `codegraph` bool 字段。
- [x] 2.2 `core/prompts/fragments/fanout/sdr-task.md` 占位符 `{{codegraph}}` 语义更新为「分组
      是否已调用链合并(供 subagent 决定是否用 codegraph 读完整链源码)」;正文措辞微调,占位符集
      不增删。

## 3. 回归测 + 版本

- [x] 3.1 `tests/test_diff_group.py` 扩展(见 §1 各单测点)+ 既有 add-mgh-sdr 测试不回归
      (CLI flag 面 / pending shape / 越树路径 / `--check` / 退出码分流)。
- [x] 3.2 零依赖 AST 扫描覆盖 `diff_group.py`(无第三方 import;`subprocess` 调用 `codegraph`
      为外部二进制,非 pip)。
- [x] 3.3 按 R5.8 bump 版本号;`tools/check_contracts.py` + `check_distributed_purity.py` +
      prompt-budget lint 全绿。
