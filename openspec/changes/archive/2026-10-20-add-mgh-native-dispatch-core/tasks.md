## 1. 环境画像脚本(core/scripts/env_profile.py)

- [x] 1.1 实现 `load(target) -> Profile`(导入形态,坏文件抛类型化异常)与 CLI 双形态
  (`--check` 零副作用校验;`--help` 即契约;stdout 单行 JSON;退出码 0/1/2);schema 按
  spec:`{v:1, dispatch_mode: auto|runner|native, native_concurrency: 1..5, quota{calls,
  window_s, calls_per_unit}}`,全键可选、未知字段忽略;验证:`--help` 输出含全部 flag 与
  取值域
- [x] 1.2 缺省与 fail-closed 语义:缺文件/缺目录 → 全缺省(auto→现状、并发 3、无配额);
  坏 JSON/未知 v/枚举域外/并发超范围 → CLI 退出码 2 + recipe(文件路径+违规字段)、导入抛
  类型化异常;验证:红测先锚「坏文件静默回退」为非法形态

## 2. 计划物化脚本(core/scripts/emit_native_plan.py)

- [x] 2.1 薄入口骨架:兄弟导入 fanout_runner(`TIERS`/`_list_pending`/`_load_template`/
  `_fill_template`/`_anchor_check`/`_safe_name`/`tier_name`),`--tier`(六 tier 闭集)+
  run 目录锚定 flag 与派发器同源 + `--wave-size` 覆盖 + `--profile`(读环境画像取并发与配
  额);`fanout_runner.py` 零改动;验证:`git diff --stat core/scripts/fanout_runner.py`
  为空;`--help` 即契约
- [x] 2.2 物化输出:`<run>/inputs/<unit>.task.md`(逐字填充,填后断言无残留 `{{`,路径过
  `_anchor_check`)+ `<run>/native_plan.json`(D2 形态:无时间戳、规范 id 排序、固定序列化;
  每单元 `{id, unit_id, task_file, checkpoint_path, done_marker, …枚举器字段透传}` 全绝对);
  stdout 单行摘要(tier/单元数/波次数/wave_size 及来源/两目录绝对路径);验证:同输入两次
  运行,两工件 `cmp` 逐字节相等
- [x] 2.3 短号派生:`<tier>-<4 字符>`,sha1(规范 id) 基 32 去易混字符集;全集两两编辑距离
  ≥2,冲突按 `sha1(unit_id+":"+salt)` 确定性加盐重派生;验证:构造冲突单元集(哈希前 4 字
  符对撞样例)断言加盐收敛与同输入同结果;断点续跑场景(子集重物化)短号不变
- [x] 2.4 波次尺寸:`min(并发, max(1, floor(quota.calls/quota.calls_per_unit)))`,来源记入
  `wave_size_source`;无配额参数时=并发;验证:配额 100/10min/K=10 → 每窗 10 → 波次 3 时
  取 3;并发 5 配额 30/10min/K=10 → 取 3 且来源=quota
- [x] 2.5 零派发副作用:全程不 spawn 模型宿主、不读写凭证、不建隔离目录、不写 marker(枚
  举器子进程除外);验证:monkeypatch/spy 断言 `Bun/subprocess` 类宿主 spawn 面未被调用
  (枚举器白名单除外)、run 目录无新增 marker/XDG/childcfg
- [x] 2.6 `--check`:内存重物化与磁盘工件逐字节比对 + 单元集与枚举器当前 pending 一致 +
  路径绝对且过锚树 + 无残留占位符 + 短号映射闭合与距离不变量;失败退出码 2 + 差异清单 +
  「重物化即修复」recipe,零自动修复;验证:红测三形态(改计划一字节/完成一个单元后
  stale/删一个 task 文件)全红,干净计划绿

## 3. 契约与测试

- [x] 3.1 同步 `core/contracts/fanout/runtime.md` 增「native plan」段:工件布局(native_plan.json
  schema、inputs/<unit>.task.md 与审计副本同路径)、短号规则(派生/加盐/距离不变量/只作转
  述不进路径)、环境画像 schema 与缺省/fail-closed、`--check` 契约、零副作用声明、「auto
  缺省=现状」钉死;验证:契约与两脚本实现逐项对得上
- [x] 3.2 新增 `tests/test_env_profile.py`:缺省解析/坏 JSON/未知 v/域外值/并发越界/--check
  三态/导入形态异常类型;先红后绿;验证:全部用例过
- [x] 3.3 新增 `tests/test_emit_native_plan.py`:逐字节往返/排序稳定/短号稳定与防撞(含构造
  冲突集)/锚树拒绝越树单元/波次算术(含来源字段)/零副作用 spy/--check 红绿(篡改、stale、
  缺文件)/六 tier 至少 sdr+scout 两面冒烟;验证:全部用例过
- [x] 3.4 定向回归:`test_fanout_runner` + `test_fanout_stale`(导入面不破坏派发器)+
  `test_zero_deps` + `test_no_compile_warnings`;验证:逐一跑过无失败
- [x] 3.5 lint 四件套(check_contracts 新 --help 面 / purity 新分发脚本 / budget 预期零增
  量 / plain_language)+ `openspec validate "add-mgh-native-dispatch-core" --strict`;
  验证:与基线一致(无新增违例)

## 4. 实机闸门(零 token 成本)

- [x] 4.1 本机对 sdr tier 真仓(或既有 springBootTemplate 对照仓)跑 `--emit` 两次 +
  `--check`:两工件逐字节一致、check 绿;检查计划内容(抽样 task 文件与既有 runner 审计副
  本语义一致:同模板同字段);确认全程无模型调用;验证:命令与输出摘录记入本 change 实机
  笔记
- [x] 4.2 缺省零变化抽查:同一项目不放 `.mgh/env-profile.json` 跑一次既有 sdr 步骤面(或
  resume 查询),确认行为与主分支一致;验证:记录进实机笔记

## 5. 收尾

- [x] 5.1 VERSION bump + CHANGELOG 分组条目(两新脚本/短号方案/环境画像/零副作用与零变化
  声明)
- [x] 5.2 实机笔记归位本 change 目录;后续 change(看门狗/sdr 接入)的消费指引一句话入
  CHANGELOG 或交接说明;验证:`test_distributed_md_purity` 复跑绿
