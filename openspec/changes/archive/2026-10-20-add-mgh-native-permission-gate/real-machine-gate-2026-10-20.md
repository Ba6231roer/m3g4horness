# 实机闸门笔记:权限询问闸门(2026-10-20)

> **受众:双受众**(维护者评审 + 后续 agent 接手企业闸门)。本文是本 change 的实机证据
> 底座:任务 4.1(本机 2.1.0 闸门)、2.2(兜底层抽查)、4.3(域外抽查)的全部记录,以及
> 任务 4.2(企业 2.0.32 闸门)的待执行复现清单(§4)。
> 本机环境:Windows 11,`opencode2` v2.1.0(npm 包 `@opencode/cli`,内嵌 Bun),模型
> `zai-coding-plan/glm-5.3-flash`(订阅内,7 次小样本 run)。scratch 复用上一 change 的
> `C:\DEV\_mgh_oc2_gate`(重跑 `install.sh --opencode` 刷新插件与 33 个 agent 定义),
> 常驻服务 pid 47608 沿用(插件文件被 install 覆写后服务经文件 watcher 热重载,
> 服务日志 13:27:39 出现新 `loading plugin` 且无任何拒载)。
> 术语:运行域 = 六运行根下有 `.active` 哨兵的受管辖区间;闸门 = 插件内的
> `permission.evaluate` 钩子;守卫 = Python `block_adhoc_scripts.py`(工具面拦截)。

## 0. 结论速览

| 闸门 | 结果 |
| --- | --- |
| 插件双钩子加载(热重载后无拒载;`await ctx.permission.hook("evaluate"` 生效) | ✅ PASS |
| 声明 read_roots 内外部读 → 放行(外部仓工作流零回归) | ✅ PASS(S2) |
| 运行域内 ask 面(`.env` 读)→ 改写 deny + 替代提示,pending 恒为零 | ✅ PASS(S3c) |
| `question` 工具 → 改写 deny + 批量澄清提示,pending 恒为零 | ✅ PASS(S3) |
| 哨兵 JSON 损坏 → fail-closed deny(域仍激活、零 read_roots) | ✅ PASS |
| agent 规则级兜底(fanout agent `question: deny`)| ✅ PASS(工具直接从工具集移除,§3)|
| 拆哨兵后 → 宿主自身询问机制接管(域外零介入) | ✅ PASS(S4) |
| 无 mgh 普通项目 → 与 S4 同形(结构性域外) | ✅ PASS(§3 末)|
| 企业 2.0.32 闸门 | ⏳ 待内网执行(§4 复现清单)|

## 1. 本机 2.1.0 新事实(影响判读,已回填契约版本矩阵)

| 事实 | 证据 |
| --- | --- |
| 默认 Build agent 权限规则集 = `{*: allow}` + `read *.env / *.env.*: ask` + `.env.example: allow`,并显式推 `question: allow` | opencode 源码 `packages/schema/src/agent.ts`(schema 级 default)+ `packages/core/src/plugin/agent.ts`(Build 推 question allow) |
| 因此 **external_directory 在 2.1.0 默认 agent 上是 allow(经 `*` 兜底),不是 ask** —— 越目录读默认不询问;ask 只在用户显式配置 `external_directory: ask`(agent frontmatter / 项目配置)或命中 `.env` 类内置 ask 面时出现 | 同上 + S3b 实测(守卫搬走后越目录读直接成功,无询问) |
| `run`(非交互 CLI 形)对产生的询问是**立即 auto-reject**(「This non-interactive run cannot ask the user for permission…」),不是挂起;无应答挂起(pending 无超时)是 **TUI/常驻服务形**的形态 —— 与 proposal 引用的 P11 复现(服务形观察窗)一致 | S4 实测输出 + 源码无超时结论(前一 change 已钉) |
| 权限层在管线中位于工具面守卫**之后**:越目录读若被 Python 守卫拦下(read 侧越树),询问根本不会产生;守卫**放行**的 ask 面(树内 `.env` 读、声明 read_roots 内的越目录读)才到达权限层 | S1(守卫 recipe 拦)对比 S2/S3c(守卫放行 → 闸门改写) |
| 规则级 deny 在 evaluate 钩子前短路(源码 `evaluateInput` 先 `denied()` 判定),且 2.x 对 deny 的工具会在 codemode 工具集中直接不可见 | 源码 + §3 的 fanout agent 抽查 |

