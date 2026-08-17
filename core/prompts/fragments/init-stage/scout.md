<!--
  mgh-init stage-flow — scout (step 3b). Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  Loaded per-step via resume_state.py stdout stage_flow_files[] (current-step single file).
-->

## scout (step 3b)

```
3b. SCOUT FAN-OUT (除非 `--no-scout`)——让 LLM 找出 regex 闸门漏掉的自研控制:
     [skeleton.json + controls_candidates.json] → plan_scout.py → [scout_plan.json::batches[]]
     py .claude/mgh-core/scripts/plan_scout.py --skeleton <target>/.mgh-init/skeleton.json \
        --candidates <target>/.mgh-init/controls_candidates.json --out <target>/.mgh-init/scout_plan.json \
        [--batch-bytes .. --batch-cap .. --budget ..]
     · 批数涌现 = ceil(Σtarget_bytes / --scout-batch-bytes);按包内聚切批,每批字节≤预算且文件数≤cap。派生量 `regex_known_count` 在 stdout / `scout_plan.json` 顶层。
     · 校验:`py .claude/mgh-core/scripts/plan_scout.py --check <target>/.mgh-init/scout_plan.json`(batches 非空除非 0 target、每批 bytes≤预算、needs_slice 仅含超批文件;退出码 2 → 回退)。
     [scout_plan.json::batches[]] → list_scout_batches.py --materialize → [stdout slim pending[](每项 `input_path`/`oversize`/`needs_slice`/`checkpoint_path`/`done_marker`/`slice_dir`)](禁手挖 `scout_plan`)
     py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout --materialize <target>/.mgh-init/inputs/scout
     按 `offset`/`effective_limit` 翻页(单页 > `--orch-budget-bytes` 时 `shrunk:true`;NEVER wrapper `.py`);per batch in page `pending[]`(**每批一个隔离 subagent 上下文**;`--resume` 跳过已 `.done`/`.failed`):
       - spawn init-scout(透传 `input_path` + checkpoint_path + done_marker + failed_marker + slice_dir + `<list_steps script_abs 派生的绝对 chunk_sources 路径>`;subagent 读 `input_path`,needs_slice 文件写 `<绝对 chunk_sources> --in <big_file> --big-file-bytes <N> --line <L> --out <slice_dir>/<safe-stem>.slice.json` 并回读该确切路径,**绝不**整文件喂 LLM)→ 成功则恰好写 `checkpoint_path`(绝对) + touch `done_marker`;失败回 `failed <原因>` ack → 编排器写 `failed_marker`、不重试不阻断(见 orchestrator-discipline fragment「fan-out 单元 `failed` ack`)
          · **逐字节复制 recipe(provenance)**:上述 `input_path`/`checkpoint_path`/`done_marker`/`failed_marker`/`slice_dir` 从 `list_scout_batches.py` stdout `pending[]` 对应字段**逐字节**复制、逐字透传给 subagent;NEVER 手拼 `<target>/<id>`、NEVER 从记忆重写路径(弱模型会把下划线目录名概率性重生成分隔符对、把 checkpoint 漂到盘符根 `D:\.mgh-init\…`)、NEVER「简化」/改写前缀;stdout 缺某字段 → 该批 `failed`(不猜不补)。
     spawn init-scout-merge 前**先判聚合预算** — `py .claude/mgh-core/scripts/plan_aggregate.py --node scout-merge --init-dir <target>/.mgh-init --budget <max-aggregate-bytes> [--materialize <target>/.mgh-init/inputs/scout-merge]`
       · `needs_reduce=false`(≤ 预算)→ 既有 single-context `init-scout-merge`(只见全部 scout 批记录,无原始码)→ `scout_candidates.json` + `checkpoints/scout/merge.json.done`
       · `needs_reduce=true`(> 预算)→ 每 shard(batch 簇)扇出 `init-scout-merge`(partial;读 shard `input_path`,ack 回传)→ 单一 rollup 仅吞各 shard 摘要 → `scout_candidates.json` + `checkpoints/scout/merge.json.done`。每请求 ≤ 预算。
     · 校验:`py .claude/mgh-core/scripts/merge_scout.py --check <target>/.mgh-init/scout_candidates.json`(每条 `source:"scout"` + file:line;退出码 2 → 回退)。
     spawn init-scout-audit(随机 ≈--scout-audit-pct 的 scout 拒绝项)→ checkpoints/scout/audit.json + .done
     py .claude/mgh-core/scripts/merge_scout.py --candidates <target>/.mgh-init/controls_candidates.json \
        --scout <target>/.mgh-init/scout_candidates.json --audit <target>/.mgh-init/checkpoints/scout/audit.json \
        --clusters <target>/.mgh-init/clusters.json
     · 候选集并入 `source:"scout"`;clusters.json **追加** scout 簇(regex 簇与其 usage_sites 不变)。复用 `discover_controls.form_clusters`,无逻辑漂移。
     · **并入>0 级联失效**:fold-in 实际并入 N>0 候选时自动删除下游 t2/t3/t4 聚合 `.done`(stderr 注明 + stdout `invalidated_tiers[]`),使 scout 补完后 plain `--resume` 重跑 T2–T4;并入 0(全重复/全失败)不删(输入没变)。
     · **终态**:`scout_candidates.json` / `controls_candidates.json` / `clusters.json` 此时为终态——不再二次聚合 / 重切批(NEVER `_aggregate_scout.py`)。
```
