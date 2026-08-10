# Contract: resume_ut_init_state.py stdout (re-entrant ut-init resume state)

Producer: `core/scripts/resume_ut_init_state.py` (deterministic, stdlib). Consumer: the
orchestrator — the single sanctioned "which step am I / what next" outlet after `--resume` /
compaction / new session.

CLI contract (`--help` 即契约):
```bash
py resume_ut_init_state.py --target <dir> [--init-dir <dir>] [--run-root <name>] [--check]
```

stdout:
```json
{
  "target": "<abs>",
  "format": "opencode",
  "step": "extract",
  "resumable": true,
  "tiers": {
    "classify": {"done": 1, "failed": 0, "total": 1},
    "extract": {"done": 2, "failed": 1, "total": 7},
    "synthesize": {"done": 0, "failed": 0, "total": 1},
    "rules": {"done": 0, "failed": 0, "total": 3},
    "assemble": {"done": 0, "failed": 0, "total": 1},
    "consistency": {"done": 0, "failed": 0, "total": 1},
    "mutators": {"done": 0, "failed": 0, "total": 1}
  },
  "next_action": {"kind": "bash|subagent|done", "desc": "...", "absolute_paths": ["<abs>", "..."]},
  "notes": []
}
```

## Rules
- **step** ∈ `not-started|classify|extract|synthesize|rules|assemble|consistency|mutators|done`。
  阻塞序列 = `classify→extract→synthesize→rules→assemble→consistency→mutators→done`。
- **ut 步骤图含「归类」前置、无 codegraph 解析步骤**(区别于 init)。
- **fan-out 层组「完成到可继续」= `done+failed>=total`**;`.failed` = 终态(`--resume` 跳过、不重派;
  crash 无 ack → 无 marker → 仍 pending → 重派)。
- 真相源 = 磁盘 `<target>/.mgh-ut-init/`(产物 + `.done`/`.failed` + `run_config.json`),**非对话记忆**。
- `run_config.json` 缺失/不可解析 → **退出码 2** + recipe(NEVER 静默猜步骤图)。
- `--check`(退出码 0/2)自洽:synthesize `.done` 无 inventory / extract `.done` 无 test_groups /
  rules `.done` 无 inventory / skip_consistency 却出现 consistency `.done` / 一单元同时 `.done`+`.failed` /
  extract marker 引未知 group / 兄弟产物不一致。
- **init 的 `resume_state.py` 零改动**(ut resume 是独立副本,隔离「恢复兜底」的爆炸半径)。
