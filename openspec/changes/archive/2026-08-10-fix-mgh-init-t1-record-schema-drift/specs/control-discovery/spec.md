## ADDED Requirements

### Requirement: Deterministic T1 record gate before T2 synthesis

The `/mgh-init` orchestrator SHALL, after the T1 fan-out wave completes and before advancing to T2
synthesis, run `validate_t1_records.py --strip-bom` and then `validate_t1_records.py --check` over
`<target>/.mgh-init/checkpoints/t1` (the `--strip-bom` pass is always run and is idempotent; the `--check`
pass is the fail-loud gate). On `--check` exit code 2, the orchestrator SHALL invalidate each violating
record's `.done` marker and re-spawn those clusters via `list_clusters` (fail-loud recovery), and MUST
NOT carry broken T1 records into T2 synthesis. This gate is the T1-boundary dual of the existing T2
`validate_inventory.py` gate, closing the path by which LLM-induced T1 record shape drift (e.g. a nested
`controls[]` instead of root-level `evidence`/`entry_points`/`confidence`) is silently dropped by T2.
See capability `t1-record-schema-gate` for the validator contract.

#### Scenario: all T1 records conform — T2 proceeds
- **WHEN** T1 fan-out is complete and `validate_t1_records.py --check` exits 0 over `checkpoints/t1`
- **THEN** the orchestrator advances to T2 synthesis with the validated records

#### Scenario: a T1 record drifts — gate fails loud, broken record never reaches T2
- **WHEN** one or more `checkpoints/t1/*.json` violate the contract shape (e.g. nested `controls[]`)
- **THEN** `--check` exits 2, the orchestrator invalidates the violating clusters' `.done` markers and
  re-spawns them, and does NOT advance to T2 carrying the broken records

#### Scenario: BOM is removed before the shape gate
- **WHEN** T1 records were written with a leading UTF-8 BOM
- **THEN** the orchestrator-run `--strip-bom` removes the BOM before `--check`, so the shape gate sees
  no-BOM records and BOM is never a fail-loud trigger
