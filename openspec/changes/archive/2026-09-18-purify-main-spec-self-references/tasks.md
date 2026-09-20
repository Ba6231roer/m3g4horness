> **定位方式**:一律用**文本锚**定位,不要依赖行号 —— 本清单里的行号是清扫前快照,每改一处后续都会偏移。
> **每处的共同验收**:改完那一处后,该句的 `SHALL`/`MUST` 规范内容必须**一字不少**;删掉的只能是过程叙述。

## 1. 基线与范围锁定

- [x] 1.1 记录基线:`grep -rn "本 change\|本变更" openspec/specs/ | wc -l` 应为 **22**;确认覆盖 9 个文件(`orchestration-substrate` 6 / `control-discovery` 5 / `security-augmentation` 3 / `sast-control-intake` 2 / `rules-emission` 2 / `sensitive-catalog` 1 / `sast-orchestration-discipline` 1 / `resume-step-discipline` 1 / `request-context-budget` 1)
- [x] 1.2 确认第 3 类 2 处**本次有意不动**:`security-augmentation`(含 `improve-mgh-init-codegraph-enrichment` 的那段)、`request-context-budget`(含 `harden-mgh-init-context-budget` 的进度段)。记下,供 8.1 作回归断言

## 2. `orchestration-substrate/spec.md`(6 处)

- [x] 2.1 删括注:`**stage 流细节的载体**(自本变更起):` → `**stage 流细节的载体**:`
- [x] 2.2 删括注:`**命名 step id 契约**(自本变更起):` → `**命名 step id 契约**:`
- [x] 2.3 删括注:`**fresh-run bootstrap 可达性**(自本变更起):` → `**fresh-run bootstrap 可达性**:`
- [x] 2.4 删括注:`**壳 token 预算**(自本变更起):` → `**壳 token 预算**:`
- [x] 2.5 删自指句(`本变更 SHALL 使该措辞在两壳顶部消失。`)。该段前半句「两壳顶部编排器声明中的「本仓」措辞 SHALL 改为「目标项目」」是行为契约,**保留**;其后的 lint 守护说明与场景名同样保留。只删这一句
- [x] 2.6 整条删除 requirement「行为保持——既有回归测全绿 + mgh-init 字节级一致」(含其正文与两个场景:`既有回归测与 lint 全绿`、`mgh-init 流水线产物路径未漂移`),并清掉遗留的空行分隔,使前后两条 requirement 间维持标准单空行。依据见 `design.md` D2

## 3. `control-discovery/spec.md`(5 处)

- [x] 3.1 场景 `Existing on-disk artifact schema unchanged`:删 `- **WHEN** 本变更生效后审阅` 中的 `本变更生效后` 四字
- [x] 3.2 场景 `form_clusters untouched by the robustness fix`:同上,删 `本变更生效后`
- [x] 3.3 场景 `Detection introduces no runtime dependency`:`对本变更新增/改动的任何` → `对引入 codegraph 消费的任何`
- [x] 3.4 场景 `No deterministic-script contract change`:删 `本变更生效后`
- [x] 3.5 `每请求有界(本 change 不将其切到 dispatcher)` → `每请求有界(不经 dispatcher)`

## 4. `sast-control-intake/spec.md`(2 处)

- [x] 4.1 `其正文未被本变更修改` → `其正文保持原样`(括注「溯源注释 `Source: vvaharness/...` 保留」原样保留)
- [x] 4.2 `load_controls.py` 及`本变更新增的任何脚本` → `及任何新增脚本`

## 5. `rules-emission/spec.md`(2 处)

- [x] 5.1 `不省上下文,违本变更目标` → `不省上下文,与 lazy 索引块目标相悖`
- [x] 5.2 `(本变更前产物)` → `(旧版产物)`

## 6. `security-augmentation/spec.md`(2 处)

- [x] 6.1 场景 `Detection introduces no runtime dependency`:`对本变更新增/改动的任何` → `对引入 codegraph 消费的任何`(与 3.3 同一改法)
- [x] 6.2 场景 `No deterministic-script contract change`:删 `本变更生效后`
- [x] 6.3 **不在本次**:同一文件中含 `improve-mgh-init-codegraph-enrichment` 的那段保持原样(第 3 类)

## 7. 单点文件(3 处 / 3 文件)

- [x] 7.1 `sensitive-catalog/spec.md` 场景 `mgh-init side unchanged`:删 `本变更生效后`
- [x] 7.2 `sast-orchestration-discipline/spec.md`:`本变更新增脚本 MUST 有回归单测` → `新增脚本 MUST 有回归单测`
- [x] 7.3 `resume-step-discipline/spec.md`:`本变更的静态表成为` → `当前静态表成为`

## 8. 验收

- [x] 8.1 全仓扫描:`grep -rn "本 change\|本变更" openspec/specs/` 结果**应恰好只剩 2 处**,且必须是 1.2 记录的 `security-augmentation` 与 `request-context-budget` 那两处。多一处或少一处都算未达标
- [x] 8.2 归档面未被改写:`grep -rn "本 change\|本变更" openspec/changes/archive/ | wc -l` 与清扫前**相同**(该目录本次零改动)
- [x] 8.3 `py openspec validate --specs --strict` → 22 项全过,0 失败
- [x] 8.4 逐处语义等价核对:对照 1.1 的基线逐条走一遍 2.x–7.x,确认每一处删掉的都是过程叙述或括注、留下的句子规范含义未变;特别复核 2.5(只删一句,前半句契约在)与 2.6(整条删除,内容确由 `AGENTS.md` 常设承载)
- [x] 8.5 分发面未受影响:确认 `core/**`、`releases/**`、`tools/**`、`tests/**` 本次零改动(`git status` 核验)
