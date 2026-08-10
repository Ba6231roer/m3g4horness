# Contract: default_mutators.json (pitest mutator derivation)

Producer: `core/scripts/derive_mutators.py` (deterministic, stdlib). Consumer: future
`/mgh-ut --mutators` (default consumption point); `report.md` / `ut_manifest.json` disclose
the source.

CLI contract (`--help` 即契约):
```bash
py derive_mutators.py --repo <target> [--out <init-dir>]
py derive_mutators.py --check <out-dir>
```

stdout:
```json
{
  "source": "pitest-config|builtin-fallback",
  "mutators": ["CONDITIONALS_BOUNDARY", "INCREMENTS"],
  "parser_notes": ["checked pom.xml", "..."],
  "output": "<abs>/.mgh-ut-init/default_mutators.json"
}
```

Top-level shape:
```json
{
  "source": "pitest-config|builtin-fallback",
  "mutators": ["CONDITIONALS_BOUNDARY", "..."],
  "parser_notes": ["checked pom.xml", "no pitest mutator config found ..."]
}
```

## Rules
- **解析**:`pom.xml`(找 `<mutators>…</mutators>` 取 `<mutator>`)/ `build.gradle`(bracket 形式
  `mutators = ["A","B"]`)/ `build.gradle.kts`(`mutators = setOf("A","B")`);按顺序,首个含
  pitest mutator 配置的文件定 `source:"pitest-config"`。
- **未发现配置** → `source:"builtin-fallback"`,mutators = **pitest 官方默认组**(pinned):
  `CONDITIONALS_BOUNDARY, INCREMENTS, INVERT_NEGS, MATH, NEGATE_CONDITIONALS, RETURN_VALS,
  VOID_METHOD_CALLS`;`parser_notes[]` 披露「未发现 pitest 配置,用内置标准集」。
- `--check`(退出码 0/2):`source` ∈ {pitest-config, builtin-fallback} + `mutators` 非空列表 +
  `parser_notes` 列表。
- **诚实边界**:mutator 清单仅作默认消费口;实跑 pitest 验证变异杀死是后续 opt-in,本版不做。
