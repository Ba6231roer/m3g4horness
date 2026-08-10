#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
block_adhoc_scripts — PreToolUse hook enforcing /mgh-init + /mgh-sast + /mgh-sra + /mgh-srr
+ /mgh-ut-init orchestrator discipline (R5.2 at runtime, R5.7 deliverable). Single decision
source for both claude (PreToolUse) and opencode (.ts plugin); the .ts shim is glue-only.

Activation = env OR disk sentinel (closes the opencode "plugin process does not inherit
mid-session bash-exported env -> guard dormant for a whole run" reliability boundary).
Active inside a mgh run-domain when EITHER (a) env MGH_INIT_ACTIVE=1 / MGH_SAST_ACTIVE=1 /
MGH_SRA_ACTIVE=1 / MGH_SRR_ACTIVE=1 / MGH_UT_INIT_ACTIVE=1 is set, OR (b) a disk sentinel
<cwd>/<run-root>/.active exists, where run-root is the domain's run dir (init->.mgh-init,
sast->security-scan, sra->.mgh-sra, srr->.mgh-srr, ut-init->.mgh-ut-init). The sentinel is
JSON {"domain","target","out_roots[]","v":1},
written by the orchestrator at step 0 via Bash and removed on completion/clean-stop.
Outside all run-domains (neither env nor sentinel): exit 0 silently (zero day-to-day noise).
Contract: core/contracts/hooks/runtime-enforcement.md.

MGH_TARGET for the subtree check resolves with precedence env MGH_TARGET > sentinel.target.
When both are absent the subtree check degrades to pass (cwd is the implicit run root —
sentinel discovery is cwd-relative — but is NOT used as a hard block target, to avoid
over-blocking when the orchestrator did not pin one).

