# Contract: T1 record shape + `validate_t1_records.py` (T1→T2 gate)

Producer: `init-induct` (T1, LLM subagent, one record per cluster / per
`<cluster_id>::shard-<n>` unit). Boundary validator: `core/scripts/validate_t1_records.py`
(deterministic, stdlib). Consumer: `init-synthesis` (T2), which reads by contract
field — a shape-drifted record (e.g. evidence/anchor/confidence nested under a
root-level `controls[]` instead of root-level fields) is silently dropped.

> **Why a gate at T1 (not T2):** T2's `validate_inventory.py` validates the
> cross-product inventory, but a drifted T1 record never becomes an inventory
> control to validate — T2 silently drops it. This validator fails loud at the
> earlier T1 boundary so the violating cluster is re-spawned, never carried
> broken into T2.

## T1 record shape (root-level object; one per checkpoint file)

| field | type | note |
|---|---|---|
| `cluster_id` | str | non-empty; canonical cluster id |
| `name` | str | non-empty kebab slug |
| `category` | enum | canonical 8 (`init_tier.INIT_CATEGORIES`) |
| `kind` | enum | vvah 6: `auth`\|`input-validation`\|`sandbox`\|`aslr`\|`cfi`\|`other` |
| `evidence` | [`file:class:method`\|`file:line`] | **≥1** non-empty string anchor |
| `entry_points` | [file] | list (may be empty) |
| `confidence` | number | int/float (bool rejected) |
| `description`/`usage`/`protects`/`gaps` | — | prose; **NOT** asserted (wide legal variance) |

`category`→`kind` SHALL match the deterministic map (`init_tier.KIND`):

| category | kind |
|---|---|
| `input-validation` | `input-validation` |
| `authentication`, `authorization` | `auth` |
| `data-masking`, `crypto`, `csrf`, `rate-limiting`, `audit-logging` | `other` |

> A root-level `controls[]` key = **`nested controls[] drift`** violation (the
> observed scout-cluster drift where fields sit under `controls[n]`). Defense-in-
> depth on the known signature; the positive contract above is the primary guard.

## `validate_t1_records.py` CLI (`--help` IS the contract surface)

```
py validate_t1_records.py --checkpoints <checkpoints/t1-dir> [--check | --strip-bom]
```

- `--check`(default when no mode given, read-only): in-memory strip of a leading
  UTF-8 BOM, then assert the root-level contract shape above.
- `--strip-bom`: losslessly rewrite each file as UTF-8 no-BOM (idempotent; a
  no-BOM file is byte-identical; non-UTF-8 / unreadable skipped + stderr, no crash).
- `--checkpoints` (required): dir holding `*.json` T1 records.

### stdout / exit codes

`--check` stdout (single JSON; stderr = diagnostics):
```json
{"check":"t1","ok":bool,"records":N,"bom":[<abs files with a leading BOM>],
 "violations":[{"file":<abs>, "cluster_id":<str|null>, "issue":<str>}]}
```
- exit `0` = ok (incl. empty dir: `ok:true, records:0` — "did T1 run?" is
  `resume_state`'s concern, not this validator's);
- exit `1` = `--checkpoints` dir missing;
- exit `2` = ≥1 violation (shape drift).

`--strip-bom` stdout:
```json
{"strip-bom":true,"records":N,"stripped":[<abs files actually rewritten>]}
```
- exit `0` always (lossless; idempotent).

### `bom[]` is advisory, not a violation

A leading UTF-8 BOM (`EF BB BF`) is a host/`Write`-tool artifact (RFC 8259
non-conformance but lossless). Under `--check` it is stripped in memory before
`json.loads` and the file is listed in `bom[]` but is **NOT** a `violations[]`
entry. The orchestrator always runs `--strip-bom` before `--check`, so `--check`
sees no BOM in practice; `bom[]` keeps direct/manual `--check` robust.

### Orchestrator wiring (T1 fan-out → T2)

After the T1 fan-out wave completes and before T2: always run `--strip-bom` then
`--check` over `<target>/.mgh-init/checkpoints/t1`. On `--check` exit 2, for each
`violations[]` entry: `rm <file>.done` (invalidate that cluster's `.done` marker)
→ re-run `list_clusters` so the cluster re-enumerates as pending → re-spawn
(`failed`/crash semantics unchanged). Surgical: only violating clusters, not the
whole wave. NEVER carry broken T1 records into T2.
