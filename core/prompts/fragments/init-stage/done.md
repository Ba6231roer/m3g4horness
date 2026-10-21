<!--
  mgh-init stage-flow — done. Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  Loaded per-step via resume_state.py stdout stage_flow_files[] (current-step single file).
-->

## done

```
8. i4: write init_manifest.json + report.md; print artifact paths + disclaimers
   · manifest 含 `codegraph:{available,used,resolved_count,unresolved_residual}`:`available`=检测到 `.codegraph/`+CLI;`used`=`codegraph=on` 且 `init-resolve` 实跑;`resolved_count`/`unresolved_residual` 取自 `resolved.json`(经
     `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/resolved.json --field resolved --count` 计数);`codegraph=off` 时 `used=false`/`resolved_count=0`,不出现解析计数。report.md 同步披露 codegraph 用量 + 残留盲区。
   · **fan-out 失败披露**(任一 tier `failed>0`):据 `resume_state.py` stdout `tiers[<tier>].failed`(磁盘真相、**NEVER** 对话记忆)写 `init_manifest.json::failures`(per-tier `{done,failed,total}`)+ `boundaries[]`(「fan-out 单元确认失败、已跳过、终局需人评」)+ `report.md` 同步披露失败计数/率。
   · **scout_merged 落账**:读 `resume_state.py` stdout `tiers.scout.merged`(fold-in 实际并入数;fold-in 未跑 / `--no-scout` 时缺省)写入 `init_manifest.json::scout.scout_merged`(既有 `scout` 段增字段,不改段结构)。
   · **派发形态与通道落账**:原生形态(`resume_state.py` stdout `dispatch` 在场)时——`scout.dispatch`(八键,取自 dispatch 字段)+ `aggregate_dispatch`(聚合四层:每层
     `native_plan_<tier>.json` 在场证据 + 实际通道 `tool|waves` + 回退/零派发/缺口事实 `fallback_events[]`)写入 manifest;`boundaries[]` 同步披露实际派发形态与通道(回退如实记,
     NEVER 声称未发生的通道);子进程形态两字段均缺席(读者以「字段缺席 = 子进程」解释)。
   · **收尾移除哨兵**:`rm <target>/.mgh-init/.active`(run 完成;避免残留哨兵锁死日常开发)
```
