# Tasks — harden-mgh-opencode-hook-parity

> 顺序按依赖:先真机探路(决定 opencode 阻断是否可行)→ shim/注入/测试 → 删错误前提 → README/AGENTS 收口 → 验收。
> 即便任务 1 核验出阻断不可行,任务 5/6(纠正文档前提)仍照做,opencode 端退为 best-effort 插件 + 明线/`--check` 兜底。

## 1. 真机核验 opencode `tool.execute.before`(前置探路)

- [x] 1.1 在真实 opencode 上核验 `tool.execute.before` **触发可靠性**(对齐社区 issue #1706),记录可靠版本下限
- [x] 1.2 核验**阻断 API**(throw / 返回 error 形态 / 改写 result)与**插件发现机制**(`.opencode/plugins/*.ts` 自动加载 vs config 注册)
- [x] 1.3 核验 opencode 工具事件**输入形态**(tool 名 / `command` / `path` 字段),定出归一化映射 → Claude `{tool_name, tool_input}`
- [x] 1.4 决策点:若阻断不可行 → opencode 端降级为 best-effort 插件(可观测不阻断)+ 明线/`--check` 兜底,记入 design 风险与「诚实边界」(文档前提仍纠正)

## 2. opencode 守卫 shim(核心移植)

- [x] 2.1 新增 `releases/opencode/plugins/block_adhoc_scripts.ts`:订阅 `tool.execute.before`;把 opencode 事件归一化为 Claude PreToolUse stdin 形态;管道调 `block_adhoc_scripts.py`;据退出码 2 阻断该调用、否则放行
- [x] 2.2 shim 仅胶水(零业务逻辑):环境门控/正则/白名单/子树守卫全部经 Python 守卫,**NEVER** 在 TS 重写

## 3. install 对等注入

- [x] 3.1 新增 `tools/install_opencode_plugin.py`(镜像 `install_hook.py` 契约:幂等落 `.ts` 进 `.opencode/plugins/`、合并不覆盖用户既有插件、`stdout`=JSON/`stderr`=诊断/退出码 0-1-2/`--remove`)
- [x] 3.2 `install.sh` opencode 分支:`warn+跳过` → 调 `install_opencode_plugin.py` 注入;失败 fail-soft(warn,不阻断 install;CI 必 fail)
- [x] 3.3 `install.sh` 镜像 `releases/opencode/plugins/` → `.opencode/plugins/`(与 `hooks/`→`.claude/hooks/` 对称)
- [x] 3.4 `install.sh` 注释与消息更新:claude-only 表述 → 双端对等;移除 `capability unsupported`

## 4. 测试

- [x] 4.1 新增 `tests/test_install_opencode_plugin.py`:幂等 / 合并不覆盖 / `--remove` / 退出码契约
- [x] 4.2 归一化层单测:opencode 事件形态 → 喂 `block_adhoc_scripts.py`,断言同 claude 端判定(`py -c` 内省阻断 / 合法叶子放行 / 子树外写入阻断)
- [x] 4.3 回归:`tests/test_install_hook.py`(claude 端不破)、`tests/test_block_adhoc_scripts.py`(守卫不改,应全绿)
- [x] 4.4 CI 守门:零依赖 AST 扫描(只扫 `*.py`)与纯净性 lint(只扫既定 `*.md` 目录)均不受 `.ts` 影响——断言扫描集未被误扩

## 5. 删错误前提(全仓文档)

- [x] 5.1 `install.sh` 注释 + stderr 消息:`capability unsupported` / `无等价 PreToolUse 能力` → `opencode 等价 hook = tool.execute.before 插件(移植缺口,本变更即补)`
- [x] 5.2 确认本变更 delta(`specs/control-discovery/spec.md`)与实现一致;归档时 `openspec sync` 自动把主 spec 的错误前提条款替换为本 delta 的 MODIFIED 条款
- [x] 5.3 `releases/opencode/command/mgh-init.md`:删 line 15「PreToolUse 能力缺失」、line 59「opencode 无 PreToolUse」→ 准确表述
- [x] 5.4 `releases/opencode/command/mgh-sra.md`:删 line 11-12「无 PreToolUse hook 能力 / 无 hook」、line 50「opencode 无 hook」→ 准确表述
- [x] 5.5 `releases/opencode/command/mgh-sast.md`:删 line 13-14「PreToolUse 能力缺失」→ 准确表述

## 6. README + AGENTS.md 收口

- [x] 6.1 `AGENTS.md` R5.7:补 opencode 插件形态(`tool.execute.before`/`tool.execute.after`)+「移植缺口非能力缺口」;对 `.ts` shim 做 R2 定性(opencode 原生胶水、非 Python 运行时依赖;守卫逻辑单一来源在 Python 标准库脚本)
- [x] 6.2 `README.md` 目录布局:补 `releases/opencode/plugins/`(装入目标 `.opencode/plugins/`);安装/hook 描述改双端对等
- [x] 6.3 `README.md` 安装段 / 「诚实边界」:opencode 端运行时纪律 hook 现已对等 + 可靠性边界披露(版本下限 / best-effort 退路)
- [x] 6.4 `CHANGELOG.md` bump 版本号(承 R5.8)

## 7. 验收

- [x] 7.1 `openspec validate` 通过;纯净性 lint + 零依赖自检 + 契约 lint(`tools/check_contracts.py`)+ AST 零依赖扫描全绿
- [x] 7.2 真机:`install.sh --opencode` 落插件 → opencode 跑 `/mgh-init` 触发 `py -c` 内省被阻断(与 claude 端对等);`--no-enforce-hook` 仍可 opt-out
  - 已验证:`install.sh --opencode` 落 `.ts` 插件 + 守卫 `.py`(co-located);`--no-enforce-hook` opt-out 生效(无 `plugins/`);**守卫调用路径端到端**(shim 归一化 → `py <守卫>` 子进程 + stdin JSON + 继承 env → 退出码 2 阻断)实测 block/pass/no-domain 三态正确;阻断 API(throw)+ 插件自动加载 + `tool.execute.before` 触发据 opencode v1.17.15 源码核验。
  - **待办(环境受限)**:opencode CLI / Bun 未在本机 PATH,故**未做 live opencode TUI 实跑** `/mgh-init`(装 Bun 后跑一次即可收尾);env 不继承边界已写进 design/AGENTS/README。
- [x] 7.3 回灌:把真机核验出的 opencode 阻断 API / 版本下限 / 触发可靠性写回 `design.md` 风险项 + `AGENTS.md`/`README.md`「诚实边界」
