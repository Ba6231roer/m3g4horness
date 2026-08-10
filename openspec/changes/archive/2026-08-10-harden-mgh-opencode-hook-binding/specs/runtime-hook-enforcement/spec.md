## ADDED Requirements

### Requirement: opencode shim feeds the guard payload via a Bun-compatible stdin

The opencode `.ts` shim SHALL feed the guard subprocess its JSON payload via a Bun-compatible
`stdin` form — `new Blob([<stringified payload>])` (or the `"pipe"` + `proc.stdin.write/end`
form). The shim MUST NOT pass a bare string to `Bun.spawn`'s `stdin`: opencode's bundled Bun
rejects a string stdin (`TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null`),
which throws inside the shim's guard-invocation path; the shim's fail-soft handling then returns a
pass and the guard silently never blocks (the D7 incident — a `py -c` introspection one-liner ran
unblocked and zeroed 25 T1 checkpoints). The Python guard (single decision source) is unchanged.

#### Scenario: a py -c introspection one-liner is blocked in opencode
- **WHEN** an opencode session is inside an mgh run-domain (env `MGH_*_ACTIVE=1` at opencode launch
  OR the `<cwd>/<run-root>/.active` sentinel present) and the model issues a Bash `py -c` command
  carrying introspection tokens (`import json` / `open(` / `load(` / `.json`)
- **THEN** the shim feeds the normalized payload to the guard as `new Blob([stdin])`, the guard
  exits 2, the shim throws and the tool call is blocked (the model sees the sanctioned-primitive
  recipe) — the guard is NOT silently disabled by a stdin-delivery throw

#### Scenario: the shim source form is regression-guarded in CI
- **WHEN** the shim source is checked in CI (no Bun runtime available)
- **THEN** a parity-test source-form assertion requires `new Blob([stdin])` to be present, preventing
  a silent revert to a bare string stdin (the runtime delivery itself is verified manually in opencode)
