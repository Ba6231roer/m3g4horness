# tasks — improve-mgh-init-t1-cluster-packing

## 1. list_clusters.py 打包核心

- [ ] 1.1 argparse 新增 `--pack-bytes B`(默认 0)与 `--pack-max N`(默认 8);`--help` 文案写明
  打包语义(单元=包、成员 marker 真相源、纯函数分区)与四级默认;`--pack-max` 单独传入而
  `--pack-bytes` 为 0 → 退出码 2 + recipe(无效组合)
- [ ] 1.2 分区函数:同 category、单簇 bytes ≤ `--max-unit-bytes` 的簇按 `(bytes 升序, cluster_id)`
  排序贪心装包(超 `--pack-bytes` 或 `--pack-max` 封包);包 id = `pack::<category>::<sha8(成员 id
  排序拼接)[:8]>`;oversize/`::shard-<n>` 单元与物化失败簇(已有 `.failed`)不入包、按既有形态
  独立出现
- [ ] 1.3 合并 input 物化:每包写 `<inputs/t1>/<safe(pack_id)>.input.json`
  (`{repo, pack_id, members:[{cluster_id, ...簇记录, hits}], checkpoints:[{cluster_id,
  checkpoint_path, done_marker}]}`,utf-8、stem 截长同源);envelope `input_path` 指向合并文件
- [ ] 1.4 包级 pending 派生 + 披露:`pending[]` 元素 `cluster_id` 载包 id、新增 `members[]`
  `{cluster_id, input_path, checkpoint_path, done_marker, bytes}`(全绝对);包 pending ⟺ ≥1 成员
  缺 `.done`;stdout 增 `cluster_total`/`cluster_done`(仅打包路径输出);`--pack-bytes 0` 路径
  stdout 逐字节不变(无新字段);分页 `--offset/--limit` 与 `--orch-budget-bytes` 收紧对包级
  列表原样生效
- [ ] 1.5 stderr 诊断:打包开启时报包数/簇数/平均成员数;物化失败簇照既有隔离语义排除出包

## 2. t1-task.md 模板多成员契约

- [ ] 2.1 模板改双形态(或打包专段):成员迭代契约——读合并 input → 探测各成员 `done_marker`
  (已有即跳过)→ 逐成员归纳、逐成员写 checkpoint(`unit` 字段 = 成员 cluster_id)+ touch 该
  成员 `done_marker` → 成员失败先完成其余成员 → 末行单行 ack `ok <pack_id> <已处理数>` /
  `failed <成员 id 列表>:<原因>`;单簇路径形态逐字不变
- [ ] 2.2 模板占位符集核对:占位符仍由 runner TIERS["t1"] 逐字替换(`{{cluster_id}}`=包 id、
  `{{input_path}}`=合并文件、`{{checkpoint_path}}`/`{{done_marker}}` 载成员清单于合并 input
  内,模板不再依赖单值占位符指认成员)——与 runner 字段位零改动对齐

## 3. 调用面与文档同步

- [ ] 3.1 `core/prompts/fragments/init-stage/t1.md` 调用示例增 `--pack-bytes`(配额场景建议值
  16384 + 一行何时启用)
- [ ] 3.2 `core/scripts/discipline_core.py` T1 步 path_recipes:增打包 flag 与「包级 `.failed` 恢复
  recipe(删除包 failed marker → 重列 → 跳过已完成成员)」
- [ ] 3.3 `docs/man/mgh-init.md`:T1 段增打包小节(参数、建议值、调用数账型、恢复 recipe、
  与簇级 marker 的关系);glossary 补「打包(pack)」条目(若缺)

## 4. 回归测试

- [ ] 4.1 `tests/test_list_clusters.py` 新增:打包确定性(同输入两次枚举包集合逐字节一致;任意
  cwd 不变)、跨 category 不混包、oversize/shard 不入包、物化失败簇不入包、包 pending 成员
  marker 派生(部分 done → 包 pending;全 done → 消失;`cluster_done` 正确)、合并 input 内容
  与 stem 截长、`--pack-bytes 0` 逐字节回归、无效 flag 组合退出码 2
- [ ] 4.2 `tests/test_init_ack_contract.py`:打包 ack 形态(`ok <pack_id> <n>` / `failed <成员
  列表>:<原因>`)入契约断言;单簇 ack 契约回归
- [ ] 4.3 `tests/test_fanout_runner.py` 冒烟:t1 tier 消费打包 pending(包 id 走 `cluster_id`
  字段位)零改动通过

## 5. 全量校验与收尾

- [ ] 5.1 `py tools/check_contracts.py`(新 flag 经 `--help` 断言)、`py tools/check_distributed_purity.py`、
  `py tests/test_list_clusters.py`、`py tests/test_init_clusters.py` 全绿
- [ ] 5.2 install 冒烟:`install.sh --claude .` + `--opencode .` 镜像后自检无 warn(t1-task.md 变更
  随镜像落地)
- [ ] 5.3 真机验收:配额环境 T1 打包实跑一段——对比开启前后单元数/stdout `cluster_total`/
  调用数(网关侧);crash 重派跳过已完成成员至少一次实证;CHANGELOG.md / VERSION bump