**判读**:P11 形态(无人应答挂死)在本机 2.1.0 上的现实入口 = ①用户显式配置
`external_directory: ask` 后的越目录读;②任何会话里的 `.env` 读(默认 ask 面);
③`question` 工具(Build/plan agent 默认 allow)。三者都被闸门(①②)与 agent 定义
兜底(③,规则级)+ 闸门(③,非 mgh agent 形)覆盖。

## 2. 任务 4.1 样例记录(每条一次 `opencode2 run`,scratch = `C:\DEV\_mgh_oc2_gate`)

环境:哨兵 `.mgh-init/.active` = `{"domain":"mgh-init","target":"C:\\DEV\\_mgh_oc2_gate","out_roots":[],"read_roots":["C:\\DEV\\_mgh_oc2_roots\\approved"],"v":1}`;
外部夹具 `C:\DEV\_mgh_oc2_roots\approved\notes.txt`(内容 `APPROVED_NOTES_OK`)与
`C:\DEV\_mgh_oc2_roots\denied\secret.txt`(内容 `TOP_SECRET_DENY`);项目根 `.env`(内容 `GATE_PROBE_ENV=1`)。

| # | 场景 | 观测 | 判定 |
| --- | --- | --- | --- |
| S1 | 越目录读 `...\denied\secret.txt`(守卫在场,资源在 read_roots 外) | 工具调用失败,recipe = 守卫读侧文案(「blocked: read outside the MGH_TARGET tree…declared read_roots[] cover ONLY their listed roots」),模型复述后正常收尾;**零 pending** | ✅ 拦截发生(工具面先于权限层;询问根本不产生) |
| S2 | 越目录读 `...\approved\notes.txt`(资源在声明 read_roots 内) | 读成功,内容 `APPROVED_NOTES_OK` 回到模型;**零 pending、零询问** | ✅ 闸门 allow 分支生效(守卫放行 → 权限层 external_directory assert → 闸门按 read_roots 全属改写 allow;无闸门时此面 = ask → TUI/服务形挂死) |
| S3 | Build agent 调 `question` 工具 | 工具失败,错误文案 = 闸门提示逐字(「无人值守运行不向用户发问:把待澄清项写入本步骤产物/续跑记录…」);模型输出 `QUESTION_DENIED:permission.rejected - 无人值守…`;**零 pending** | ✅ question 分支生效 |
| S3b | **守卫 .py 临时搬走** + 越目录读(资源在 read_roots 外) | 读**成功**(无询问、无拦截)——2.1.0 默认 agent 的 external_directory 是 allow(`*` 兜底),闸门按规则 ③ 不碰 allow;守卫恢复后同形读即被守卫拦(S1) | ✅ 按契约(闸门只关询问,不做授权收紧;fail-soft 分层与既有「守卫缺席 → PASS」披露一致,如实记录) |
| S3c | 树内 `.env` 读(守卫放行树内读;宿主内置 ask 面) | 工具失败,错误文案 = 闸门 ask→deny 提示逐字(「无人值守运行不接受交互式授权等待…」);模型复述后正常收尾;**零 pending** | ✅ **闸门 ask→deny 分支的直接样本**(spec 场景「运行域内 ask 被改写为 deny」) |
| S4 | **哨兵移走** + 同 S3c 的 `.env` 读 | 宿主自身询问机制接管:`permission requested: read (.env); auto-rejecting` + 宿主文案(「This non-interactive run cannot ask…」);闸门文案**不在场** | ✅ 域外零介入(闸门严格以哨兵为激活信号) |
| S5 | 哨兵 JSON 写成 `{{{corrupt` + 同 S3c 读 | 闸门 ask→deny 提示逐字在场(fail-closed:域仍激活、read_roots 按 空 处理) | ✅ spec 场景「哨兵 JSON 损坏时 fail-closed 且不伤宿主」 |

哨兵与守卫在样例间按上表即时搬移/恢复;结束时哨兵已恢复为带 read_roots 的有效 JSON,
守卫 .py 在位。

## 3. 任务 2.2(兜底层抽查)与 4.3(域外抽查)

