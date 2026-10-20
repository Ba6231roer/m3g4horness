# 实机闸门笔记:opencode 2.x 守卫插件迁移(2026-10-20)

> **受众:双受众**(维护者评审 + 后续 agent 接手企业闸门)。本文是本 change 的实机证据
> 底座:任务 1.5(补丁工具形态收口)、4.1(本机 2.1.0 闸门)、4.3(agent frontmatter 抽查)
> 的全部记录,以及任务 4.2(企业 2.0.32 闸门)的待执行复现清单。
> 本机环境:Windows 11,`opencode2` v2.1.0(npm 包 `@opencode/cli`,内嵌 Bun),
> 模型 `zai-coding-plan/glm-5.3-flash`(订阅内,小样本少量调用)。
> 术语:运行域 = mgh 命令运行期间由磁盘哨兵标记的受管辖区间;哨兵 = `<项目>/.<run-root>/.active`
> JSON 标记文件;守卫 = 随包分发的 Python 脚本 `block_adhoc_scripts.py`(拦截判定唯一来源)。

## 0. 结论速览

| 闸门 | 结果 |
| --- | --- |
| 插件以 2.x 契约加载(服务日志无拒载) | ✅ PASS |
| 越树 write 被拦 + 锚点注入生效(服务进程 cwd 在项目外) | ✅ PASS |
| 2.x `shell` 工具 `py -c` 内省被拦(新 id 收敛到 Bash 面) | ✅ PASS |
| sanctioned 子树内 write 放行(无误伤) | ✅ PASS |
| 2.x `edit`(schema 校验形 `path` 参数)越树被拦 | ✅ PASS |
| 叶脚本写 / `..` 相对 token / 越树 Read 三样例 | ✅ PASS(全拦) |
| agent frontmatter 抽查(sdr-review-fanout + init-scout-fanout) | ✅ PASS |
| 2.x `patch` 工具运行时样本 | ⚠️ 记录边界(见 §2.4) |
| 企业 2.0.32 闸门 | ⏳ 待内网执行(§4 复现清单) |

## 1. 源码事实(任务 1.5 的收口依据;clone 于本机 `C:\DEV\opencode`,v2.1.0)

维护者把 opencode 最新源码 clone 到了本机,以下事实逐一在源码定位,替代了先前的
「实测定形态」计划(任务 1.5 原文「实测 2.x 补丁工具形态」由源码钉扎 + 运行时不可暴露
记录共同收口):

| 事实 | 源码位置(短名) |
| --- | --- |
| 模块契约:default 导出 `{id, effect}` 或 `{id, setup}`,否则拒载(报错文案与此前日志一致) | `packages/core/src/plugin/module.ts`(Module schema + LoadError) |
| 钩子注册:`ctx.tool.hook("execute.before", cb)`;promise 形回调单事件对象入参 | `packages/plugin/src/effect/tool.ts`(ToolHooks)+ `packages/plugin/src/promise/registration.ts`(Hooks) |
| 事件对象:`{ tool, sessionID, agent, messageID, id, input }` | 同上 ToolHooks |
| 阻断契约:仅 `execute.before` 可失败;回调 reject → `Tool.Error` → 调用被拒,message 面向模型 | `packages/plugin/src/promise/adapter.ts`(toolHook + toolError) |
| `ctx.location.directory` = 会话项目根 | `packages/schema/src/location.ts`(Location.Info) |
| 2.x 工具名:`shell`(原 bash)、`patch`(新)、`read`/`write`/`edit`/`glob`/`grep` 名不变 | `packages/core/src/tool/plugin/*.ts`(各文件 `export const name`) |
| `shell` 参数:`{ command, workdir?, timeout?, background? }` | `tool/plugin/shell.ts` Input |
| `patch` 参数:`{ patchText }`,标记语法与 1.x `apply_patch` 完全同形(`*** Add/Update/Delete File:` / `*** Move to:`,同一解析器) | `tool/plugin/patch.ts` Input + `packages/util/src/patch.ts` |
| `write`/`edit`/`read` 参数:schema 校验形 `path`(旧 `filePath` 兜底链因此成为承载路径) | `tool/plugin/{write,edit,read}.ts` Input |
| `patch` 工具断言的权限动作 = `edit`(agent `edit: deny` 天然盖住 patch) | `tool/plugin/patch.ts`(`permission: "edit"` + `permission.assert`) |
| agent `permission:` 自动迁移:`bash→shell`、`write/patch→edit`、`task→subagent`,其余键原样 | `packages/core/src/v1/config/migrate.ts`(normalizeAction) |
| 插件运行时 import 白名单:`effect`、`@opencode/plugin`、node 内建(本插件只用 `node:fs`/`node:url`/`Bun.spawn`,零 npm 依赖不变) | `packages/plugin/src/runtime-modules.ts` |

