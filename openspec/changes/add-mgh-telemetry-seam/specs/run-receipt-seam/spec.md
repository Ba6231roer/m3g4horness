# run-receipt-seam Specification

## Purpose

为 `mgh-init` / `mgh-sra` / `mgh-sast` 提供**企业内网使用埋点**的解耦观测缝:每条命令在成功收尾时,
由确定性脚本把本次运行的关键产物写成本地、零网络、良性的「运行回执」到稳定路径与版本化 schema。
开源仓**只**暴露这一稳定缝(回执 + schema);任何采集/上传/网络逻辑由企业内部独立维护、不经
`install.sh` 分发的 overlay 承接。回执也可兼作审计/resume 辅助。设计目标承 R2(零运行时依赖 /
内网零联网——开源仓不增任何网络代码)与 R5.3/R5.9(确定性脚本稳定性 + boundary validator)。

## ADDED Requirements

### Requirement: 每条 mgh-* 命令在成功收尾写一份本地运行回执

`mgh-init` / `mgh-sra` / `mgh-sast` 的命令壳 SHALL 在命令**成功收尾**的最后一步,经 `Bash` 调用
`emit_run_summary.py` 一次,把本次关键产物落成一份本地 JSON 回执。失败/中断 SHALL 默认不写回执
(编排器可选地以 `--status failed` 记失败用法)。回执写出失败 SHALL NOT 阻断或改变命令的正常产出。

#### Scenario: 成功运行写出一份回执
- **WHEN** 对目标项目成功跑完 `/mgh-sast`(产出 `security-scan/report.sarif` 等)
- **THEN** 命令末步调用 `emit_run_summary.py`,在 `<project-root>/.mgh-receipts/` 下生成一份回执 JSON,内含 `cmd: "mgh-sast"` 与本次关键产物条目

#### Scenario: 回执写出失败不影响命令产出
- **WHEN** `emit_run_summary.py` 因只读磁盘/权限等未能写出回执
- **THEN** 命令的主体产物(report.sarif / controls_inventory.json / business_context.json 等) SHALL 仍然完整存在,命令视为成功

#### Scenario: 失败/中断默认不写回执
- **WHEN** 命令在收尾前失败或被中断
- **THEN** 默认不在 `.mgh-receipts/` 生成 `status: ok` 回执(除非编排器显式以 `--status failed` 记录)

### Requirement: 回执 payload 遵循稳定 schema(回执级、无正文)

回执 SHALL 为 JSON 且含字段:`schema`(整数,初值 `1`)、`cmd`、`host`、`user_sha`、`started`、
`ended`、`status`、`artifacts`(数组,每项 `{path, kind, bytes, sha256}`)、`counts`(对象,键值对计数)。
回执 SHALL NOT 含任何文件**正文/内容片段**(仅路径 + 字节数 + sha256)。schema 变更 SHALL 递增
`schema` 版本号。schema 字段定义 SHALL 落在 `core/contracts/run-receipt.md` 作为稳定契约。

#### Scenario: 回执字段完备且无正文
- **WHEN** `emit_run_summary.py` 对一次成功 init 运行写出回执
- **THEN** 该 JSON 含 `schema/cmd/host/user_sha/started/ended/status/artifacts/counts` 全部字段;`artifacts[]` 每项仅含 `path/kind/bytes/sha256`,无任何文件正文

#### Scenario: 产物条目带大小与 sha256
- **WHEN** 回执记录一个产物 `controls_inventory.json`
- **THEN** 该条目的 `bytes` 等于文件实际字节数,`sha256` 等于该文件内容的 sha256 十六进制摘要

#### Scenario: schema 版本化
- **WHEN** 回执 schema 发生不兼容变更
- **THEN** `schema` 字段值 SHALL 相对前一版本递增,且 `core/contracts/run-receipt.md` 同步更新

### Requirement: 回执产出者为零网络确定性脚本

`emit_run_summary.py` SHALL 仅用 Python ≥3.10 标准库,且 SHALL NOT import 任何网络模块
(`urllib`、`http`、`socket`、`ssl`、`requests` 等)。该约束 SHALL 由 AST 扫描与单测双重强制。
回执产出 SHALL 只读写本地文件系统,绝不发起任何网络调用。

#### Scenario: 脚本无网络 import
- **WHEN** 对 `core/scripts/emit_run_summary.py` 跑零依赖 AST 扫描
- **THEN** 扫描通过,不出现任何网络模块的 import

#### Scenario: 脚本运行期不发网络调用
- **WHEN** 在断网/内网零联网环境跑 `emit_run_summary.py`
- **THEN** 回执正常写出,全程无网络调用、无网络异常

### Requirement: 回执缝是外部观测者唯一依赖的稳定契约

回执 SHALL 一律落盘到统一稳定路径 `<project-root>/.mgh-receipts/<cmd>-<iso-ts>-<shortid>.json`
(绝对路径,`project-root` 由编排器经 `--target` 显式传入)。该目录与版本化 schema 构成**唯一**
供外部(企业 overlay)观测的稳定缝;外部观测者 SHALL NOT 依赖任何命令内部产物路径或运行态环境变量
之外的不稳定细节。schema SHALL 容许外部消费者忽略未知字段(向前兼容)。

#### Scenario: 回执路径统一且稳定
- **WHEN** init / sra / sast 任一命令成功收尾写回执
- **THEN** 回执文件名形如 `<cmd>-<iso-ts>-<shortid>.json`,统一位于 `<project-root>/.mgh-receipts/`

#### Scenario: 外部观测者只依赖缝
- **WHEN** 企业 overlay 采集使用情况
- **THEN** overlay 仅扫描 `.mgh-receipts/*.json` 并按 schema 解析;不读取 `.mgh-init/`/`security-scan/`/`.mgh-sra/` 等命令内部产物目录,不依赖运行态 env

### Requirement: 回执写出默认开启且可 opt-out,绝不外发

回执写出 SHALL 默认开启(纯本地、零网络,无负担)。环境变量 `MGH_NO_RECEIPT=1` SHALL 作为
opt-out,置位时命令 SHALL NOT 写回执。回执 SHALL 永远只落本地;开源仓内的命令 SHALL NOT
将回执内容发送到任何远端。

#### Scenario: 默认写出回执
- **WHEN** 成功运行命令且未设 `MGH_NO_RECEIPT`
- **THEN** `.mgh-receipts/` 下生成对应回执

#### Scenario: opt-out 关闭回执
- **WHEN** 置 `MGH_NO_RECEIPT=1` 后成功运行命令
- **THEN** 不生成任何回执,命令其余行为不变

#### Scenario: 开源仓不外发
- **WHEN** 仅使用开源仓(无企业 overlay)成功运行任一命令
- **THEN** 全程不发生任何网络外发;回执只存在于本地 `.mgh-receipts/`
