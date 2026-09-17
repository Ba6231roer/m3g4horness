# 缺陷分析:mgh-init T1 归纳记录 schema 漂移导致 scout 簇被 T2 静默丢弃

> 分析文档,供「分析与设计修复」任务消费。本文只做**根因 / 影响 / 证据 / 候选方向**,不给实现。
> 日期:2026-08-07 · 触发场景:`fix-mgh-init-scout-stranding` 已安装后,scout 候选仍不进 inventory
> 关联:[`review-mgh-init-scout-stranding.md`](review-mgh-init-scout-stranding.md)(D1–D4,本文为 D5,与之正交)

## TL;DR

scout 候选经 fold-in → clusters → T1 归纳**全部落地**后,仍不进 `controls_inventory.json`。根因:
T1 归纳记录(`checkpoints/t1/*.json`)**schema 漂移**——部分子代理(本轮即 scout 簇)产出**嵌套 `controls[]`**
结构,违反 init-induct 契约的**根级 `evidence[]` / `entry_points[]` / `confidence`** 形状
(`init-induct.md:36-47`)。T2 synthesis 只消费契约形状记录,读到嵌套结构记录**静默丢弃** →
scout 类别(含 `authorization`)从 inventory 消失,管线却报 step=done。

## 一、现象与已确认事实(磁盘真相)

| 项                            | 值                                                                           |
| ---------------------------- | --------------------------------------------------------------------------- |
| scout 候选 / clusters / T1     | 全部落地(`controls_candidates.json` 11 类、`clusters.json` 11 类、t1 22/22)         |
| T2                           | 重跑、校验通过(`checkpoints/t2` 仅 `.done`,无 `.failed`)、`init_manifest.json` 写入     |
| inventory                    | 仍仅 input-validation + data-masking                                          |
| input-validation 记录(regex 簇) | 根级 `evidence[]` / `entry_points[]` / 单个 `confidence`(**符合契约**)              |
| authorization 记录(scout 簇)    | 嵌套 `controls[n].evidence` / `anchor_file` / `confidence`(**违反契约**)          |
| 契约形状                         | `init-induct.md:36-47`:根级 evidence/entry_points/confidence,evidence ≥1 真实锚点 |

## 二、根因

- init-induct 输出形状**仅由提示词约束**(`init-induct.md:36-47`),**无确定性校验**——对比 T2 产物有
  `validate_inventory.py`(R5.9 边界检查),T1 记录没有对等 validator。
- LLM 子代理输出漂移 → 部分簇(本轮为 scout 簇,在 resume 中由不同 LLM 会话归纳)记录形状违反契约
  (嵌套 `controls[]` 而非根级字段)。
- T2 synthesis 按契约字段提取(`init-synthesis.md`),读到嵌套结构提取不到 → **静默丢弃**,不报错、
  不进 manifest、不产生 `.failed`。

## 三、为何丢得不留痕

- T1 记录无 validator:违反契约的记录通过 T1 边界,fail-loud 不存在。
- T2 丢弃是 LLM 行为,不产生 `.failed`;`validate_inventory` 只验 T2 产物,而 T2 产物只剩 2 个规范类 →
  校验通过。
- 结果:step=done、manifest 写入,看起来「完整成功」,实际 scout 层数据归零。

## 四、严重度

**高。** scout 层(scout 413 批 LLM 读取 + fold-in + T1 归纳的全部成果)在最终 inventory **静默归零**。
且与 D1–D4(`fix-mgh-init-scout-stranding`)正交:**D1–D4 全修后,此缺陷仍会让 scout 进不了 inventory**——
这就是该 fix 装完后 authz 依旧缺失的直接原因。

## 五、触发条件

scout 簇在 resume 中由 init-induct 子代理归纳时输出漂移(与 regex 簇首次归纳同提示词、不同 LLM 会话)。
LLM 非确定性 → 漂移是随机事件,re-run 可能复现也可能不复现。

## 六、候选修复方向(留给设计任务,不展开)

1. **T1 记录形状确定性 validator**(类比 `validate_inventory`):init-induct 产物 MUST 含根级
   `evidence`(≥1 真实 `file:line` / `class:method` 锚点)/ `entry_points` / `confidence`,
   违反 → fail-loud 或自动归一。
