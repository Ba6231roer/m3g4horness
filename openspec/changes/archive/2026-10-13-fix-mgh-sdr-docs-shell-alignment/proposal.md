> **人话序** 现象:2026-10-13 深度评审在文档/壳/契约面确认一组「说的和做的对不上」:① 敏感数据维度声称「目录对象随任务消息下发」,但主路径根本没有搭载通道——六维之一永远拿不到项目敏感目录,且没有任何披露(对银行项目用户是实质弱化);② 契约文档声称 `--dimensions` 收窄会透传到子任务,与三面壳「收窄不下发」的诚实披露直接矛盾;③ dsh 面把 launcher 推荐为首选入口,但 launcher 根本不支持 dsh 宿主;④ opencode agent 定义里有一个运行时永不替换的字面占位符;⑤ 同一条超时规则在三面壳里有三种措辞。另有 launcher 的健壮性缺口:异常退出残留哨兵使守卫常驻后续会话、上游脚本输出错形时崩溃而非逐分支失败;产物内省脚本对畸形输入和中日韩控制台会崩;以及一批死代码。改什么:敏感目录改为「物化文件 + 只读路径下发」(与外部仓结论同构,顺带消除 launcher 侧静默截断);全部披露对齐实现事实;健壮性小修各配最小回归。怎么验证:六维子任务消息可读到敏感目录文件、三面措辞一致、契约与壳无矛盾、畸形输入优雅失败,文档面 lint 与定向回归全绿。

## Why

- 评审(2026-10-13,基线 main HEAD `6e6ac63`)在文档/壳/契约面与杂项工具确认 20 条(6 medium 文档面 + launcher/describe 健壮性 + 卫生类)。核心矛盾是**披露失真**——分发面文档声称的机制与实现事实不一致,会误导编排 agent(按不存在的机制行动)与维护者(按错误的文档理解系统):
  - **M6**:sdr-task.md 声称敏感目录对象「随编排器任务消息下发」,但主路径任务消息只由 fanout_runner 从固定模板 + 固定占位符集构造(无 catalog 槽)——**主路径下 sensitive-data 维度永远拿不到项目敏感目录**,只能依赖基线投影 + 通用掩码预期,且无任何披露(与 `--dimensions` 的明示披露形成对比)。目录落盘在 context.json,但刚性三元组禁止读它。launcher `_build_prompt` 声称「逐字透传」却内嵌目录对象并 4000 字符静默截断(L3)——「逐字」在 launcher 层已不成立。
  - **M18**:`core/contracts/sdr/pipeline.md` 声称 `--dimensions` 收窄「透传」,与三面壳的诚实披露(「收窄当前不下发:不进入评审单元的任务消息」)直接矛盾;L9:三面 agent 定义重复同一失真(声称 note 会收窄维度)。
  - **M15**:dsh SKILL 把 launcher「首选」逐字镜像自 opencode 面,但 launcher `--host` 仅支持 opencode|claude——dsh-only 部署按「首选」走会 fail-loud 早退。
  - **M16/M17**:超时不变式段三面三种措辞(压缩括号注形 vs 完整规范形,非白名单差异);opencode agent 判定纪律含运行时永不替换的 `{{ }}` 字面占位符。
  - **M19/M20**:契约字段清单欠载(pending[]/stdout/manifest 三处);hooks 契约完全遗漏 sdr 域哨兵生命周期(实现已是 arm → co-write → rearm → check 四步),并含「确定性写入器尚未落地」的过时表述(实际已落地两个)。
- launcher/工具健壮性:**L1** 空 try/finally 死代码(异常路径残留 `.active` 哨兵使守卫常驻后续开发会话、无任何提示);**L2** launcher 对 sdr_context stdout 的消费无防护(输出错形 → traceback 而非 per-branch FAILED,且残留哨兵);**M12** describe_artifact `--field` 索引守卫与 int() 语义错配(畸形路径 traceback);**M13** describe_artifact 是全族唯一缺控制台 utf-8 重配置的脚本(中文 Windows 控制台即崩——维护者本机即此环境);**L10** opencode 壳参数表三个 flag 无转发槽位。

## What Changes

