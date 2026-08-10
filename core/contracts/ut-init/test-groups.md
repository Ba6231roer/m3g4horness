# Contract: test_groups.json (layer-group classification)

Producer: `core/scripts/classify_tests.py` (deterministic, stdlib). Consumer: the extract
tier's work-list enumerator `list_test_groups.py --tier extract` + `resume_ut_init_state.py`.

CLI contract (`--help` 即契约):
```bash
py classify_tests.py --repo <target> --out <init-dir> [--scope <path|package|file>] [--subsplit-threshold F]
py classify_tests.py --check <out-dir>
```

## Output Schema

Top-level shape:
```json
{
  "repo": "<abs target>",
  "scope": {"note": "full-repo|path:...|package:...|file:..."},
  "generated_by": "classify_tests.py",
  "groups": [<LayerGroup>, ...],
  "unclassified": ["<rel>", ...],
  "scanned": 0,
  "truncated": false,
  "subsplit_threshold": 0.8
}
```

| field | type | note |
|---|---|---|
| `repo` | string | abs project root (供 `list_test_groups` 读样本) |
| `groups[]` | list | the fan-out units (层组) |
| `unclassified[]` | list | test files with JUnit/TestNG markers but no bucket; disclosed, not grouped |
| `scanned` | int | test files scanned (before content filter) |
| `truncated` | bool | `--max-files` warn-and-continue cap hit |

`LayerGroup`:
```json
{
  "id": "service::MockitoExtension",
  "layer": "controller|service|repository|config|integration|util|other",
  "family": "WebMvcTest|SpringBootTest|MockitoExtension|DataJpaTest|pure|mock-static|mock-time|parameterized|...",
  "uniformity": "uniform|hetero",
  "member_count": 32,
  "assert_density": 2.3,
  "annotation_counts": {"MockitoExtension": 32},
  "members": ["src/test/java/com/acme/service/UserServiceTest.java", "..."]
}
```

## Rules
- **桶集**(pinned): `controller / service / repository / config / integration / util / other`.
- **归类信号** = 实际注解 + import + 包路径 + 文件名综合判定,**不靠名字猜**:`@WebMvcTest`/`@WebFluxTest`
  → controller;`@DataJpaTest`/`@JdbcTest`/`@MybatisTest`/`@DataMongoTest` → repository;
  `@Testcontainers` / `@SpringBootTest`+`TestRestTemplate` → integration;`@SpringBootTest`+`MockMvc`
  → controller;`@SpringBootTest` → service;`@TestConfiguration`/`@Configuration` → config;
  `@ExtendWith(MockitoExtension)`+`@InjectMocks`/`@Mock` → service;包路径/文件名作 fallback 提示。
- **混合子风格拆子组**:一层内若 >1 个 style family 且无单一 family 占比 ≥ `--subsplit-threshold`
  (默认 0.8)→ 按 family 拆子组(`id = <layer>::<family>`)。`uniformity` 按组内注解 token 分布判定。
- **Util 异质子分**(pinned):util 文件按信号优先级 `spring-context > mock-static > mock-time >
  parameterized > pure` 分 style family;混杂 util 桶按同阈值子分。
- **断言密度**(cheap hint,非独立 stage):组内断言命中数 / 测试方法数;喂给提炼 prompt 作样本质量提示。
- `--check`(退出码 0/2):每个 group 有 `id`(唯一)+ `layer`(在桶集)+ `uniformity`(uniform|hetero)+
  非空 `members`;members 跨组不重叠、磁盘上存在。

> **诚实边界**:`unclassified[]` 不进入 fan-out(避免 LLM 读无法归类的长尾);`report.md` 披露其计数。
