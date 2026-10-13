# fix-mgh-guard-enforcement-integrity

> **人话序**:深度评审的守卫域批次:三端共用的运行时守卫 `block_adhoc_scripts.py` 有两个高危缺口——
> ①重定向越树拦截对 sast/sra/srr/sdr 四个域**整体放行**(一个被两个语义相反的调用点复用的函数,对无
> 白名单域直接返回「放行」),实测 `echo x > <声明的只读根>/f` 全链路 exit 0,直接违反「声明只读根
> 永不可写」铁律;②守卫读 stdin 时未强制 UTF-8,中文 Windows(GBK 管道)下 payload 解成乱码 → 哨兵
> 锚点断裂 → **六域全部规则对每次调用静默放行**(评审实机 A/B:同一份 UTF-8 字节,utf-8 下拦、gbk 下
> 放)。本批把三个写入口统一为「按域镜像工具面」的单一判定、补 UTF-8 解码,并收口守卫域其余 9 项
> medium/low(写动词不认授权根、带空格 `-c`/`-m` 误判、`python3.11` 绕过、grep 模式误触 stop-all、
> 判定/哨兵双 cwd 源、双 shim 把「守卫文件缺失」误判为 deny、纪律表共享可变、净网边界缺 `<`/`>`、
> f2 大小写)+ 两处「残留哨兵只挡脚本写」失实文档。验证:13 项各配先红后绿回归 + 既有守卫面全绿。

## Why

2026-10-13 /mgh-init 全流程评审(97 文件)的守卫域发现群(报告存于维护者私有文档区),七批修复
战役的**批次 2**。守卫是三端(claude / opencode / dsh)单一判定源,其缺口意味着全部六条 `mgh-*`
命令的运行时纪律同时失效,故在 fanout/分发/枚举各批之前优先收口。批次 1(resume 状态机)已落地
(VERSION 0.1.68);本批涉及文件经 git diff 核实自评审基线以来零改动,行号与实测结论全部有效。

**H2(高危,实测复现)**——redirect 越树拦截对四域不可达:`_redirect_in_sanctioned` 本是「init/ut-init
受信子树白名单」的查询函数,却被复用在语义相反的调用点上(树外拦截的豁免判断);它对无 allowlist 的
sast/sra/srr/sdr 直接 `return True`(「no-allowlist => OK to proceed」),使 `echo x > D:\out\f` 在四域
经 redirect 规则**放行**。允许集外的目标会被兜底净网(rule m)拦住但报的是读侧 recipe(引导错位);
落点在**声明的只读根内**时(评审实测形态)净网也在允许集内 → 全链路 exit 0,「声明只读根永不可写」
被直接击穿。同根连坐:`_out_of_tree_mutation`(Bash 写动词)不认哨兵 `out_roots`——同一授权写根,
Write/Edit 工具面放行、redirect 放行、Bash 写动词却拦(三入口结论翻转),且 `_emit_bash_write_block`
的 `out_roots` 形参从未被读(死参数,当年想接线没接上的痕迹)。

**H3(高危,实机 A/B)**——stdin 未强制 UTF-8:`json.load(sys.stdin)` 的解码随控制台代码页走,中文
Windows(claude/dsh 面 payload 带 cwd)下 UTF-8 字节被按 cp936 解码 → `cwd` 锚点损坏 → 哨兵向上
发现失败 → `domain is None` → **六域全部规则静默放行整场 run**。三端宿主发的都是 UTF-8 字节,错在
守卫侧解码;`C:\Users\<中文名>\...` 正是中文 Windows 默认布局,触发面是常态而非边角。

**H13(文档失实)**——两处文档宣称「残留哨兵只挡脚本写、不挡 JSON/.md/读」,与实现矛盾:实测
init/ut-init 域哨兵激活时拦截受信子树外**一切写(任何扩展名)**与树外读。失实预期会让维护者误判残留
哨兵无害而不清理——而 init 域残留哨兵等于目标项目日常开发的**全面写锁定**(src 下改行都拦)。批次 1
已在 `resume_state --check` 落了「完成态哨兵残留」违例,本批补文档真相与回归测。

**其余 medium/low(9 项,均经评审二次验证)**:解释器正则的负向前瞻只对无空格粘连形有效(死代码),
`py -m pytest <树外.py>` / `py -c "..." <树外.py>` 的尾随参数被误当执行脚本拦截;`python3.11`/`python3.12`
带点版本号绕过全部 `py -c` 内省与 heredoc 检测(版本段正则不含点);规则 l 把 `grep -n "mgh-core/scripts/
run.py" notes.md` 的引号内**搜索模式**当磁盘引用,触发最重的 stop-all 阻断;路径判定用 `Path.cwd()` 而
哨兵发现用 payload `cwd`(两来源可错根);双 shim(opencode/dsh)把「守卫文件缺失时 python 打不开文件
的退出码 2」误判为 deny(与 fail-soft 契约「文件不在 → PASS」矛盾,评审确认 opencode 面同病);
`get_discipline` 返回共享可变结构(消费方一次 append 即永久污染跨域纪律表);净网正则左边界字符类缺
`<`/`>`(`>D:/out/f` 无空格重定向形态提取不到 token,与 H2 联动时彻底无拦截);f2 叶源码拦截的路径段
比较大小写敏感(`.CLAUDE/Mgh-Core/Scripts` Windows 变体绕过);模块 docstring 规则 (m) 说明段整段
粘贴两遍(编辑事故)。

## What Changes

