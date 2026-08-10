# Contract: ut_manifest.json (terminal manifest)

Producer: command orchestrator (final step). Consumer: humans + `/mgh-ut` (future) + resume.

Top-level shape:
```json
{
  "version": "0.1.x",
  "format": "opencode|claude",
  "repo": "<abs target>",
  "counts": {"groups": 7, "extract": 7, "rules": 3, "unclassified": 2, "scanned": 123},
  "failures": {"extract": {"done": 5, "failed": 1, "total": 7},
               "rules": {"done": 2, "failed": 0, "total": 3}},
  "rules": {"block": "test-conventions", "rules_dir": "<abs>",
            "rules_layout": "claude:.claude/rules/test-*.md|opencode:AGENTS.md index + docs/test-conventions/*.md",
            "categories": ["junit5", "mockito"],
            "migrated_legacy_blocks": 0,
            "lint": {"ok": true, "violations": []}},
  "mutators": {"source": "pitest-config|builtin-fallback", "mutators": 7},
  "provenance": {"classify": "classify_tests.py", "extract": "ut-extract",
                 "synthesize": "ut-synthesize", "rules": "ut-rulewriter"},
  "boundaries": [],
  "artifacts": {}
}
```

## Boundaries[] (honesty disclosures; 简体中文文案)
- rules 是 LLM 归纳候选、是提示而非完备规约(抽样提炼必有遗漏,后续 `/mgh-ut` 的 LLM 自适应);
- 弱信号测试只标记不删、不学成家法;弱信号主导约定需人评;
- fan-out 单元确认失败、已跳过、终局需人评(per-tier `{done,failed,total}`);
- 请求上下文预算触发(`oversize`/`shrunk`/聚合超限)无静默溢出;
- pitest-config 派生 mutator 清单仅作默认;未发现配置 → builtin-fallback 披露;
- JVM-only(只扫 Java/Kotlin/Scala/Groovy 测试源码树);
- `unclassified[]` 长尾不进入 fan-out。

## Checkpoint-unit table
| tier | unit |
|---|---|
| classify | whole (test_groups.json) |
| extract | per group `extract/<safe(group_id)>.json` |
| synthesize | whole `synthesize/.done` |
| rules | per category `rules/<cat>.<fmt>.json` |
| assemble | `assemble/.done` |
| consistency | whole `consistency/.done` |
| mutators | whole (default_mutators.json) |
