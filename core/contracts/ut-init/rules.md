# Contract: test_rules_inventory.json (test-convention rules inventory)

Producer: `ut-synthesize` subagent (whole-tier; no raw code). Consumer: the rules-tier
enumerator `list_test_groups.py --tier rules` + `validate_test_rules.py` boundary check +
`resume_ut_init_state.py`.

Top-level shape:
```json
{
  "repo": "<abs target>",
  "format": "opencode|claude",
  "rules": [<Rule>, ...]
}
```

`Rule`:
```json
{
  "category": "junit5|mockito|assertj|naming|fixture|...",
  "name": "assertj-assertions",
  "layer": "controller|service|repository|config|integration|util",
  "description": "1–2 行:团队在<层>的这条测试约定",
  "usage": "写新测试时 SHOULD 怎么遵循",
  "anchor": "src/test/java/com/acme/UserServiceTest.java::UserServiceTest.t",
  "evidence": ["file:class:method", "..."],
  "provenance": {"groups": ["service::MockitoExtension"], "strong": 4, "weak": 1},
  "confidence": 0.8,
  "weak_dominated": false,
  "notes": []
}
```

## Rules
- **每层 / 每约定一条**:跨组观察去重归并(同约定多处出现 → 合并,provenance 记全部来源组)。
- **每条 SHALL 指向具体文件/类/方法**(`anchor`,可索引)+ **provenance**(从哪组样本归纳、强/弱信号计数)。
- **弱信号主导约定** → `weak_dominated:true` + `confidence ≤ 0.3` + `notes[]`「弱信号主导,需人评」
  + `ut_manifest.json::boundaries[]` 披露。
- **单点信号**(仅 1 组观察佐证)→ `confidence ≤ 0.4` + `notes[]`「单点信号,可能是个例」。
- `validate_test_rules.py --inventory <path>`(退出码 0 ok / 1 用法·IO / 2 违例):wrapper shape + 每条 `category`/`name`/`layer`(在桶集)/
  `anchor`(非空 `file:class:method`)/`evidence`(非空列表)/`provenance.groups`(列表)/`confidence`(∈[0,1])/
  `weak_dominated`(bool,若在)。
- **输出纯净性(源头净化层)**:人读字段 SHALL 只描述目标项目的测试约定;`NEVER` 工具内部信息
  (工具名/脚本名/流水线层级作过程描述/内部路径/「如何被发现」)。结构字段(`provenance`/`layer`/
  `confidence`/`weak_dominated`/`anchor`)原样保留。
- 诚实边界:rules 是 LLM 归纳候选、是提示而非完备规约(抽样必有遗漏,后续 `/mgh-ut` 的 LLM 自适应)。