- **统一写目的地判定(D1,治 H2 + out_roots 三入口翻转)**:新增单一谓词供 Bash 写动词 / redirect /
  `py -c` 写形态三个入口共用——init/ut-init:目的地经 `_allowlist_write_blocked`(受信子树 + AGENTS.md
  + 哨兵 `out_roots`)判定;四域(sast/sra/srr/sdr):越树即拦、树内放行(逐字镜像各自 Write/Edit 工具
  面)。`_redirect_in_sanctioned` 的「无 allowlist 早真」删除;`_emit_bash_write_block` 死参移除。
  **`read_roots` 在任何写面永不豁免**(只读根永不可写)。
- **stdin 强制 UTF-8(H3)**:`json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))` 一行修复;
  补 GBK 管道回归测(TextIOWrapper gbk 包 UTF-8 字节,修复前放行/修复后拦截)。
- **解释器 `-c`/`-m` 排除修真**:token 流中出现 `-c`/`-m`(空格或粘连形态)即非「执行脚本」形态,
  该规则退出(内省/写重标记规则拥有这些 body);负向前瞻死代码删除。
- **带点版本 token 覆盖**:`_PYC_RX` / `_PY_INLINE_RX` 版本段改含点形态,`python3.11 -c` / heredoc
  不再绕过。
- **规则 l 模式操作数豁免**:搜索动词(rg/grep/findstr/find/fd/ag/ack)简单命令的**首个非旗标操作数**
  (即搜索模式)不再是磁盘引用;读动词(cat/type/Get-Content)操作数照判(stop-all 面不缩)。
- **单一 cwd 源**:路径判定的 cwd 与哨兵发现锚统一(payload `cwd` 优先、回退守卫进程 cwd)。
- **双 shim fail-soft 修真**:守卫文件存在性预检(缺失 → fail-soft 放行 + 诊断),python「can't open
  file」的退出码 2 不再误判为 deny;opencode 与 dsh 两面同步。
- **纪律表防御性拷贝**:`get_discipline` 返回深拷贝,消费方不可污染共享表。
- **净网边界补 `<`/`>`**;**f2 路径段比较大小写不敏感**;**docstring 重复段删除**。
- **H13 文档真相**:`orchestrator-discipline.md` 与 `runtime-enforcement.md` 两处按域精确改述残留哨兵
  语义(init/ut-init = 受信子树外全面写锁 + 树外读拦;四域 = 脚本写/越树写/树外读拦,树内非脚本写
  放行),并衔接批次 1 的完成态哨兵残留违例;补回归测断言 init 哨兵激活时受信子树外 `.md`/`.json`
  写被拦。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `runtime-hook-enforcement`: Bash 写动词/redirect 的写目的地判定统一(四域越树拦、init/ut-init 认
  `out_roots`、`read_roots` 永不豁免写面);守卫 stdin 解码强制 UTF-8;判定与哨兵发现单一 cwd 源;
  解释器规则的 `-c`/`-m` 带空格排除;带点版本 token 覆盖;规则 l 搜索模式豁免;净网左边界含 `<`/`>`;
  f2 大小写不敏感;opencode shim 守卫缺失 fail-soft。
- `dsh-host-integration`: dsh pre-execute shim 守卫文件缺失时 fail-soft 放行(退出码 2 ≠ deny 的判定
  前置存在性检查)。
- `resume-step-discipline`: `get_discipline` 返回防御性深拷贝(共享纪律表不可被消费方污染)。

## Impact

- **代码**:`core/scripts/block_adhoc_scripts.py`(判定统一/解码/cwd/正则/规则 l/边界/大小写/docstring)、
  `core/scripts/discipline_core.py`(深拷贝)、`releases/opencode/plugins/block_adhoc_scripts.ts` 与
  `releases/dsh/plugins/mgh-guard.ts`(存在性预检;镜像 install 面 `install_opencode_plugin` /
  `install_dsh_wiring` 分发同步)。
- **文档(分发面)**:`core/prompts/fragments/orchestrator-discipline.md`、`core/contracts/hooks/
  runtime-enforcement.md`(H13 改述)。
- **测试**:`test_block_adhoc_scripts`(13 项先红后绿主战场)、`test_opencode_hook_parity` /
  `test_dsh_hook_parity`(shim 源形态断言)、`test_install_opencode_plugin` / `test_install_dsh`
  (分发镜像)、`test_resume_state` / `test_list_steps`(纪律表污染回归)、`test_zero_deps` /
  `test_no_compile_warnings`。
- **兼容性**:守卫无 CLI 面(`--help` 契约不涉);拦截面**只增不减**(四域 redirect 越树从放行变拦、
  误拦面从拦变放行——`py -m` 尾参/grep 模式两类误拦消除);三端 parity 守卫(canonical 字节一致)
  与接线覆盖 CI 不变量零扰动。
- **战役上下文**:七批次之 2;批次 3(fanout_runner 剩余)起与本批无文件交集。

## 修复战役分批路线图(本 change = 批次 2)

| 批次 | 域 | 状态 |
| --- | --- | --- |
| 1 | resume 状态机 + per-step 加载(CR-1 + H12 + 口径簇) | ✅ 已归档(0.1.68) |
| **2** | **守卫域(H2/H3/H13 + M×7 + L×3,本文档)** | **本 change** |
| 3 | fanout_runner 派发器剩余(忙等/杀树/path-drift 反写/子串匹配/PWD/`_safe_name` 漂移) | 待做 |
| 4 | 分发死链与壳/agent 面(H10/H14/H9 + 待实测 edit:deny + 壳面 M) | 待做 |
| 5 | 枚举/聚合/切片口径(H4/H8 + runner 预算转发 + 枚举器 M 群) | 待做 |
| 6 | discover / expand_scope 扫描韧性(H5/H6/H7 + discover M 群) | 待做 |
| 7 | stage 提示词与契约批量 + 拍板项(H11 `--merge` 出口:实现 vs 拒绝,**需维护者拍板**) | 待做 |
