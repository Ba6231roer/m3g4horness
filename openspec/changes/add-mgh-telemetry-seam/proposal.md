## Why

企业内网部署 `mgh-init` / `mgh-sra` / `mgh-sast` 时,运营方希望有**使用埋点**:谁用过、每次产出了什么(本就是少数几个文档/章节,体量很小),周期性同步到内网某个服务端(服务端可按需加接口,偶尔调用失败即丢弃,要求不严)。但本仓是 GitHub 上的开源项目,**埋点(采集 + 上传)代码不能进 GitHub**。需要一种**尽可能解耦**的实现:开源仓只暴露一个稳定、良性、零网络的「观测缝」,真正的采集与上传由企业内部独立维护、永不 push 的 overlay 包承接。

## What Changes

- **新增确定性叶脚本 `core/scripts/emit_run_summary.py`**(Python 标准库、**零网络**):在每条 `mgh-*` 命令**成功收尾**时由编排器 `Bash` 调用一次,把本次运行的关键产物(路径 + 字节数 + sha256)+ 命令 + 主机 + 用户标识哈希 + 起止时间 + 计数,写成一份**本地** JSON 回执。AST 扫描 + 单测双重证明无 `urllib`/`socket`/`requests` 等任何网络 import。
- **三份命令壳各 +1 行收尾调用**(`releases/{claude-code/commands,opencode/command}/mgh-{init,sra,sast}.md`):成功末步 `py .../emit_run_summary.py`,失败/中断不写。回执**永远只落本地**,不触发任何外发。
- **新增稳定契约 `core/contracts/run-receipt.md`**:定义回执落盘路径(`<project-root>/.mgh-receipts/<cmd>-<ts>-<id>.json`)、schema(版本化 `schema: 1`)、字段清单。这是企业 overlay 唯一依赖的稳定缝——承 R5.3 I/O 契约稳定性。
- **企业 overlay(独立包,在 m3g4horness 仓外实现,不进 GitHub、不分发;如 `C:\DEV\mgh-telemetry-overlay\`)**:一个共享 `flush.py`(标准库 `urllib`,扫 `.mgh-receipts/` 未发回执 → POST,`.sent.json` 去重,失败 swallow、跨运行自愈、**无 cron**)为唯一含网络代码处;两端薄胶水——Claude Code 一条 `PostToolUse` 命令、opencode 一个 `tool.execute.after` 的 `.ts` 插件 shim(已据 opencode 官方文档核实:hooks 即 JS/TS 插件,非命令式 config hook)。配 `config.json`(一行 url + 可选 token);`install_telemetry.py` 幂等落胶水进目标项目;`server/server.py` 内网接收端参考实现。
- **install.sh 自检清单 + 契约 lint 扩展**:把 `emit_run_summary` 加入 `install.sh` 的共定位自检列表;`tools/check_contracts.py` 覆盖命令壳对该脚本的调用 flag。

非目标(明确不做):不在开源仓内实现任何上传/网络/采集逻辑;不向 `core/scripts/` 引入第三方依赖(承 R2);不改变任何命令现有产物路径或现有 I/O 契约。

## Capabilities

### New Capabilities
- `run-receipt-seam`: 在 `mgh-*` 命令成功收尾时,由确定性脚本写一份**本地、零网络、良性**的运行回执到稳定路径与稳定 schema,作为外部(企业内部)观测者唯一依赖的稳定缝。覆盖:每条命令在成功末步经 `emit_run_summary.py` 写回执;回执 schema(回执级:命令/主机/用户哈希/起止/产物路径+大小+sha256/计数);零网络保证(脚本无任何网络 import);opt-in/默认良性(回执纯本地,无回执不影响命令正常产出)。

### Modified Capabilities
<!-- 无。回执缝是横切的新观测能力,其要求在新 capability 内描述并引用「每条 mgh-* 命令」,
     不拆改 control-discovery / security-augmentation / sast-* 现有要求。 -->

## Impact

- **代码**:新增 `core/scripts/emit_run_summary.py` + 单测 `tests/test_emit_run_summary.py`;三份命令壳各 +1 行收尾调用;新增 `core/contracts/run-receipt.md`。
- **安装/契约**:`install.sh` 共定位自检列表 +1;`tools/check_contracts.py` 增覆盖;零依赖 AST 扫描目标扩到新脚本(证明零网络)。
- **研发铁律对齐**:R2(零运行时依赖 / 内网零联网)——开源仓**不增任何网络代码**,离线/内网零联网产品特性不变,上传逻辑完全外置到企业 overlay;R5.3/R5.9(`emit_run_summary.py` 自包含、stdout=JSON/stderr=进度、退出码 0/1/2、幂等、`--check` validator);R5.10(命令壳新增调用为操作性内容,回执 schema 为操作性契约,均非 dev-only provenance)。
- **诚实边界**:开源仓**不提供**任何「谁在用」的统计能力;统计只在企业部署并自行接入 overlay 后才生效。开源使用者若无 overlay,只是本地多一个 `.mgh-receipts/` 目录(可 `.gitignore`)。
