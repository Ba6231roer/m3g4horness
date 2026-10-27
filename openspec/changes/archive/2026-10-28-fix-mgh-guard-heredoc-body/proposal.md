# fix-mgh-guard-heredoc-body

> **人话序**:真实大仓跑 mgh-init 时,子代理往 checkpoint 文件写 JSON 用的是 `cat > 文件
> <<'EOF' … EOF` 这种"整段喂内容"的写法。守卫检查 Bash 命令时是拿正则扫整段文本,不区分
> "命令部分"和"内容部分"——于是内容里的 `yyyy/MM/dd` 被当成一个越权路径、`>2000` 被当成
> 重定向符号,合法写入被连拦两次;模型第三次为了过守卫**把记录里的日期片段改掉了**,等于
> 守卫误伤直接篡改了产物内容。本 change 给守卫加一步"结构剥离":先把 heredoc/here-string
> 的**数据体**从待判文本里剥掉,再跑路径净网/写动词/重定向判定——数据是数据,不是命令。
> 喂给解释器的 heredoc(`py - <<EOF`,那是在喂代码)不在豁免之列,原有拦截一条不松。

## Why

2026-10-27 对真实 run 两个子代理会话的取证(评审登记册 #22):

1. **误拦一**:JSON 内容含 `yyyy/MM/dd`,被路径判定误解析为越权写路径 → 拦;
2. **误拦二**:内容含 `>2000` 与 `$`,被误判为重定向符号 → 拦;
3. **后果**:模型第三次**改掉记录内容里的日期片段**后成功——守卫误伤导致产物内容被篡改,
   比漏拦一次更伤产物质量;同时每个受影响批次多烧两轮重试(会话从正常批的 130KB 膨胀到
   异常批的 300KB)。

守卫的 Bash 面判定是 regex-over-string(与全部 Bash 规则同立场,诚实边界已声明),但
"heredoc 数据体与命令结构不分"不在已声明残余之列——这是可修的结构性缺陷,不是已知
局限。姊妹问题(#21:守卫拦掉 `py -c` 校验导致写入零语法校验)已随
`harden-mgh-init-output-gates`(0.1.102)落地,不在本 change。

## What Changes

- 守卫(`block_adhoc_scripts.py`,单一真相源)新增**结构剥离预处理**:判定路径净网/写动词/
  删除/重定向四类规则前,先把 bash heredoc(`<<`/`<<-`,含引号定界符)与 PowerShell
  here-string(`@"…"@`/`@'…'@`)的**数据体**从待判文本中剥离——数据体只流向重定向目标
  文件,不构成命令结构。
- **不松任何拦截**:解释器喂养形态(`py - <<EOF`、`python <<'EOF'` 等,既有"内联解释器
  代码拦截"requirement 辖域)在剥离**之前**按原文判定,原样全拦;命令部分(重定向目标、
  路径 token、写动词)照旧全判;未终结/畸形的 heredoc 段**不剥离**(保守判全文,只可能
  误拦不可能漏拦)。
- 三端字节级同步(canonical → claude/opencode 两份 hook 副本,parity 测试强制);契约
  `runtime-enforcement.md` 与根手册守卫段的残余清单同步更新。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `runtime-hook-enforcement`:新增一个 requirement——heredoc/here-string 数据体从 Bash
  命令结构判定中剥离(含解释器喂养豁免、畸形保守、双误拦形态的过/真违规仍拦的场景闭集)。

## Impact

- **改动面**:`core/scripts/block_adhoc_scripts.py`(预处理 + 接线)+ 两份 hook 副本字节
  同步 + `tests/test_block_adhoc_scripts.py`(红→绿)+ 三端 parity 测试 + 契约
  `core/contracts/hooks/runtime-enforcement.md` + 根 `AGENTS.md` 诚实边界守卫段。
- **六域全生效**(守卫为 mgh-init/sast/sra/srr/sdr/ut-init 共用),非 init 专属。
- **零新增依赖**;判定仍在 Python 守卫单一真源,shim/插件零改动;VERSION bump。
- **不做**:非 heredoc 位置的日期形态 token(如引号参数里的 `yyyy/MM/dd`)仍属已知残余,
  本 change 不扩白名单——先修结构,不猜词表。
