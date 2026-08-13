<!--
  mgh-init stage-flow — resolve (step 3c, optional, codegraph-gated). Install mirrors to <mgh-core>/prompts/fragments/init-stage/.
  Loaded per-step via resume_state.py stdout stage_flow_files[] (current-step single file).
-->

## resolve (step 3c)

```
3c. (optional, codegraph-gated) init-resolve — 仅当 `codegraph=on` **且** `unresolved[]` 非空时执行;
     排空文本/AST 图结构性漏掉的框架路由 / DI / AOP / interface→impl / 反射控制。**non-fatal + bounded**:
     [controls_candidates.json::unresolved[]] → describe_artifact.py --field → init-resolve subagent → [resolved.json]
     · 取 `unresolved[]` 清单(合法瞄结构出口):
       `py .claude/mgh-core/scripts/describe_artifact.py --in <target>/.mgh-init/controls_candidates.json --field unresolved`
       → stdout `{"field":"unresolved","value":["<file>",...]}`;空列表 → 跳过本 stage(摘要披露)。
     · spawn init-resolve({unresolved[], repo root, checkpoint_path=<target>/.mgh-init/resolved.json(绝对),
       done_marker=<target>/.mgh-init/checkpoints/resolve/.done(绝对)}, codegraph=on)
       → 恰好写 `checkpoint_path`(绝对)+ touch `done_marker`(产 `{repo, resolved[]{…source:"codegraph", resolved_path[]}, unresolved_residual[]}`,见 `core/contracts/init/resolved.md`)
     · **additive 并入 T1 候选流**:`resolved[]` 按既有 `category::anchor` 簇键由编排器路由到对应簇的 candidate hits(additive;**不** mutate regex/scout 候选、**不**改任何确定性脚本;簇形成语义与既有 form_clusters 一致)。`source:"codegraph"` 结构标签一路保留进 inventory/manifest。`unresolved_residual[]` 残留计 manifest `codegraph.unresolved_residual`。
     · **MGH_TARGET / 子树守卫**:`resolved.json` 写在 `<target>/.mgh-init/` 下,既有子树守卫覆盖;`checkpoint_path` 是编排器**逐字给定**的绝对路径(NEVER 拼装 `<target>/<id>`、NEVER 占位符、NEVER 相对)。
     · **fail-soft / non-fatal**:`codegraph=off` / `unresolved[]` 为空 / 清单过大超单 subagent 上下文预算 → 跳过整 stage + 摘要披露,流水线**不阻断**、不报致命错(对标 init-survey 的 optional/advisory/non-fatal 语义)。T1 从 `clusters.json` 正常扇出不受影响。
```