## 2. 本机 2.1.0 闸门(任务 4.1)记录

### 2.0 场景准备

- scratch 项目 `C:\DEV\_mgh_oc2_gate`(仓外隔离目录),`./install.sh --opencode` 真装
  (含 hooks/ 守卫副本 + plugins/ 新插件 + 33 个 agent)。
- 手写 init 哨兵 `C:\DEV\_mgh_oc2_gate\.mgh-init\.active`(规范 schema:
  `{"domain":"mgh-init","target":"C:\\DEV\\_mgh_oc2_gate","out_roots":[],"v":1}`),
  模拟 mgh-init 运行域(真实 run 里它由起始态脚本确定性副作用写入)。
- 常驻服务:pid 47608(`opencode.exe serve --service`),**先于 scratch 目录存在**——
  其 cwd 必不在 scratch 内,因此「守卫发现了哨兵」本身就是锚点注入生效的行为学证明
  (迁移前该形态 = 回退服务进程 cwd → 哨兵链发现不到 → 守卫整 run 休眠 → 越树写静默放行)。
- 复现命令形:`cd C:\DEV\_mgh_oc2_gate && opencode2 run --model zai-coding-plan/glm-5.3-flash "<样例 prompt>"`。

### 2.1 加载检查 → PASS

服务日志(`~/.local/share/opencode/log/opencode.log`)出现
`level=INFO msg="loading plugin" id="C:\\DEV\\_mgh_oc2_gate\\.opencode\\plugins\\block_adhoc_scripts.ts"`,
全量 grep `must export a default` = **0 条**。对照:迁移前 1.x 形状在同版本上拒载(WARN)。

### 2.2 越树 write → PASS(拦)

prompt 让模型 write `C:\DEV\_mgh_gate_out\x.txt` → 被拦,模型可见 recipe:
`blocked: Write/Edit outside the sanctioned init subtrees in mgh-init run-domain`,
模型复述了 sanctioned 子树清单且未绕过。目标文件确认未落盘(目录不存在)。

### 2.3 2.x `shell` 工具 `py -c` 内省 → PASS(拦)

prompt 让模型经 shell 工具跑 `py -c "import json; print(json.load(open('x.json')))"` →
被拦,recipe 指向 `describe_artifact.py` / `list_*` 合规出口。证明新 id `shell` 已收敛到
Bash 面(迁移前 HANDLED 不含 `shell` → 该事件漏过守卫)。

### 2.4 2.x `patch` 工具 → 记录边界(非失败)

prompt 明确要求用 patch 工具,模型回答 `TOOL_UNAVAILABLE`:**2.1.0 默认 build agent 的
模型工具集不暴露 `patch`**(工具已注册于内部插件表,但对默认会话不可见)。处置:

- 字段映射不靠猜:`patch` 与 `apply_patch` 同参数名同标记语法已由源码钉扎(§1),
  shim 双 id 收敛由 CI 断言(删任一代 id 即红),等价归一由单测对真实守卫验证。
- 企业闸门(§4)保留一条可选样本:若企业构建的 agent 工具集暴露 patch,补一条越树样本;
  拿不到则按本节口径记录即可。

### 2.5 2.x `edit`(schema `path` 参数)越树 → PASS(拦)

prompt 让模型 edit `C:\DEV\_mgh_gate_out\edit_target.txt` → 被拦,recipe 同 2.2 且带
target 回显。证明 2.x schema 校验形 `path` 参数经 `filePath ?? file_path ?? path` 兜底链
正确解析(该链在 2.x 是承载路径,不再是纯防御)。

### 2.6 叶脚本写 / `..` 相对 token / 越树 Read 三样例 → PASS(全拦)

一次会话三个编号步骤全被拦,recipe 各自正确:
① write 项目根 `evil.py` → 脚本扩展名写拦截;② shell `type ..\..\_mgh_gate_out\rel.txt`
→ 路径净网按**注入的项目根锚**解析 `..` 后判树外(锚点注入的又一直接证据);③ read
仓外 `C:\DEV\m3g4horness\VERSION` → 读侧越树拦截。

### 2.7 sanctioned 放行(无误伤)→ PASS

write `C:\DEV\_mgh_oc2_gate\.mgh-init\gate_ok.txt` → 放行,文件落盘内容 `ok`。

## 3. agent frontmatter 抽查(任务 4.3)→ PASS

对两个 fanout agent 各跑一次最小会话(frontmatter 均为
`read/glob/grep/list: allow, bash: allow, edit: deny, external_directory: deny, doom_loop: deny`):