2. 或 **T2 容错**:synthesis 对嵌套/发散 schema 归一化读取(而非契约字段直取)。
3. 或 **T1 产物确定性归一**:统一经确定性脚本把 LLM 产物归一到契约形状,不再信任 LLM 输出形状。

## 七、可复现证据

- `rg -l "controls\[" <target>/.mgh-init/checkpoints/t1/*.json` 列出嵌套结构记录(契约形状记录无 `controls[`)。
- 对比 authorization 记录(嵌套 `controls[]`)vs input-validation 记录(根级 evidence/entry_points/confidence)。
- `resume_state.py` step=done、t2 无 `.failed`、inventory 仅 2 类、`init_manifest.json` 无相关 failures 披露。

## 八、相关文件索引

| 角色                   | 文件                                                      |
| -------------------- | ------------------------------------------------------- |
| T1 记录契约形状            | `core/prompts/stages/init-induct.md:36-47`              |
| T1 记录 validator(缺失)  | `core/scripts/` 无对应检查(对照 `validate_inventory.py` 之于 T2) |
| T2 消费契约形状            | `core/prompts/stages/init-synthesis.md`                 |
| T2 产物 validator(对照)  | `core/scripts/validate_inventory.py`                    |
| 记录命名(次要:只替换不截断,超长风险) | `core/scripts/list_clusters.py::_safe_name`             |

## 九、与既有缺陷的关系

| 缺陷 | 归属 | 状态 |
|---|---|---|
| D1 tier 顺序无确定性闸门 | `review-mgh-init-scout-stranding.md` | fix-mgh-init-scout-stranding 已修 |
| D2 下游 marker 无级联失效 | 同上 | 已修(`--invalidate-stale`;merge_scout 级联未落地,doc/impl 缺口) |
| D3 scout 类别漂移 | 同上 | 已修(merge_scout 归一;已并入候选不受益,需回退重 fold) |
| D4 scout 贡献一致性 | 同上 | 已修(`--check`) |
| **D5 T1 记录 schema 漂移** | **本文** | **未修——本文任务** |
| **D6 T1 记录写出带 UTF-8 BOM** | **本文(§十)** | **未修——本文任务** |
| **D7 R5.2 hook 激活侧漏网** | **本文(§十一)** | **未修——本文任务** |

## 十、D6 — T1 归纳记录写出带 UTF-8 BOM(事故链诱因)

> 触发场景:用户在 resume 会话里为修 BOM 让 LLM 跑了一条「原地截断+读」one-liner,
> `open(p,'w').write(open(p,...).read())` 同表达式先截空再读 → 25 个 t1 checkpoint JSON 一次性归零;
> 后续 `regen_ckpts.py` 从 input 数据重建了最小记录,丢失 subagent 证据分析,access-control 类随之丢失。

**本节只记录 mgh-init 侧可归因的真缺陷;one-liner 本身的 bug 与 `regen_ckpts.py` 的数据损失属
操作侧(R5.2 黑盒纪律范畴,见下「不在本文修复范围」),不记为产品缺陷。**

### D6 现象与归因

- **T1 子代理(`init-induct`)写出的 `checkpoints/t1/*.json` 带 UTF-8 BOM**(EF BB BF 头)。
- BOM 对 JSON 不规范(RFC 8259:JSON 文本 SHALL 为 UTF-8 **无** BOM);Python `json.loads` 与 `rg` 能容忍,
  但:① 触发下游/人工「修 BOM」动作(本轮事故的直接诱因);② 某些严格 JSON 消费者拒收。
- 对照:`write_runconfig.py` 的 `_atomic_write_json`(`.tmp`+`os.replace`)及其它确定性脚本写 JSON 均
  **无 BOM**;T1 记录是 **LLM 子代理**用 `Write` 工具产出,形状未受确定性脚本的写出纪律约束 → BOM 漂入。

### D6 根因

- T1 记录(及任意 LLM 子代理产物 JSON)的**写出编码无确定性约束**:子代理 `Write` 工具是否加 BOM 取决于
  宿主/会话,非契约。与 D5 同源——都是「LLM 子代理产物形状仅靠提示词、无确定性兜底」。

