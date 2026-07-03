# Tasks — fix-mgh-init-cluster-fanout

> 实现顺序:契约 + 叶脚本 → 双壳收紧 → 测试/工具/版本 → 验收。每项可独立验证。

## 1. 核心产物(core/)

- [x] 1.1 新增 `core/contracts/init/clusters.md`:落 `{repo, clusters[], truncated}` 包装结构 +
      Cluster 记录字段表(`cluster_id/category/kind/shape/evidence_files[]/usage_sites[]/candidate_ids[]`,
      源 `discover_controls.py:409`);注明簇级无 `entry_points`(在 candidate 上)。与 `candidates.md`
      并列同风格。
- [x] 1.2 新增 `core/scripts/list_clusters.py`:argparse 契约 `--clusters <path>` `--checkpoints <dir>`
      (可选,默认 `<clusters>/../checkpoints/t1`);读 `clusters.json` + 扫 `*.done`;stdout JSON
      `{repo,total,done,pending[],truncated}`,`pending[]` 每项
      `{cluster_id,category,kind,shape,evidence_files[],candidate_count}`;stderr 走进度;退出码 `0/1/2`。
- [x] 1.3 `list_clusters.py` 自包含纪律:`sys.path.insert(0, dir-of-__file__)`、utf-8 读入、
      任意 cwd 可 `py`、零第三方依赖(仅 `argparse/json/pathlib/sys`)、`--help` 列全 flag。
      幂等只读;空 `clusters[]`→`total:0`、`truncated:true`→透传,均退出 `0`。

## 2. 编排器双壳(releases/,逐字镜像 R5.1)

- [x] 2.1 `releases/claude-code/commands/mgh-init.md` 步骤 4:fan-out 改为调用
      `list_clusters.py` 取 `pending[]`;显式声明 clusters.json 是包装字典,**禁止 `len()` 顶层**;
      簇数真相源 = discover stdout `clusters` / list_clusters stdout `total`。补「确定性调用」示例。
- [x] 2.2 同壳「Stage→组件表」补 `list_clusters.py` 行(i1/T1 枚举);「Output」段补指向 `clusters.md`。
- [x] 2.3 同壳步骤 3 init-survey:标注 **optional + advisory(非 T1 输入)+ non-fatal + 大簇跳过**;
      声明缺失 `i1_enriched.json` 不阻断。
- [x] 2.4 `releases/opencode/command/mgh-init.md`:逐字镜像 2.1–2.3 的全部改动(flag/示例/措辞一致)。

## 3. 测试 / 工具 / 版本(R5.8)

- [x] 3.1 `tests/`:为 `list_clusters.py` 加用例——包装解包、pending·done 切分、`total=done+len(pending)`、
      空 clusters、`truncated:true` 透传、缺 checkpoints 目录。可并入 `test_deterministic.py` 或新建文件。
- [x] 3.2 `tools/check_contracts.py`(注:该工具本仓库**未实现**,`tools/` 仅 extract_prompts/gen_lens_skills/gen_opencode_agents;改为**手动双壳 flag 镜像核验**——claude/opencode 两壳的 `list_clusters.py --clusters/--checkpoints` 调用逐字一致,已 grep 确认):把 `list_clusters.py` 及其 flag(`--clusters`/`--checkpoints`)
      加入双壳 flag 提取 + `--help` 断言集。
- [x] 3.3 版本 bump:确认版本载体(grep 顶层 VERSION / install.sh / manifest 字段;design Open Q),
      按既有约定 bump;在壳/manifest 记录新版本。
- [x] 3.4 零依赖 AST 扫描:确认 `list_clusters.py` 无非标准库 import、无 `vvaharness` import。

## 4. 验收

- [x] 4.1 `py tests/test_deterministic.py`(或新测)全绿;`py tools/check_contracts.py` 双壳全 flag 通过。
- [x] 4.2 `openspec validate fix-mgh-init-cluster-fanout` 通过(契约/场景 4-hashtag 合规)。
- [x] 4.3 手测:对样例仓跑 `discover_controls.py` → `list_clusters.py`,确认 `total` 等于 `clusters[]`
      实际长度(非 3);构造若干 `.done` 验证 pending 切分。
- [x] 4.4 回归确认:`clusters.json` 磁盘结构未变;既有产物兼容;双壳措辞一致。