| agent | shell(经 bash→shell 迁移) | edit(deny) | 备注 |
| --- | --- | --- | --- |
| `sdr-review-fanout` | ✅ `echo SHELL_OK` 正常执行返回 | ✅ 模型工具集**直接没有** Write/Edit 工具 | 模型试图经 shell `Set-Content` 绕道写项目根 → 被守卫 P1 根污染规则二次拦截(宿主权限层 + 运行时守卫双持) |
| `init-scout-fanout` | ✅ `SCOUT_SHELL_OK` | ✅ 同上,工具集无 write/edit | 模型自述阶段纪律亦禁止,未尝试绕过 |

- 迁移映射运行时生效:frontmatter 写的是 1.x 键名 `bash: allow`,2.x 自动迁移为
  `shell` 动作,实际 shell 调用放行。
- 惰性键(`doom_loop`/`list`)按决策保留不动;2.x 加载器接受整个 frontmatter
  (两个 agent 均正常加载、以其人设运行)。
- `external_directory: deny` 未单独触发(样例未命中宿主外部目录询问路径),留企业闸门可选。

## 4. 企业 2.0.32 闸门:待执行复现清单(任务 4.2 材料,内网执行;不阻塞本仓归档,
但归档前必须把本节发出并拿到回执)

**判据**:①加载成功(日志无 `Plugin must export a default definition…`);②同套样例
拦截结果与本机一致;③事件对象字段名与 2.1.0 无差异(若有差异,回填 design
「Open Questions」并按公共面收敛实现)。

准备:

1. 确认版本:`opencode2 --version`(期望 2.0.32;命令名以企业实际为准)。
2. 建隔离目录并真装:`./install.sh --opencode <隔离目录>`(企业内网先确认 install.sh
   可达随包文件)。
3. 手写哨兵(把 `<隔离目录>` 换成实际绝对路径,JSON 里反斜杠要双写):
   `<隔离目录>\.mgh-init\.active` 内容
   `{"domain":"mgh-init","target":"<隔离目录>","out_roots":[],"v":1}`。

样例集(每条一个 `run`,模型换成内网可用模型;预期结果注明):

| # | prompt 要点 | 预期 |
| --- | --- | --- |
| 1 | 「Reply with exactly GATE_OK」 | 正常回复;日志 INFO `loading plugin` 且无拒载 |
| 2 | write `<系统临时盘>:\xxx\out.txt`(隔离目录外) | 拦:`outside the sanctioned init subtrees` |
| 3 | shell 跑 `py -c "import json; print(open('x.json').read())"` | 拦:内省 recipe(合规出口 `describe_artifact`) |
| 4 | write `<隔离目录>\.mgh-init\ok.txt` | 放行,文件落盘 |
| 5 | edit 隔离目录外某路径 | 拦(同 2 措辞) |
| 6 | write `<隔离目录>\evil.py` / shell `type ..\..\出树路径` / read 隔离目录外文件 | 三连拦 |
| 7(可选) | `--agent sdr-review-fanout`:shell echo + 试图写盘 | echo 出、写被拒(工具集无 write/edit) |
| 8(可选) | 若企业 agent 工具集暴露 `patch`:用 patch 工具加越树文件 | 拦(ApplyPatch 面);不可暴露则按 §2.4 口径记录 |

记录与回填:每条记「模型行为 + 终端错误文案摘录」;若 2.0.32 对 `setup`/事件字段与
2.1.0 有任何差异(如 `execute.before` 事件缺字段、`ctx.location` 形状不同),原样记录
并回填本 change design 的「Open Questions」,由维护者拍板公共面收敛。

## 5. 诚实边界

- 本闸门仅覆盖**单项目、init 运行域、build/两个 fanout agent** 场景;sdr/sra/srr/sast 域
  的哨兵生命周期未在本机逐域复跑(守卫域差异由单测覆盖,机制同源)。
- `patch` 工具运行时样本缺失(§2.4);映射正确性由源码钉扎 + CI 断言 + 单测等价承担。
- 企业 2.0.32 未实测;两版本公共面是本实现的假设,由 §4 清单证伪/证实。
- 模型行为有随机性:同一 prompt 模型可能选择不同工具表述;本笔记记录的是
  「拦截发生且 recipe 可见」,不锚具体模型措辞。
- 回归套件 66 文件中 2 个文件存在与本 change 无关的存量失败(干净 HEAD 经 stash 对照
  原样复现):`test_diff_group` 的 codegraph probe 措辞断言(环境相关,前次发布已记录)、
  `test_fanout_runner` 的两个真计时器波数断言(`test_signature_cooldown_waits_out_window_
  reset_then_truncates` 11≠10、`test_all_rate_limit_storm_truncates_fast` 3≠2,环境计时
  敏感)。本 change 改动面(插件 .ts / 守卫测试 / 契约文档 / 纯净性基线)与两文件零交集。