Blocks the real-world failure shapes —
  (a) Bash `py -c|python -c` introspection of artifacts (import json / open( / load( / .json);
  (b) Write/Edit of ANY script extension {.py,.ps1,.sh,.bash,.zsh,.bat,.cmd,.ts,.js,.mjs,.cjs}
      — runtime scripts are READ-ONLY (NO path whitelist: the prior core/scripts and
      tests/tools/hooks exemptions only mattered while inactive, at which point main() already
      returned 0). Leaf scripts under mgh-core/scripts/ are read-only for the orchestrator.
  (c) Write/Edit whose resolved target falls OUTSIDE the resolved MGH_TARGET tree (all five
      domains; e.g. a drive root, %LocalAppData%\\Temp). For mgh-init AND mgh-ut-init the
      guard ADDITIONALLY requires the target inside a sanctioned subtree (positive allowlist):
      init -> <target>/.mgh-init/**, <target>/.claude/rules/**, <target>/docs/security-controls/**;
      ut-init -> <target>/.mgh-ut-init/**, <target>/.claude/rules/**, <target>/docs/test-conventions/**;
      both allow <target>/AGENTS.md + sentinel out_roots[] -- so in-tree root pollution
      (temp_clusters*.json, process_*.ps1) fails loud too. sast/sra/srr retain the out-of-tree
      check without the positive allowlist.
  (d) Bash whole-read of a multi-unit aggregate (cat/head/tail/type/Get-Content of
      clusters.json / controls_candidates.json / scout_plan.json / controls_inventory.json /
      s3_chunks.json / s5_filtered.json / scope_manifest.json / change_context.json).
On a hit: exit 2 (Claude Code blocks the call) + stderr recipe pointing at the sanctioned
primitives (list_* --materialize input_path / describe_artifact / producer stdout).

Claude Code feeds the tool call as JSON on stdin:
  {"tool_name":"Bash|Write|Edit", "tool_input":{"command"|"file_path": ...}, ...}

Zero runtime deps (Python >=3.10 stdlib: json/os/pathlib/re/sys). Idempotent, stateless,
no TTY.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path

# Per-domain run-domain env flag + cwd-relative run-root (where the .active sentinel lives).
# Precedence order when more than one is active (rare): sast > sra > srr > init.
_DOMAINS = (
    ("mgh-sast", "MGH_SAST_ACTIVE", "security-scan"),
    ("mgh-sra", "MGH_SRA_ACTIVE", ".mgh-sra"),
    ("mgh-srr", "MGH_SRR_ACTIVE", ".mgh-srr"),
    ("mgh-init", "MGH_INIT_ACTIVE", ".mgh-init"),
    ("mgh-ut-init", "MGH_UT_INIT_ACTIVE", ".mgh-ut-init"),
)

# A `py -c` / `python -c` / `python3 -c` invocation (preceded by start or a shell
# delimiter, so it does not match a substring of another token).
_PYC_RX = re.compile(r'(?:^|[\s;&|(])py(?:thon)?[0-9]*\s+-c\b')
# Introspection / re-derivation signals (FD1 real failure shape).
_INTRO_TOKENS = ("import json", "open(", "load(", ".json")

# Script extensions blocked at runtime (leaf scripts read-only; .ts covers the opencode plugin
# glue -- its install-time write happens while the guard is inactive). .json/.md are NOT here
# (legit artifacts); their *location* is governed by the write-confinement rule.
_SCRIPT_EXTS = (".py", ".ps1", ".sh", ".bash", ".zsh", ".bat", ".cmd",
                ".ts", ".js", ".mjs", ".cjs")

# Per-domain sanctioned work-list primitives (the recipe points the agent at the right
# one). describe_artifact.py + producer stdout are shared across domains.
_WORKLIST = {
    "mgh-init": "list_clusters.py / list_scout_batches.py / list_rule_jobs.py",
    "mgh-sast": "list_chunks.py / list_verify_jobs.py",
    "mgh-sra": "prepare_augment.py / merge_augment.py / merge_memory.py",
    "mgh-srr": "ingest_requirements.py / render_report.py / merge_memory.py",
    "mgh-ut-init": "list_test_groups.py",
}

# Per-domain multi-unit aggregates the orchestrator MUST NOT whole-read (request-context-
# budget): the fan-out unit's complete record is materialized to inputs/<tier>/<unit>.input.json
# (subagent reads it), so whole-reading the aggregate is the bloat failure shape.
_AGGREGATES = {
    "mgh-init": ("clusters.json", "controls_candidates.json", "scout_plan.json",
                 "controls_inventory.json"),
    "mgh-sast": ("s3_chunks.json", "s5_filtered.json", "scope_manifest.json"),
    "mgh-sra": ("change_context.json",),
    "mgh-srr": ("change_context.json",),
    "mgh-ut-init": ("test_groups.json", "test_rules_inventory.json"),
}
# A shell read verb (start/delimiter-bound) — cat/head/tail (sh), type (cmd), Get-Content/gc
# (pwsh). Legit leaf scripts never use these on an aggregate (they pass it as --flag <path>).
_READ_VERB = re.compile(r'(?:^|[\s;&|(])(?:cat|head|tail|type|Get-Content|gc)\b', re.IGNORECASE)

# A write-redirect (`>` / `>>`) to a path under a known temp dir, capturing the written path.
# Temp dir patterns: $env:TEMP/$env:TMP/%TEMP%/%TMP% (Windows), /tmp/$TMPDIR (POSIX);
# case-insensitive (Windows env vars). A path separator is required so `$env:TEMP2/...`,
# `/tmpfoo`, or a bare `%TEMP%` do NOT match. The path character class stops at shell
# delimiters (`;`/`&`/`|`/space/quote), so a `> ...; Get-Content ...` one-liner captures
# exactly the written file (not the trailing `;`).
_TEMP_WRITE_RX = re.compile(
    r'>>?\s*"?\'?((?:\$env:TEMP|\$env:TMP|%TEMP%|%TMP%|/tmp|\$TMPDIR)'
    r'[/\\][^\s;"\'&|]+)',
    re.IGNORECASE)
# A temp read-back verb (Get-Content/gc = pwsh, cat = sh, type = cmd/pwsh alias).
_TEMP_READ_RX = re.compile(r'(?:Get-Content|gc|cat|type)\b', re.IGNORECASE)

# Per-domain sanctioned write subtrees (positive allowlist) for the rules-writing commands;
# sentinel out_roots[] extends this for customized --out / --rules-dir absolute roots.
# mgh-ut-init is same-shape as mgh-init (writes rules into .claude/rules + AGENTS.md), so
# both use the allowlist; sast/sra/srr retain the out-of-tree check without it.
_ALLOWLIST_SUBTREES = {
    "mgh-init": (".mgh-init", ".claude/rules", "docs/security-controls"),
    "mgh-ut-init": (".mgh-ut-init", ".claude/rules", "docs/test-conventions"),
}
# Human-facing label for the allowlist rejection message (keeps the existing "sanctioned
# init subtrees" wording byte-stable for init).
_SUBTREE_LABELS = {"mgh-init": "init", "mgh-ut-init": "ut-init"}


def _recipe(domain: str) -> str:
    return (
        f"{domain} orchestrator discipline (R5.2): use a sanctioned primitive —\n"
        f"  - work-list   -> {_WORKLIST[domain]}\n"
        "  - whole multi-unit aggregate -> list_* --materialize pending[].input_path "
        "(subagent reads its own bounded file) or describe_artifact.py --keys/--field\n"
        "  - structure   -> describe_artifact.py --keys/--sample/--shape/--field\n"
        "  - derived qty -> the producer's stdout field\n"
        f"  NEVER py -c / python -c introspection, NEVER whole-read a multi-unit aggregate, "
        f"NEVER Write a script (leaf scripts read-only) in {domain}; Write/Edit MUST land in "
        f"a sanctioned subtree (init/ut-init) / inside MGH_TARGET (sast/sra/srr)."
    )


def _is_introspect_py_c(cmd: str) -> bool:
    if not _PYC_RX.search(cmd):
        return False
    low = cmd.lower()
    return any(tok in low for tok in _INTRO_TOKENS)


def _is_whole_aggregate_read(cmd: str, domain: str) -> bool:
    """True iff a Bash command shell-reads (cat/head/tail/type/Get-Content/gc) one of this
    domain's multi-unit aggregates. The read-verb guard prevents false positives on legit
    leaf invocations that reference an aggregate as a `--flag <path>` arg."""
    aggs = _AGGREGATES.get(domain, ())
    if not aggs or not _READ_VERB.search(cmd):
        return False
    low = cmd.lower()
    return any(a in low for a in aggs)


def _is_blocked_script_write(path: str) -> bool:
    """True iff a Write/Edit target bears a script extension. NO whitelist -- at runtime there
    is no legitimate script write (all sanctioned producers emit JSON/.md). Inactive sessions
    never reach here (main() returns 0 before any check)."""
    return path.lower().endswith(_SCRIPT_EXTS)


def _read_sentinel(path: Path):
    """Parse the .active sentinel JSON {domain,target,out_roots[],v}; None if missing/broken
    (tolerant: a absent or malformed sentinel is treated as absent -- never blocks)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _safe_resolve(p: str):
    try:
        return Path(p).resolve()
    except (OSError, ValueError):
        return None


def _resolve_domain(cwd: Path):
    """Return (domain, sentinel_or_None) for the active run-domain, else (None, None).
    Active = env MGH_<DOM>_ACTIVE=1 OR <cwd>/<run-root>/.active sentinel present."""
    for domain, env_key, run_root in _DOMAINS:
        sentinel = _read_sentinel(cwd / run_root / ".active")
        if os.environ.get(env_key, "") == "1" or sentinel is not None:
            return domain, sentinel
    return None, None


def _resolve_target(sentinel):
    """MGH_TARGET precedence: env MGH_TARGET > sentinel.target. Returns a resolved abs Path,
    or None when both are absent (None => subtree check degrades to pass; the guard never uses
    cwd as a hard block target -- avoids over-blocking when no target was pinned)."""
    env_t = os.environ.get("MGH_TARGET", "").strip()
    if env_t:
        return _safe_resolve(env_t)
    if sentinel:
        t = sentinel.get("target")
        if isinstance(t, str) and t.strip():
            return _safe_resolve(t.strip())
    return None


def _allowlist_write_blocked(path: str, target, out_roots, subtrees) -> bool:
    """mgh-init / mgh-ut-init positive allowlist: block unless the resolved target is inside a
    sanctioned subtree (e.g. <target>/.mgh-init | .claude/rules | docs/security-controls),
    equals <target>/AGENTS.md, or is inside a sentinel out_roots[] root. Returns False (pass)
    when target is None (degrade), the path is empty, or any side will not resolve."""
    if target is None or not path:
        return False
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return False
    try:
        if p.parent == target and p.name.lower() == "agents.md":
            return False
        for sub in subtrees:
            if p.is_relative_to(target / sub):
                return False
        for root in out_roots:
            r = _safe_resolve(root)
            if r is not None and p.is_relative_to(r):
                return False
    except (OSError, ValueError):
        return False
    return True


def _temp_path_rx(path: str) -> str:
    r"""Regex for a temp path where every separator matches either `/` or `\` (PowerShell
    accepts both; mixed-separator read-back is the same logical file). Other chars escaped."""
    return "".join(r"[/\\]" if ch in ("\\", "/") else re.escape(ch) for ch in path)


def _detect_temp_io(command: str) -> str | None:
    """Detect a Bash command that write-redirects to a known temp dir AND reads the SAME
    file back within the same invocation (defense-in-depth; the primary fix is in the
    orchestrator-discipline fragment's "stdout 直消费"). Returns the written path on match,
    None otherwise.

    Observed failure shapes:
      PowerShell: `> $env:TEMP/x.json; Get-Content $env:TEMP/x.json -Raw | ConvertFrom-Json`
      POSIX:      `> /tmp/x.json; cat /tmp/x.json | jq ...`
    Conservative: write-only temp I/O (no read-back) and in-tree redirects are NOT flagged.
    Regex over known temp patterns (not a shell parser) — does not claim exhaustive
    coverage of every possible temp-dir path."""
    m = _TEMP_WRITE_RX.search(command)
    if not m:
        return None
    path = m.group(1).strip('"\'')
    if not path:
        return None
    if re.search(rf'{_TEMP_READ_RX.pattern}\s*"?\'?{_temp_path_rx(path)}\b',
                 command, re.IGNORECASE):
        return path
    return None


def _is_out_of_tree(path: str, target) -> bool:
    """True iff a Write/Edit target resolves OUTSIDE the MGH_TARGET tree (sast/sra/srr;
    defense-in-depth for the fan-out output-path contract -- turns a silent drift to a
    non-project dir into a fail-loud). Returns False (pass) when target is None (degrade),
    the path is empty, or either side will not resolve."""
    if target is None or not path:
        return False
    try:
        return not Path(path).resolve().is_relative_to(target)
    except (OSError, ValueError):
        return False


def main():
    cwd = Path.cwd()
    domain, sentinel = _resolve_domain(cwd)
    if domain is None:
        return 0  # outside any run-domain: pass silently (zero day-to-day noise)
    target = _resolve_target(sentinel)
    out_roots = (sentinel or {}).get("out_roots") or []
    if not isinstance(out_roots, list):
        out_roots = []
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError):
        return 0  # cannot inspect -> never block
    tool = payload.get("tool_name", "")
    ti = payload.get("tool_input") or {}

    if tool == "Bash":
        cmd = (ti.get("command") or "")
        if _is_introspect_py_c(cmd):
            sys.stderr.write(
                f"blocked: ad-hoc `py -c` introspection in {domain} run-domain.\n  {_recipe(domain)}\n")
            return 2
        # temp-dir write + read-back is checked BEFORE the aggregate read: a list_* command that
        # carries an aggregate as a --flag AND redirects stdout to temp would otherwise trip the
        # aggregate rule with the wrong recipe — the precise guidance here is "consume stdout
        # directly", not "materialize".
        temp_io = _detect_temp_io(cmd)
        if temp_io is not None:
            sys.stderr.write(
                f"blocked: temp-dir write + read-back in {domain} run-domain: "
                f"`{temp_io}` — redirecting deterministic-script stdout to a file under "
                f"$env:TEMP/%TEMP%//tmp/$TMPDIR and reading it back is forbidden; the Bash "
                f"tool result already carries stdout (last line is the JSON), consume it "
                f"directly (orchestrator-discipline \"stdout 直消费\").\n"
                f"  {_recipe(domain)}\n")
            return 2
        if _is_whole_aggregate_read(cmd, domain):
            sys.stderr.write(
                f"blocked: whole-read of a multi-unit aggregate in {domain} run-domain.\n"
                f"  {_recipe(domain)}\n")
            return 2
    elif tool in ("Write", "Edit"):
        path = (ti.get("file_path") or ti.get("path") or "")
        if _is_blocked_script_write(path):
            sys.stderr.write(
                f"blocked: Write/Edit of a script (leaf scripts read-only) in {domain} "
                f"run-domain: {path}\n  {_recipe(domain)}\n")
            return 2
        # write confinement: init/ut-init positive allowlist; sast/sra/srr out-of-tree check.
        if domain in _ALLOWLIST_SUBTREES:
            label = _SUBTREE_LABELS.get(domain, domain)
            if _allowlist_write_blocked(path, target, out_roots,
                                        _ALLOWLIST_SUBTREES[domain]):
                sys.stderr.write(
                    f"blocked: Write/Edit outside the sanctioned {label} subtrees in {domain} "
                    f"run-domain: {path}\n  target = {target}\n  {_recipe(domain)}\n"
                    f"  the output path MUST be the verbatim `checkpoint_path`/`rule_path` "
                    f"from the producer stdout (already absolute, inside <target>/.mgh-init | "
                    f".claude/rules | docs/security-controls | .mgh-ut-init | "
                    f"docs/test-conventions, or a sentinel out_root).\n")
                return 2
        elif _is_out_of_tree(path, target):
            sys.stderr.write(
                f"blocked: Write/Edit outside the MGH_TARGET tree in {domain} run-domain: "
                f"{path}\n  target tree = {target}\n  {_recipe(domain)}\n"
                f"  the output path MUST be the verbatim `checkpoint_path`/`rule_path`/"
                f"`draft_path` from the producer stdout (already absolute, under the target tree).\n")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