### D6 影响

- BOM 本身不丢数据,但作为**诱因**引发了破坏性「修 BOM」操作(本轮)。
- 更普遍:任何严格 JSON 消费方(含未来确定性脚本若用 `json.loads(strict)`/外部工具)可能拒收带 BOM 记录,
  造成与 D5 同形的「记录在盘、下游静默吃不下」。

### D6 候选修复方向(留给设计任务)

1. **T1 记录写出走确定性归一**(与 D5 修复⑥合并):LLM 子代理产出后,经确定性脚本校验 + 重写为
   **UTF-8 无 BOM** 的契约形状(一处同时解 D5+D6)。
2. 或 **init-induct 提示词显式要求无 BOM 写出** + validator 断言首字节非 `EF`(弱约束,同 D5 提示词路线,
   不推荐作唯一手段)。

### D6 证据

- 受影响记录文件首三字节为 `EF BB BF`(`xxd`/`Format-Hex` 可验);`json.loads` 可解析、
  `json.loads(..., strict=False)` 行为不变但 BOM 仍在。
- 对照 `write_runconfig.py` 产物无 BOM。

### 不在本文修复范围(操作侧,记录备查)

- **R5.2 黑盒纪律 → 已坐实为 D7**(见 §十一):该 one-liner 在 mgh-init resume 运行域内由 LLM 自发执行,
  本应被 `block_adhoc_scripts.py` 阻断却未被拦 → R5.2 hook 激活侧漏网,是真缺陷。
- **`regen_ckpts.py`**:非 mgh-init 分发脚本(未在 `core/scripts/`),为事故恢复手工产物,其重建逻辑不
  纳入本文。

## 十一、D7 — R5.2 运行时 hook 激活侧漏网(`py -c` 内省 one-liner 未被阻断)

> 触发场景(用户复盘确认):用户手改 `access-control__*.json` → `resume_state.py --invalidate-stale` →
> 新 session `/mgh-init --resume`。**resume session 内 LLM 自发执行**了「修 BOM」one-liner:
> `[open(p,'w',encoding='utf-8').write(open(p,encoding='utf-8-sig').read()) for p in pathlib.Path('.mgh-init/checkpoints/t1').glob('*.json')]`
> (同表达式先截断后读 → 25 个 t1 checkpoint JSON 归零)。该 one-liner **未被 `block_adhoc_scripts.py` 拦截**。

### D7 现象

- 一条教科书式「一次性微脚本内省 + 重派」(`py -c` + `open(` + `.json` + `pathlib.glob`),在 mgh-init
  resume 运行域内执行,`block_adhoc_scripts.py` 守卫**未阻断**(未 exit 2)。
- 这是 R5.2/R5.7 存在的核心目的——「能用 hook 做确定性闭环的,不写进 MD 靠 agent 自觉」——它失败了。

### D7 根因(opencode shim 绑定层 fail-soft,非激活时序、非检测逻辑)

**激活与检测条件全部满足(用户会话日志确认),Python 守卫(单一决策源)无责:**

- **激活满足**:resume step 0 `export MGH_INIT_ACTIVE=1`(env set);磁盘哨兵 `<target>/.mgh-init/.active`
  **已写入且四 key 完整**(`domain`/`target`/`out_roots[]`/`v`)→ `_read_sentinel`(`:169`)**容忍**解析、
  判 dict 通过 → `_resolve_domain`(`:189`)**应**返回 domain=mgh-init。激活非"休眠"。
- **检测满足**:one-liner 命中 `_PYC_RX`(`:67`,`py -c`)+ `_INTRO_TOKENS`(`:71`,`open(`/`.json`)
  → `_is_introspect_py_c` **应** True → 守卫**应** exit 2。检测无漏判。

**因此失效在 opencode `.ts` shim(`releases/opencode/plugins/block_adhoc_scripts.ts`)的绑定/加载,
任一命中即 fail-soft 放行(只有精确 `code===2` 才 throw 阻断,`:81-84`):**

