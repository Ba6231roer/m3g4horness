## Context

现状与约束(动机见 proposal「Why」;前两个前置 change——插件 2.x 迁移、权限询问闸门——已归
档):

- 子进程派发器 `core/scripts/fanout_runner.py`(3860 行)已具备全部可复用资产,且带
  `if __name__ == "__main__"` 守卫、可被兄弟导入而不触发主流程:`TIERS` 表(六 tier 的枚举
  器/转发 flag/模板/占位符/路径锚字段/agent 名)、`_list_pending`(枚举器调用与 run 目录锚
  定)、`_load_template`/`_fill_template`(模板逐字填充,填后断言无残留 `{{`)、
  `_anchor_check`(路径锚树)、`_safe_name`(安全文件名)、`_quota_admission`(配额纯函数)、
  `DEFAULT_WAVE`。执行期它把填好的任务消息写审计副本到 `<inputs-dir>/<unit>.task.md`。
- 项目级配置先例:`read_roots_config.py` 管 `<项目>/.mgh/read-roots.json`(v 字段 + 缺文件
  零变化 + 坏文件 fail-closed)——环境画像沿用同一形态与目录。
- 本 change 是原生派发路线的第 3 个(共 8 个):它只产「计划工件 + 环境画像」,不接入任何
  命令壳(sdr 接入是第 5 个),不做看门狗(第 4 个),不做插件派发工具(第 6 个)。
- 约束:R2 零依赖;R5.3 叶脚本形态(`--help` 即契约、stdout 单行 JSON、退出码 0/1/2);
  R5.10 分发纯净(新脚本是分发面);`fanout_runner.py` 是稳定性契约产品,本 change 对其
  **零改动**。

## Goals / Non-Goals

**Goals:**

- 原生派发的单元输入构造与子进程形态零漂移(同一模板引擎、同一锚树、同一枚举来源)。
- 计划工件可对账:同输入逐字节可重复,`--check` 能捕获 stale/篡改。
- 短号把「弱模型转述长路径」的错抄面收敛为「4 字符防撞短号」。
- 环境画像缺省零变化、坏文件 fail-closed,为后续 change 提供单源配置面。
- `fanout_runner.py` 行为零变化(由「零改动」构造保证)。

**Non-Goals:**

- 不接入任何命令壳/步骤清单/resume 指引(消费者是后续 change)。
- 不做运行期节流(配额滑窗、冷却、风暴截断仍属派发/看门狗层;本 change 只做**静态波次尺
  寸**算术)。
- 不定义 `auto` 在「原生消费者存在后」的细化规则(如按 special-auth 在场切 native)——缺省
  解析钉死为现状,演进另立 change。
- 不做 claude/dsh 面。

## Decisions

### D1 独立薄入口,不给派发器加 flag

- **决策**:新增 `core/scripts/emit_native_plan.py`,以兄弟导入(`sys.path.insert(0,
  dir-of-__file__)`,R5.3a)复用 fanout_runner 的模块级函数;**不**给 `fanout_runner.py`
  加 `--emit-native-plan` flag。
- **理由**:派发器是 3860 行、51 个测试类守着的稳定性契约面(R5.3/R5.5);加新模式扩大其
  `--help` 契约面并触碰久经实战的主流程。「runner 行为零变化」用「源码零改动」来构造保证,
  比加 flag 后回归证明更硬。新入口独立获得自己的 `--help` 契约与测试面。
- **备选否决**:`fanout_runner.py --emit-native-plan`(计划文档允许的另一形态)——被否,理
  由如上;复制模板引擎到新脚本——被否,两份实现必然漂移,违背「单元输入构造零漂移」目标。

### D2 计划工件形态:无时间戳、稳定排序、三方映射

- **决策**:`<run>/native_plan.json` 顶层 `{v, tier, agent, repo, wave_size, wave_size_source,
  units_total, waves[]}`;`waves[]` 内每单元 `{id(短号), unit_id(规范 id), task_file,
  checkpoint_path, done_marker, …路径全绝对}`(路径字段集与该 tier 枚举器输出对齐,逐字透
  传)。**不含任何时间戳**;单元按规范 id 排序后切波;JSON 序列化固定
  `ensure_ascii=False, indent=2, sort_keys` + 换行结尾。
- **理由**:逐字节可重复是「计划=纯函数产物」的前提,也让 `--check` 的重物化比对最简单
  (无「除时间戳外一致」的豁免面)。task 文件沿用 `<inputs-dir>/<unit>.task.md` 与审计副本
  同路径——子进程形态若在计划产出后运行,重写同内容文件,幂等无害。
- **备选否决**:计划带 `generated_at`——被否(破坏逐字节比对,且无消费方需要它;run 目录
  名本身已含时间戳)。

### D3 短号:`<tier>-<4 字符>` 哈希派生 + 确定性加盐防撞

- **决策**:候选 = `sha1(规范单元 id)` 的 base32 小写取 4 字符(字符集去除 `0/o/1/i/l` 等
  易混字符);对全单元集做两两编辑距离校验,冲突者按 `sha1(unit_id + ":" + salt)`(salt =
  1,2,3…)确定性重派生直至全集满足距离 ≥2;前缀用 tier 名(`sdr-`/`scout-`/`t1-`…)。
