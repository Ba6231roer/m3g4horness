# Contract: `skeleton.json`

Producer: `core/scripts/discover_controls.py` (i1, deterministic, stdlib; emitted in the
**same single pass** as `controls_candidates.json` — no second walk). Consumer: `core/scripts/plan_scout.py` (scout batch
planner) + audit trail.

> **纯机械抽取,不含语义判定。** skeleton 只回答「这个文件结构长什么样」,**不**回答
> 「它是不是安全控制」——后者由 LLM scout 层在廉价元数据上判断。覆盖**全部非点前缀**源文件
> (含被 regex 预过滤跳过的文件),是 scout 选择「读谁」的全仓地图。点前缀路径默认与候选/
> 调用图同一 chokepoint 跳过(见 `candidates.md`「文件枚举剪枝」;`--include-dotfiles` 覆盖)。

Top-level shape:

```json
{
  "repo": "<abs repo root>",
  "generated_by": "discover_controls.py",
  "files": [<FileSkeleton>, ...]
}
```

A `FileSkeleton`:

```json
{
  "file": "src/main/java/com/acme/security/PermGuard.java",
  "lang": "java",
  "pkg": "src/main/java/com/acme/security",
  "classes": ["PermGuard"],
  "imports": ["jakarta.servlet.http.HttpServletRequest"],
  "method_sigs": ["check", "enforce", "isAllowed"],
  "fan_in": 47,
  "bytes": 12345,
  "regex_hit": false
}
```

| field | type | note |
|---|---|---|
| `file` | path | 相对 repo 的 posix 路径 |
| `lang` | enum | `expand_scope` 的 `SOURCE_EXT` 语言键(java/python/js/ts/go/c/ruby/php) |
| `pkg` | path | 由 file 推导的目录(posix);scout 按此做**包内聚**分批 |
| `classes[]` | [name] | 复用既有 `CLASS_RX`(class/interface/enum/record/`@interface`) |
| `imports[]` | [str] | 按 `lang` 分派的 import/`#include`/require/`from…import` 命中串(去重,有上限) |
| `method_sigs[]` | [name] | 复用 `JAVA_DEF`/`DEF_CALL` 的定义名(len>2) |
| `fan_in` | int | reverse 调用图上该文件被多少文件调用(scout 的「共享控制」信号) |
| `bytes` | int | 文件字节数;scout 按此做**字节预算**分批 |
| `regex_hit` | bool | 是否被 i1 regex 命中(命中者已产候选,scout 不重复扫) |

- **无损**:抽取不做任何「是否控制」判断;`regex_hit=false` 的文件**仍出现**在此(对 scout 可见)。
- **单遍**:`discover_controls.py` 在既有 walk+read 循环里追加抽取,不新增遍历。
