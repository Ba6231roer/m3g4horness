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
     [scout_plan.json::batches[]] → fanout_runner.py(内部消费 list_scout_batches --materialize)→ [波次 spawn + ack + marker,零 LLM 回合]
     · **主路径(dispatcher,一次 Bash + 重派)**:带 per-call `timeout` 跑
       py .claude/mgh-core/scripts/fanout_runner.py --scout-plan <target>/.mgh-init/scout_plan.json --checkpoints <target>/.mgh-init/checkpoints/scout --inputs-dir <target>/.mgh-init/inputs/scout --time-budget-ms <宿主 per-call timeout × 0.8,如 opencode 900000ms 宿主 → 720000;claude Bash 上限 600000ms → 480000> --call-timeout-s <per-call 杀上限(秒),MUST < budget×0.8,如 720000→540 / 480000→360> --stall-timeout-s <失活静默阈(秒),MUST < --call-timeout-s,如 300>
       · **派发前孤儿清理(每次 fanout 派发前,MUST)**:上一次运行可能被宿主硬杀、留下仍在烧 token 的孤儿 runner/子进程。先 `py .claude/mgh-core/scripts/fanout_runner.py --kill-stale --dry-run --checkpoints <本 tier checkpoints 目录>` 审将杀 PID → `killed` 非空则去掉 `--dry-run` 真杀;`killed:[]` 幂等跳过。stderr 心跳行(每单元派发事件 + 每 `--hb-interval-s`(默认 60s)一行在飞披露 `inflight=<k> unit=<id> idle=<s>s done=<d>/<total>`)为实时进度;非 ok 终态 stderr 附该单元 run.log 绝对路径(`<checkpoints>/<tier>/<unit>.run.log`),失活树杀单元列于 stdout `stall_killed[]`。
       · 四级超时不变式(spawn 前 fail-loud,违反退出码 2):`--time-budget-ms` MUST < 宿主 per-call `timeout` 且 MUST 显式传 `--call-timeout-s`(< budget×0.8)、`--stall-timeout-s` < `--call-timeout-s`(≥60;失活=子进程输出静默 ≥ 阈值即树杀重派):stall-timeout-s < call-timeout-s < time-budget-ms × 0.8 < 宿主 per-call `timeout`;合规组合 720000/540/300 或 480000/360/300;软时限先于宿主硬杀触发,重派才轮轮干净早退而非硬杀循环。详见 `fanout_runner.py --help`。
       · stdout 摘要 `partial:true`(软时限早退)→ **重派同一命令**(重派传 per-call `timeout` > `--time-budget-ms`)直至 `partial:false`;NEVER 手动翻页、NEVER 逐次撰写 subagent 任务消息(固定模板 + 逐字填充在脚本内完成)。
       · **零推进熔断(双观察点)**:每新派发 N×`--wave` 个单元或队列耗尽后重列,均重列一次磁盘终态计数;连续 N 次(默认 2,`--stall-waves`)零增长且仍有待派 → **退出码 2** + stdout `stalled:true` + `stalled_pending[]`(每卡住单元的 id + 其 marker 在盘存在性)→ **停止重派**、跑 `py .claude/mgh-core/scripts/resume_state.py --target <target> --check` 诊断,对照 `stalled_pending[]` 核对 marker 存在性;诊断清楚后 `--resume` 续跑。NEVER 熔断后继续盲目重派。
       · **快败风暴三层(配额限流形态)**:① `stalled:true` 且 `resume_state.py --check` 无磁盘异常(marker 与 `stalled_pending[]` 互洽)→ provider 拥塞形态 → 直接重派同一命令(runner 已内建快败冷却 `--cooldown-s` 与熔断前一次退避自愈),NEVER 据此改写输入/删 marker/写微脚本;② stdout `rate_limited:true` + `rate_limited_crashes[]`(限流特征风暴截断)→ **等满一个配额窗口**(网关配置,如 10 分钟)再 `--resume`;③ tier 收尾 `failed>0` 且该单元 run.log 呈 provider 瞬断(429/rate limit/quota)→ **至多一次** `--retry-failed` 重派(runner 自动携枚举器 `--include-failed`,身份来自枚举器,认领删 marker),再失败接受缺口并在报告披露。
       · 退出码 2(宿主 CLI 不可用)→ stderr 带 recipe → 走下方**手派路径**(行为与引入 dispatcher 前逐字一致);退出码 2 + `STALLED` 心跳 = 零推进熔断 → 上行 recipe。
       · **宿主外手动直跑(大仓长跑逃生门)**:人可自己开终端直跑同一 dispatcher 命令(无宿主超时钳制、stderr 逐波进度直读、进度 sidecar `<target>/.mgh-init/fanout_progress.scout.json` 照写),跑完回会话 `/mgh-init --resume` 接续(磁盘 marker 是唯一真相源,两侧天然互斥)。
     · **手派路径(回退)**:list_scout_batches 枚举 + 编排器逐波 spawn——
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