1. **tool id 不匹配**(`:28,79`):`HANDLED={"bash","write","edit"}`,`if (!HANDLED.has(input.tool)) return`。
   若 opencode 实际 shell 工具 id ≠ `"bash"`(如 `shell`/`exec`/`task`)→ 所有 shell 命令早退放行,one-liner
   未进守卫。**头号嫌疑。**
2. **参数绑定错位**(`:36,80`):`normalize` 读 `output.args.command`;若 opencode `tool.execute.before`
   事件参数不在 `output.args` → `command` 变 `""` → `_PYC_RX` 不匹配 → 放行。
3. **cwd 不对**(`:55` `cwd: process.cwd()`):若插件进程 cwd ≠ `<target>` → 守卫 `_resolve_domain`
   找不到 `<cwd>/.mgh-init/.active` → domain=None → 休眠放行。
4. **插件未加载**(`:75` 导出形状):若与 opencode 插件接口不符 → shim 死代码,`tool.execute.before` 从不触发。
5. **fail-soft 默认放行**(`:69,72,85`):spawn 失败/非 2/诊断全 pass;胶水任何不完美 → 静默 allow。

> R5.7「opencode 移植缺口非能力缺口」在本事故**确实 manifested**:双端字节级 parity 守卫(Python)
> 正确,但 opencode 侧胶水绑定失效 + fail-soft 放行 = 确定性闭环在 opencode 上**实际不闭合**。

### D7 影响

- 一次性破坏全部 t1 checkpoint(本轮 25 个 JSON 归零),且无回滚;后续 `regen_ckpts.py` 重建丢失
  subagent 证据分析 → access-control 类最终丢失。
- 更普遍:R5.2 在 opencode resume 路径上存在**激活可靠性窗口**,任何 LLM 自发的 `py -c` 内省/微脚本
  在该窗口内不被拦——违背 R5.2 的确定性闭环承诺。

### D7 待确认(opencode 运行时取证,非 Python 源码可定)

激活与检测已确认满足(哨兵四 key 完整 + env set + 检测命中),故待确认全部转向 **opencode shim 运行时**:

- **插件是否加载**:opencode 是否实际注册/运行 `block_adhoc_scripts.ts`(`.opencode/plugins/` 注入是否生效、
  导出形状是否匹配当前 opencode 插件接口)。**头号待查。**
- **shell 工具真实 id**:opencode 执行 `py -c` 走的工具 id 是不是 `"bash"`(命中 `HANDLED`)?
- **`tool.execute.before` 事件形状**:参数是否在 `output.args`、命令字段是否 `command`?
- **插件 cwd**:`process.cwd()`(`:55`)是否 = `<target>`(哨兵能否解析)?
- **定位途径**:opencode 运行时日志 / 插件 debug 输出(**非** resume transcript——transcript 只看得到 Bash
  调用,看不到插件 fire 与否);由修复任务在 opencode 侧复现 + 插桩。

### D7 候选修复方向(留给设计任务,shim 层)

1. **校准 shim 的工具 id + 事件形状**:核对 opencode 当前版本 shell 工具真实 id 与 `tool.execute.before`
   参数路径,修正 `HANDLED` / `normalize`(`:28,36`);加回归测(对标 `tests/test_opencode_hook_parity.py`)。
2. **插件加载校验**:确认导出形状匹配 opencode 插件接口;install 自检断言插件被注册、能 fire。
3. **cwd 鲁棒**:shim 显式把 `<target>`(经哨兵/run_config)传给守卫,不依赖 `process.cwd()`。
4. **重新审视 fail-soft**:守卫不可达 / 绑定失效时 fail-soft-pass(当前,`:69,72,85`)vs fail-closed 的权衡
   ——当前 pass 为不破坏 session,代价是 enforcement 静默消失(本事故 = 25 个 t1 记录归零)。
5. (与 D6 合)消除诱因:T1 记录无 BOM → 无「修 BOM」动机 → 不触发本类 LLM 自发脚本。

### D7 证据

- `block_adhoc_scripts.py:67,71,144-148`(检测逻辑,命中该命令);`:189-195`(激活 = env 或哨兵)。
- R5.7 段 B(opencode 插件不继承 mid-session env → 哨兵为可靠激活路径)。
- 用户复盘:one-liner 在 `/mgh-init --resume` session 内由 LLM 自发执行,未被阻断。