- **M6 + L3**:敏感目录下发改为**物化文件 + 路径透传**——sdr_context 把解析后的敏感目录单独物化为 `<run-dir>/sensitive_catalog.json`;任务模板三元组新增该文件**只读路径**(与外部仓结论文件的路径透传同构);launcher `_build_prompt` 不再内嵌目录对象(4000 截断逻辑随之删除,「逐字透传」恢复成立);agent 定义与 launcher 措辞同步。
- **M18 + L9**:契约 `--dimensions` 段改写为与壳披露一致(收窄仅闭集校验 + manifest 记录,不进入任务消息;真正接线后恢复现文);三面 agent 定义删除「note 收窄维度」句。
- **M15**:dsh SKILL 补披露——launcher 仅 spawn opencode/claude 宿主,dsh-only 部署直接走壳内路径(不改 launcher;注意 SKILL token 4994/5000 贴顶,同步精简等量措辞)。
- **M16**:opencode/dsh 超时不变式段对齐 claude 完整规范形(宿主具体数值留在调用占位符)。
- **M17**:三面 agent 判定纪律统一为 claude 精确散文形,opencode 面删除 `{{ }}` 字面形态。
- **M19**:契约三处字段清单补全(pending[] 补 `baseline_path/external_dir/slimmed/chain`;stdout 补 `base/branch/pending_approval[]/baseline_truncated_bytes` 与 `external_repos[]` item 形;manifest counts 补 `findings/excluded_files`)。
- **M20**:hooks 契约补 sdr 域哨兵生命周期段(arm → co-write → rearm → check 四步与各写入器);Authoring 行改「两个确定性写入器」(`read_roots_config --add` 与 `sdr_context --approve-external`)。
- **L10**:opencode 壳参数表 `--max-standalone-bytes/--max-interface-bytes/--include-excluded` 加转发槽位,三面同步(契约 lint 对账)。
- **L1**:launcher 删除空 try/finally 死代码外壳(行为不变;见 design 的哨兵语义辨析)。
- **L2**:launcher 对 sdr_context stdout 消费包 try/except → per-branch FAILED(多分支清单继续后续分支,不 traceback)。
- **M12/M13**:describe_artifact `--field` 索引守卫改 try-int;补与兄弟脚本相同的控制台 utf-8 重配置块;补最小回归(该脚本此前无专属测试)。
- **卫生**:resume_sdr_state 死常量/死参数、sdr_tier probe 失败原因如实区分(不再统一报 "no binary")、launcher 函数内重复 import 清理。
- 版本收口:`CHANGELOG.md` + `VERSION` bump。

## Capabilities

### New Capabilities

<!-- 无。 -->

### Modified Capabilities

- `security-design-review`:MODIFIED「敏感目录复用与默认模板回退(与 sra/srr 的显式分歧)」——透传机制明确为「物化文件 + 只读路径进三元组」(替代不可达的对象内嵌);ADDED「分发面披露与实现事实同步」——壳/agent/契约文档声称的机制 SHALL 与实现一致、未接线机制 SHALL 明示披露(launcher 宿主支持面、超时不变式、占位符、dimensions、字段清单、哨兵生命周期);ADDED「launcher 异常路径卫生与上游产物消费防护」——异常路径哨兵语义、上游 stdout 错形的逐分支失败降级。
- describe_artifact(M12/M13)为纯输入健壮性修复,不改任何 requirement 承诺,以新增最小回归兑现。

## Impact

- **代码**:`core/scripts/mgh_sdr_launch.py`(L1/L2/L3 + 卫生)、`core/scripts/describe_artifact.py`(M12/M13)、`core/scripts/sdr_context.py`(M6 的物化一步)、`core/scripts/resume_sdr_state.py` 与 `core/scripts/sdr_tier.py`(卫生)。
- **分发面文档**(本 change 的主面,三面镜像纪律适用):`core/prompts/fragments/fanout/sdr-task.md`(M6 三元组)、三面命令壳 `mgh-sdr.md`(M16/L10)、三面 agent 定义 `sdr-review-fanout`(M17/L9)、dsh SKILL(M15)、`core/contracts/sdr/pipeline.md`(M18/M19)、`core/contracts/hooks/runtime-enforcement.md`(M20)。改任一面 MUST 同查另两面(R5.1 镜像纪律)。
- **测试**:`tests/test_sdr_context.py`(物化文件)、`tests/test_mgh_sdr_launch.py` 与 `tests/test_sdr_failure_chain.py`(L1/L2)、`tests/test_distributed_md_purity.py`、`tests/test_dsh_command_surface.py`(三面镜像与纯净性)、describe_artifact 新增最小回归;`python tools/check_contracts.py`(L10 槽位对账)、`python tools/check_distributed_prompt_budget.py`(**dsh SKILL 4994/5000 贴顶,改文案后必须跑**)、`python tools/check_plain_language.py`(人类面措辞)。
- **契约**:`sdr-task.md` 三元组新增只读路径一项(任务消息内容变化,fanout_runner 占位符集**零改动**——路径经既有三元组槽位搭载);CLI 面零新增 flag。
- **跨面提示**:改了分发面 md → 发布前跑全量回归(仓库惯例);本 change 与其余四个修复 change 相互独立,但**建议最后执行**(文档对齐以代码事实为准,先落代码面修复可避免披露二次返工)。
- **版本**:`CHANGELOG.md` + `VERSION` bump。