- **理由**:派生自规范 id(而非序号)保证 pending 集变化后同单元同号——断点续跑与跨会话引
  用不漂;4 字符去混字符集有 27^4≈53 万空间,单元数 ≤ 数千时冲突率低、加盐轮次浅;编辑距
  离 ≥2 把「错抄一个字符命中另一合法单元」从概率问题变为结构不可能。前缀带 tier 让人/模型
  在日志里一眼分辨单元归属。
- **备选否决**:纯序号(`u17`)——被否(pending 集变化即漂移,跨波次引用歧义);更长短号
  (6–8 字符)——被否(错抄面本来就由防撞不变量收口,更长只增加转述 token)。

### D4 环境画像:独立小模块,缺省=现状、fail-closed 于坏文件

- **决策**:新增 `core/scripts/env_profile.py`(约百行,模块导入 + CLI 双形态,先例
  read-roots 配置脚本):`load(target) -> Profile`(导入形态,坏文件抛类型化异常)与
  `--check`(CLI 形态,退出码 2 + recipe)。缺文件 → 全缺省(`dispatch_mode:"auto"` → 解析
  为现状派发形态;`native_concurrency` 缺省 3;`quota` 三键整体可选)。
- **理由**:画像将有多个消费者(后续的壳/步骤清单/看门狗/插件工具),独立模块避免每个消费
  者各写一份解析;「auto 缺省 = 现状」把本 change 的行为影响压到零;fail-closed(而非静默
  回退)让「以为配了 native 实际跑 runner」的错配在启动期就炸出来。
- **备选否决**:把画像塞进 emit 脚本的 flag——被否(消费者不止它);画像进 run_config
  (per-run)——被否(画像是项目/机器级偏好,不是单次运行意图;run_config 已有既定边界)。

### D5 波次尺寸:静态算术,不做运行期节流

- **决策**:`wave_size = min(native_concurrency 或 CLI 覆盖值, 配额每窗口可派单元数)`;
  配额项缺省不参与;配额每窗口可派单元数 = `max(1, floor(quota.calls /
  quota.calls_per_unit))`(复用派发器估算口径 K 的同一算术,静态化)。波次按排序后顺序切
  分,`wave_size_source` 字段记录取小者来源(`concurrency|quota`)。
- **理由**:计划只定**形状**;运行期配额滑窗/冷却/等窗是看门狗与派发纪律的职责(后续
  change),静态算术与它们不冲突。来源字段让人一眼看出「为什么波次这么小」。
- **备选否决**:计划内嵌时间戳化的滑窗预算——被否(破坏确定性,且运行期重算更准)。

### D6 `--check` = 零修复的重物化比对

- **决策**:`--check` 在内存中按当前磁盘状态重算计划,与磁盘工件逐字节比对;任何差异(单
  元集前进、文件被改、环境不一致)退出码 2 + 差异清单 + 「重物化即修复」recipe;不做任何
  自动修复。
- **理由**:计划是纯函数产物,重算即权威;「自动修复」会掩盖「为什么磁盘状态与计划不符」
  这一线索(可能是篡改、可能是双跑)。stale 计划(部分单元已完成)如实报过时——消费方
  (后续壳)的纪律本来就是每波前重物化/重查询。
- **备选否决**:`--check` 只验 schema 不比对内容——被否(捕获不了 stale/篡改,自检价值减半)。

## Risks / Trade-offs

- [fanout_runner 内部函数签名变化(未来 change 改它)导致薄入口断] → 薄入口只依赖少数稳
  定函数并在其测试里锚定调用面;派发器自身的改动面测试映射(test_fanout_runner)本就要跑,
  断裂会在 CI 显形。
- [短号与既有单元文件名编码(`_safe_name`)混淆] → 计划里短号与规范 id、文件路径三方映射
  同时在场;短号只用于「模型转述与人对账」,永不参与文件系统路径构造(路径永远来自枚举器
  透传)。
- [枚举器输出字段漂移导致计划字段不全] → 计划字段集对齐枚举器 stdout 契约并以快照测试锚
  住;tier 新增时(如未来通道 B)按同契约扩展。
- [`auto` 缺省语义被未来 change 悄悄改] → 本规格把「缺省解析 = 现状」钉死为 requirement;
  任何细化(按 special-auth 切 native)都必须走 spec 修改,不可实现层暗改。
- [两个新脚本进入分发面带来的纯净/契约负担] → 任务里含 check_contracts(--help 面)、
  purity、zero_deps 闸门;脚本不携带任何研发语境词。

## Migration Plan

1. 实现两脚本 + 测试(先红后绿);本机对 sdr tier 真仓跑 `--emit` + `--check`(零模型调
   用、零 token 成本)。
2. 合入后随 install 分发;无任何既有行为迁移(缺省零变化),无需回滚数据。
3. 回滚:删两脚本与测试即可;`fanout_runner.py` 未被触碰。

## Open Questions

- 计划 JSON 是否需要为通道 B(插件派发工具,第 6 个 change)预留扩展字段(如 per-unit 的
  agent 覆盖)——留到该 change 按「加可选字段、旧计划仍过 --check」的兼容原则处理,本
  change 不预铺。