- **兜底层**:以 `--agent sdr-review-fanout` 跑 `question` 调用样例 → `Unknown tool
  'question'` —— 规则级 `question: deny` 使该工具对 agent **工具集直接不可见**(对比:
  未钉 pin 的 Build agent 上 question 工具在场,S3 即证)。兜底层生效形态比预期更强:
  模型连尝试都不能。两层不冲突实证:规则级 deny 短路在钩子前,兜底层拦 mgh 自带
  agent,闸门拦其余会话形状,互不重叠也互不依赖。
- **域外抽查**:新建普通项目 `C:\DEV\_mgh_oc2_plain`(无 `.opencode/`,即无插件、
  无哨兵)跑同款 `.env` 读 → 输出与 S4 完全同形(宿主 auto-reject 文案)。结构性域外:
  插件按项目 `.opencode/plugins/` 发现,普通项目里闸门代码根本不存在。

## 4. 企业 2.0.32 闸门:待执行复现清单(任务 4.2;内网执行,不阻塞本仓归档)

**判据**:①插件加载成功(服务日志无 `Plugin must export a default definition…`);
②§2 样例集拦截/放行结果与本机一致;③记录 2.0.32 与 2.1.0 的两处差异点(见下
「重点观测」),差异若影响实现则回填 design「Open Questions」并按公共面收敛。

准备:

1. `opencode2 --version`(期望 2.0.32;命令名以企业实际为准)。
2. 隔离目录真装:`./install.sh --opencode <隔离目录>`;确认安装副本
   `.opencode/plugins/block_adhoc_scripts.ts` 含 `await ctx.permission.hook("evaluate"`。
3. 建外部夹具两个目录(一个将声明进 read_roots、一个不声明),各放一个文本文件。
4. 手写哨兵(把 `<隔离目录>` 换成实际绝对路径,JSON 里反斜杠双写;
   `read_roots` 换成实际声明目录):
   `<隔离目录>\.mgh-init\.active` =
   `{"domain":"mgh-init","target":"<隔离目录>","out_roots":[],"read_roots":["<声明目录>"],"v":1}`。
5. 项目根放一个 `.env` 文件(S3c/S4 样例用)。

样例集(每条一个 run,模型换内网可用模型;预期结果注明):

| # | prompt 要点 | 预期(同本机 §2 编号) |
| --- | --- | --- |
| 1 | 声明 read_roots 内的外部文件读 | 内容返回、零询问(S2) |
| 2 | 项目根 `.env` 读 | 工具失败 + 闸门提示(「无人值守运行不接受交互式授权等待…」)(S3c) |
| 3 | `question` 工具调用 | 失败 + 闸门提示(「无人值守运行不向用户发问…」)(S3) |
| 4 | 移走哨兵后重复样例 2 | 宿主自身询问机制接管(auto-reject 或弹窗,按企业形态),闸门文案不在场(S4) |
| 5 | read_roots 外的外部文件读(守卫在场) | 守卫读侧 recipe 拦截(S1;若企业构建守卫路径不同,以实际 recipe 为准) |
| 6(可选)| TUI/服务形会话重复样例 2 | 询问**不产生**(闸门改写在先)——此样例只有在企业能开 TUI 观察窗时做 |

**重点观测(回答 design「Open Questions」)**:

- 2.0.32 默认 agent 的 `question` 效果是否同为 allow(Build agent 是否同样显式推
  allow):看样例 3 在**未加闸门**的旧插件副本上是否产生询问/表单。
- `external_directory` 询问的资源通配尾缀形态是否同为 `<dir>/*`(正斜杠 + `/*`):
  给 agent 显式配 `external_directory: ask` 后做一次越目录读,记录 evaluate 事件或
  最终效果;实现按「剥尾缀后前缀匹配」防御,两形皆容。
- 若 2.0.32 没有 `permission.evaluate` 钩子面(该钩子为 2.x 引入,2.0.32 属 2.x 早期,
  预期有):以样例 2 判定——若询问未被改写(出现表单/auto-reject 而非闸门文案),
  记录为**版本断代事实**回填契约版本矩阵,兜底层(样例 3 的 agent pin)在该版独立兜底。

回执处置:全样例 PASS → 双版本闸门闭合,本节改判 PASS 并随归档;任一样例差异 →
差异清单回填 design「Open Questions」+ 契约版本矩阵,再评是否收敛实现。
