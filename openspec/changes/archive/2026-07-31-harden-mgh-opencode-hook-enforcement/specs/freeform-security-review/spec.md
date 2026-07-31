## MODIFIED Requirements

### Requirement: Runtime discipline and zero runtime dependencies

`/mgh-srr` SHALL run under the `MGH_SRR_ACTIVE` run-domain (parallel to `MGH_SRA_ACTIVE`) with the
`block-adhoc-scripts` guard active on both claude (`PreToolUse`) and opencode (`.ts` plugin) ends. The guard's
**activation model + runtime write discipline** SHALL follow the shared contract
[`runtime-hook-enforcement`](../runtime-hook-enforcement/spec.md): activation = `MGH_SRR_ACTIVE=1` env **or**
the `<cwd>/.mgh-srr/.active` disk sentinel (written by the orchestrator at step 0 via `Bash`, removed on
completion/clean-stop — closes the prior opencode "mid-session env not inherited → guard dormant" boundary);
runtime writes of any script extension (`.py`/`.ps1`/`.sh`/`.ts`/…) SHALL fail-loud with **no**
`core/scripts`/`mgh-core/scripts` whitelist exemption (leaf scripts are read-only); out-of-subtree writes SHALL
be blocked (srr retains the out-of-tree check; no positive allowlist). The new scripts SHALL use only the Python
standard library (no `pip` dependency; R2); `.docx`/`.xlsx` handling via `zipfile` + `xml.etree`.

#### Scenario: hook blocks adhoc script in SRR domain
- **WHEN** the orchestrator attempts a `py -c` introspection, a `Write` of an adhoc `.py`/`.ps1`/`.ts` script, or an out-of-subtree write
- **THEN** the `block-adhoc-scripts` guard fails the call (exit code 2) with a stderr recipe; identical behavior on both claude and opencode ends

#### Scenario: opencode activates the srr guard via the disk sentinel
- **WHEN** opencode 下 `MGH_SRR_ACTIVE` env 未设,但 step 0 已写 `<cwd>/.mgh-srr/.active` 哨兵
- **THEN** 守卫经哨兵激活,等效 env 已设;内省/越权脚本写/越树写均 fail-loud

#### Scenario: Shell writes and removes the srr sentinel
- **WHEN** 审阅两份 `mgh-srr.md` 编排流起步与完成态
- **THEN** 两壳均含 `export MGH_SRR_ACTIVE=1` + 写 `<target>/.mgh-srr/.active` 哨兵步骤;完成态移除哨兵
