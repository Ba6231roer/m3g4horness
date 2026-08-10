## ADDED Requirements

### Requirement: T1 record boundary shape validator

`core/scripts/validate_t1_records.py` SHALL deterministically validate every
`checkpoints/t1/*.json` against the `init-induct` contract shape (`core/prompts/stages/init-induct.md`,
root-level object), mirroring `validate_inventory.py`'s T2-boundary role at the earlier T1 boundary.
For each record it SHALL assert: top-level is a JSON object; root-level `cluster_id` (non-empty string);
`name` (non-empty string); `category` ∈ canonical 8 (`init_tier.INIT_CATEGORIES`); `kind` ∈ vvah 6-enum
(`auth|sandbox|input-validation|aslr|cfi|other`); `category`→`kind` matches `init_tier.KIND`;
`evidence` is a non-empty list of non-empty string anchors; `entry_points` is a list; `confidence` is a
number. A nested `controls[]` key at the root (the observed drift signature where evidence/anchor/confidence
sit under `controls[n]` instead of the root) SHALL be flagged as a violation. stdout SHALL be a single JSON
object `{"check":"t1","ok":bool,"records":N,"bom":[...],"violations":[{"file","cluster_id","issue"}]}`;
stderr SHALL carry diagnostics; exit codes SHALL be 0 (ok) / 1 (checkpoints dir missing) / 2 (violation).
It SHALL be zero-runtime-dependency (Python ≥3.10 stdlib), self-locating its dir for the `init_tier`
sibling import (R5.3a), and runnable under any cwd.

#### Scenario: conforming root-level record passes
- **WHEN** `validate_t1_records.py --checkpoints <dir>` runs over a record with root-level
  `cluster_id`/`name`/`category`/`kind`/`evidence[≥1 anchor]`/`entry_points`/`confidence`, `category` ∈
  the canonical 8, `kind` ∈ the vvah 6-enum, and `category`→`kind` matching `KIND`
- **THEN** stdout `ok` is `true`, `records` counts the file, `violations` is empty, and exit code is 0

#### Scenario: nested controls[] drift is rejected
- **WHEN** a record carries a root-level `controls[]` whose elements hold `evidence`/`anchor_file`/
  `confidence` instead of root-level fields (the observed scout-cluster drift)
- **THEN** the record is reported in `violations` with a `nested controls[] drift` issue and exit code is 2

#### Scenario: missing or empty evidence is rejected
- **WHEN** a record's `evidence` is absent, not a list, empty, or contains a non-string/empty anchor
- **THEN** the record is reported in `violations` and exit code is 2

#### Scenario: non-canonical category or kind is rejected
- **WHEN** a record's `category` is not in the canonical 8, or `kind` is not in the vvah 6-enum, or
  `category`→`kind` does not match `init_tier.KIND`
- **THEN** the record is reported in `violations` with the specific issue and exit code is 2

#### Scenario: missing checkpoints directory
- **WHEN** the `--checkpoints` directory does not exist
- **THEN** stderr reports the missing path and exit code is 1 (not 2)

#### Scenario: empty checkpoints directory is not a violation
- **WHEN** the `--checkpoints` directory exists but contains no `*.json` records
- **THEN** stdout `ok` is `true`, `records` is 0, and exit code is 0 (a missing-T1-run condition is
  `resume_state`'s concern, not the shape validator's)

#### Scenario: BOM is reported as advisory, not a shape violation
- **WHEN** a record file begins with a UTF-8 BOM (`EF BB BF`) but is otherwise conforming
- **THEN** the file is listed in stdout `bom[]` but is NOT a `violations[]` entry, and exit code is 0
  (BOM is losslessly strippable; removal is the `--strip-bom` mode's job, not a fail-loud shape defect)

### Requirement: Lossless UTF-8 BOM strip mode

`validate_t1_records.py --strip-bom --checkpoints <dir>` SHALL losslessly remove a leading UTF-8 BOM
(`EF BB BF`) from each `checkpoints/t1/*.json` and rewrite the file as UTF-8 no-BOM. It SHALL be idempotent:
a file without a BOM SHALL be left byte-identical and not reported as changed. It SHALL NOT alter any byte
other than stripping the leading BOM. stdout SHALL report `stripped[]` (files actually rewritten).
Unreadable / non-UTF-8 files SHALL be skipped and reported in stderr, not crash the run.

#### Scenario: BOM is stripped losslessly
- **WHEN** `--strip-bom` runs over a file beginning with `EF BB BF` followed by valid JSON bytes
- **THEN** the file is rewritten without the BOM, every byte after the BOM is unchanged, and the file is
  listed in stdout `stripped[]`

#### Scenario: no-BOM file is untouched
- **WHEN** `--strip-bom` runs over a file with no leading BOM
- **THEN** the file's bytes are byte-identical before and after, and it is absent from `stripped[]`

#### Scenario: strip is idempotent
- **WHEN** `--strip-bom` is run twice over the same directory
- **THEN** the second run reports an empty `stripped[]` and changes no bytes
