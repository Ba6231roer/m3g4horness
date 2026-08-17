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
  (e) Bash execution of a script-extension file via the shell's file association — a
      script-ext path as the command body (PowerShell call-operator `& "<…>.py"` OR a bare
      `"<…>.py"` / `./x.sh` first command token) WITHOUT an explicit interpreter-launcher
      prefix. On win32 opencode runs every Bash command under PowerShell
      (`tool/shell.ts`: `powershell -Command …`), so the degraded form resolves the file
      association (e.g. `.py` -> Notepad), opening a GUI editor / "create file?" dialog that
      blocks the shell tool and deadlocks the run. Canonical `py "<abs script>"` /
      `python` / `bash` / `pwsh -File` pass (explicit interpreter -> no file association);
      a script path that is only a `--flag <path>` argument is NOT blocked.
  (f) Read-side out-of-tree: Read/Glob/Grep whose resolved anchor (Read.file_path /
      Glob.path / Grep.path, defaulting to cwd when `path` is absent) falls OUTSIDE the
      resolved MGH_TARGET tree. The submodule leak shape: a reader subagent (cwd = a parent
      repo's submodule, e.g. D:\\parent\\sonA) Read/Glob/Grep the parent dir D:\\parent\\ or
      a sibling module D:\\parent\\sonB\\, which used to reach the host permission prompt and
      INTERRUPT the run (soft failure). Now a fail-loud exit 2 + read-side recipe (D4: a
      Glob/Grep with no `path` and a cwd outside the target tree is the cwd-drift leak).
      target absent => degrade to pass (NEVER a hard read block when none was pinned).
  (g) Bash file-search escape route: a `Bash` command invoking a file-search verb
      (rg/ripgrep/grep/egrep/fgrep/findstr/find/fd/ag/ack as a leading token of the command
      or of a sub-command after `;`/`|`/`&&`/`||`) with an out-of-tree scope (any explicit
      absolute-path argument resolving outside the target tree, OR no explicit path and the
      cwd outside the target tree). Closes the bypass where the model invokes rg/grep/…
      directly in Bash instead of the native Grep/grep tool (whose `path` anchor is already
      confined by (f)). Regex-over-observed-shape; pipes/aliases/env-injected paths not
      guaranteed (same stance as (d)/(e)); a `--flag <path>` argument on a non-search verb
      does NOT trip.
  (h) Bash write/delete-verb escape route + redirect (write side): a `Bash` command invoking a
      write verb (New-Item/Set-Content/Add-Content/Out-File/tee/mkdir/Copy-Item/Move-Item/…)
      or a destructive DELETE verb (Remove-Item/del/rm/rmdir/…) directly in Bash, OR a `>`/`>>`
      redirect, whose destination resolves OUTSIDE the MGH_TARGET tree — closes the bypass where
      the model invokes a file-write/delete verb directly in Bash instead of the native
      Write/Edit tool (whose target is already confined by (c)). For mgh-init AND mgh-ut-init the
      destination SHALL ADDITIONALLY land inside a sanctioned subtree (positive allowlist, P1) —
      an in-tree root-pollution write (`Set-Content <target>\\evil.txt`) fails loud too. A delete
      hit surfaces a delete-side recipe (deletion is irreversible; NEVER delete sibling modules).
      Rule-a relabel: a `py -c` WRITE shape (`write(`/`makedirs`/`shutil.copy`/`shutil.rmtree`/…)
      with an out-of-tree path is labelled write/delete (NOT introspection) so the recipe matches.
  (i) Tool-abstraction write face: claude `MultiEdit`/`NotebookEdit` enter the write-confinement
      branch like Write/Edit; opencode `apply_patch` (paths[] extracted from `patchText` markers by
      the .ts shim, glue-only) is confined path-by-path. An out-of-tree / blocked-script-ext /
      non-sanctioned-subtree path on either => fail-loud + write-side recipe (delete wording for
      apply_patch delete operations). `.ipynb` is NOT a script extension (artifact, not runtime).
On a hit: exit 2 (Claude Code blocks the call) + stderr recipe pointing at the sanctioned
primitives (list_* --materialize input_path / describe_artifact / producer stdout).

Claude Code feeds the tool call as JSON on stdin:
  {"tool_name":"Bash|Write|Edit|MultiEdit|NotebookEdit|ApplyPatch|Read|Glob|Grep", "tool_input":{...}, ...}

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
# Write/delete shapes inside a `py -c` body that are NOT introspection (the prior _INTRO_TOKENS
# `open(`/`load(`/`.json` falsely labelled `py -c "open(..,'w').write('x')"` as introspection,
# surfacing the wrong recipe). On a `py -c` hit with an out-of-tree absolute path, presence of
# one of these => write/delete shape => write-side recipe (rule-a relabel, L1/D8). `open(` is
# intentionally NOT here (ambiguous: `json.load(open('D:/out/x.json'))` is a read) — a bare
# `open('D:/out/f','w')` still blocks via the introspection rule's `open(` token.
_PYC_WRITE_TOKENS = ("makedirs", "mkdir", "write(", "write_text", "write_bytes",
                     "shutil.copy", "shutil.move", "shutil.rmtree", "os.replace",
                     "os.rename", "os.remove", "os.unlink")

# Script extensions blocked at runtime (leaf scripts read-only; .ts covers the opencode plugin
# glue -- its install-time write happens while the guard is inactive). .json/.md are NOT here
# (legit artifacts); their *location* is governed by the write-confinement rule.
_SCRIPT_EXTS = (".py", ".ps1", ".sh", ".bash", ".zsh", ".bat", ".cmd",
                ".ts", ".js", ".mjs", ".cjs")

# File-search verbs a model can invoke DIRECTLY in Bash to bypass the native Grep/grep tool's
# `path` confinement (the read-side tool-abstraction rule covers Read/Glob/Grep; this closes
# the `Bash: rg … <out-of-tree path>` escape route — opencode ships ripgrep, `rg` is on PATH).
# Detection is regex-over-observed-shape: we match the verb as the FIRST token of the command
# or of a sub-command following a shell delimiter (`;`/`|`/`&&`/`||`) — NOT a substring of any
# token, so `grep` inside a longer word never trips. Does NOT claim exhaustive coverage of
# every search form (pipes/aliases/env-injected paths are not guaranteed).
_FILE_SEARCH_VERBS = ("rg", "ripgrep", "grep", "egrep", "fgrep", "findstr", "find",
                      "fd", "ag", "ack")
# A leading file-search verb (start/delimiter-bound) as the FIRST token of a simple command.
# group(1) = the verb; delimiters match the clause-isolation set used by the file-association
# rule so `; rg …` / `| rg …` sub-commands also trip.
_FILE_SEARCH_VERB_RX = re.compile(
    r'(?:^|[;|&])\s*(?:&&|\|\|)?\s*(' + "|".join(_FILE_SEARCH_VERBS) + r')\b',
    re.IGNORECASE)
# An explicit absolute-path token in a Bash command: Windows drive-letter `C:\…`/`C:/…`,
# POSIX `/…`, or UNC `\\…`. Matches the path body up to a shell delimiter (`;`/`&`/`|`/space/
# quote); used to scan a file-search command's path arguments for an out-of-tree anchor.
_ABS_PATH_TOKEN_RX = re.compile(
    r'(?:[A-Za-z]:[\\/][^\s;"\'&|]*|\\\\[^\s;"\'&|]*|/[^\s;"\'&|]*)')

# Write verbs a model can invoke DIRECTLY in Bash to bypass the native Write/Edit tool's
# confinement (the write-side tool-abstraction rule covers Write/Edit/MultiEdit/NotebookEdit;
# this closes the `Bash: Set-Content … <out-of-tree path>` escape route). Detection mirrors
# _FILE_SEARCH_VERB_RX: the verb as the FIRST token of the command or of a sub-command after
# `;`/`|`/`&&`/`||`, NOT a substring of any token (`\b`-anchored, so `cp` inside a longer word
# never trips). Regex-over-observed-shape; does NOT claim exhaustive coverage (pipes/aliases/
# env-injected paths, PowerShell `.NET` static methods, robocopy/fsutil are not guaranteed —
# same stance as the other Bash rules).
_WRITE_VERBS = ("new-item", "ni", "set-content", "sc", "add-content", "ac", "out-file",
                "tee", "mkdir", "md", "copy-item", "cpi", "cp", "copy", "xcopy",
                "move-item", "mi", "mv", "rename", "rename-item")
# Destructive delete verbs are a SEPARATE set so the recipe can call out irreversibility.
_DELETE_VERBS = ("remove-item", "ri", "del", "erase", "rm", "rmdir", "rd")
# Copy/Move/xcopy are multi-source verbs whose DESTINATION is the LAST absolute-path token
# (source tokens may legitimately live in-tree); all other write/delete verbs are single-path
# (ANY out-of-tree absolute-path token => hit).
_COPY_MOVE_DEST_VERBS = ("copy-item", "cpi", "cp", "copy", "xcopy", "move-item", "mi", "mv")
# A leading write/delete verb (start/delimiter-bound). group(1) = the verb (capture preserves
# case; .lower()'d on lookup against the lowercased tuples above).
_MUTATION_VERB_RX = re.compile(
    r'(?:^|[;|&])\s*(?:&&|\|\|)?\s*(' + "|".join(_WRITE_VERBS + _DELETE_VERBS) + r')\b',
    re.IGNORECASE)

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

# Explicit interpreter-launcher prefixes that PASS the file-association rule (block D1):
# when one of these precedes a script path, the shell runs the interpreter (no file
# association). Stored as a set of the FIRST launcher token + a few two-token forms
# (`pwsh -File`, `cmd /c`, …) matched against the command's leading tokens.
_LAUNCHER_PREFIXES = (
    "py", "python", "python3", "python2",
    "bash", "sh", "dash", "zsh",
    "pwsh -file", "pwsh -command",
    "powershell -file", "powershell -command",
    "cmd /c", "cmd /k",
)
# A leading PowerShell call-operator `&` (optionally followed by spaces) before a
# script-ext path = invocation via file association (the observed deadlock shape).
_CALL_OP_RX = re.compile(r'^\s*&\s*')
# A script-ext path token at command-body position: quote-wrapped OR bare (incl. a
# leading `./` / `.\` / `/`). Matches the leading command token only (anchored).
# _SCRIPT_EXTS already include the literal dot and re.escape keeps it; do NOT add a
# second `\.` prefix (that would require a double dot). The path body allows any
# non-space, non-quote char so both `"…\chunk_sources.py"` and `./x.sh` match.
_SCRIPT_EXT_ALT = "|".join(re.escape(e) for e in _SCRIPT_EXTS)
# group 1 = the bare/quoted script-ext token at the start (sans quotes/call-op).
_CMD_BODY_EXT_RX = re.compile(
    r'^\s*(?:&\s*)?"?\'?([^\s"\']*(?:' + _SCRIPT_EXT_ALT + r'))"?\'?(?:\s|$)',
    re.IGNORECASE)

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
# A `>` / `>>` redirect to ANY path (generalizes _TEMP_WRITE_RX, which only matched known
# temp-dir prefixes). Captures the redirect target (stops at a shell delimiter). Used to block
# non-temp out-of-tree redirects (`echo x > D:\out\f.json`) the temp-only rule did not match.
# The retained _detect_temp_io defense (temp write + read-back) stays independent of this rule.
_REDIRECT_RX = re.compile(r'>>?\s*"?' + r"'?" + r'([^\s;"\'&|]+)')

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


def _read_recipe(domain: str, target) -> str:
    """Read-side out-of-tree recipe (peer of _recipe; shared by the tool-abstraction rule
    Read/Glob/Grep and the Bash file-search rule rg/grep/find/…). Read side has NO positive
    allowlist (only 'stay inside the target tree'); the recipe points at the batch input +
    repo-root-anchored search, never at the parent dir / sibling modules."""
    tgt = target if target is not None else "<not pinned — resolve MGH_TARGET>"
    return (
        f"  target tree = {tgt}\n"
        f"  Read/Glob/Grep (and Bash rg/grep/find/findstr/…) MUST stay inside the target "
        f"tree (your cwd's working project). Read only this batch's input_path / targets[]; "
        f"for sibling-package confirmation use Glob/Grep (or `rg`/`grep` in Bash) with an "
        f"EXPLICIT `path` anchored at the repo root. NEVER read the parent dir, NEVER read "
        f"sibling modules, NEVER anchor a search at a path outside the target tree."
    )


def _read_out_of_tree(tool_input, target, cwd):
    """True iff a Read/Glob/Grep call's resolved anchor falls OUTSIDE the resolved MGH_TARGET
    tree. Read takes `file_path`; Glob/Grep take the `path` anchor (defaulting to cwd when
    absent — D4). Same Path.resolve().is_relative_to(target) semantics as the write side
    (_is_out_of_tree), NOT a positive-allowlist check — any file inside the target tree is
    readable. Returns False (pass) when target is None (degrade), the path is empty, or
    either side will not resolve."""
    if target is None:
        return False
    # Read: single file_path.
    fp = (tool_input.get("file_path") or tool_input.get("path") or "")
    if fp:
        try:
            return not Path(fp).resolve().is_relative_to(target)
        except (OSError, ValueError):
            return False
    # Glob/Grep: the `path` anchor is the authoritative scope (the `pattern`/`glob` field is
    # NOT parsed for traversal — conservative against false positives on legit patterns). When
    # `path` is absent the anchor defaults to the guard's cwd (D4 cwd-as-anchor): a cwd that
    # drifted outside the target tree (submodule cwd = parent) is exactly the leak shape.
    anchor = (tool_input.get("path") or "").strip()
    if not anchor:
        try:
            return not cwd.is_relative_to(target)
        except (OSError, ValueError):
            return False
    try:
        return not Path(anchor).resolve().is_relative_to(target)
    except (OSError, ValueError):
        return False


def _out_of_tree_file_search(command, target, cwd):
    """True iff a Bash command invokes a file-search verb (rg/grep/findstr/find/fd/ag/ack,
    as the FIRST token of the command or a sub-command after `;`/`|`/`&&`/`||`) with an
    out-of-tree scope. On a verb hit: scan every explicit absolute-path token (Windows
    drive-letter / POSIX / UNC) in the command — ANY one resolving outside the target tree
    => True. No explicit absolute path => the search root defaults to cwd (D4): block iff cwd
    is outside the target tree. Returns False (pass) when target is None (degrade), no
    file-search verb leads any simple command, or no path resolves. Regex-over-observed-shape:
    does NOT parse which token is pattern vs path (syntax varies), does NOT claim exhaustive
    coverage of pipes/aliases/env-injected paths (same stance as temp-I/O / file-assoc rules).
    """
    if target is None or not _FILE_SEARCH_VERB_RX.search(command):
        return False
    abs_tokens = _ABS_PATH_TOKEN_RX.findall(command)
    for tok in abs_tokens:
        try:
            if not Path(tok).resolve().is_relative_to(target):
                return True
        except (OSError, ValueError):
            continue
    # No explicit absolute-path token at all -> the search root defaults to cwd: a cwd that
    # drifted outside the target tree is the leak shape (D4). If ANY absolute-path argument
    # was present (all in-tree), the search root is that path, NOT cwd -> pass.
    if abs_tokens:
        return False
    try:
        return not cwd.is_relative_to(target)
    except (OSError, ValueError):
        return False


def _is_introspect_py_c(cmd: str) -> bool:
    if not _PYC_RX.search(cmd):
        return False
    low = cmd.lower()
    return any(tok in low for tok in _INTRO_TOKENS)


def _out_of_tree_mutation(command: str, target, cwd):
    """Decide a Bash write/delete-verb (or `py -c` write shape) for write confinement.

    Returns a tuple (kind, dest, oot):
      - kind  : "write" / "delete" / None  (None => no mutation verb / `py -c` write hit)
      - dest  : the offending destination token string (an absolute path, or "<cwd>" for the
                cwd-drift leak), or "" when kind is None
      - oot   : True iff dest resolves OUTSIDE the target tree (the W1/W3/D4 shape). False when
                kind is set but the destination is IN the target tree (the P1/D5 in-tree root-
                pollution shape, only enforced for init/ut-init by the caller).

    Mirror of _out_of_tree_file_search, applied to write/delete verbs (_WRITE_VERBS /
    _DELETE_VERBS) instead of search verbs. On a verb hit, scan every explicit absolute-path
    token; for single-path verbs the FIRST out-of-tree token => hit, otherwise the FIRST in-tree
    token is the destination (for P1); for Copy/Move/xcopy the LAST token (= destination) is
    judged. No explicit absolute path => the destination defaults to cwd (D4): a cwd outside the
    target tree => oot hit (dest="<cwd>"); a cwd inside => in-tree (dest="<cwd>", oot=False) so
    the caller can still run the init/ut-init P1 check.

    Returns (None, "", False) when target is None (degrade — NEVER use cwd as a hard block target
    when none was pinned), no mutation verb leads any simple command, or no path resolves.

    NOTE: the init/ut-init in-tree sanctioned-subtree check (P1/D5) is applied by the caller on
    a (kind set, oot False) result — it needs domain + out_roots + subtrees (mirror of how the
    Write/Edit tool layer works).
    """
    if target is None:
        return None, "", False   # degrade-pass (NEVER use cwd as a hard block target when none pinned)
    m = _MUTATION_VERB_RX.search(command)
    if m:
        verb = m.group(1).lower()
        kind = "delete" if verb in _DELETE_VERBS else "write"
        abs_tokens = _ABS_PATH_TOKEN_RX.findall(command)
        if verb in _COPY_MOVE_DEST_VERBS:
            # destination = LAST absolute-path token; sources may legitimately be in-tree.
            if abs_tokens:
                dest = abs_tokens[-1]
                try:
                    return kind, dest, not Path(dest).resolve().is_relative_to(target)
                except (OSError, ValueError):
                    return None, "", False
            # no explicit path -> destination defaults to cwd
            try:
                in_tree = cwd.is_relative_to(target)
            except (OSError, ValueError):
                return None, "", False
            return kind, "<cwd>", not in_tree
        # single-path write/delete verb: judge the destination. If ANY token is out-of-tree, that
        # is the hit (W1/W3); otherwise the FIRST in-tree token is the destination for P1.
        for tok in abs_tokens:
            try:
                if not Path(tok).resolve().is_relative_to(target):
                    return kind, tok, True   # out-of-tree hit
            except (OSError, ValueError):
                continue
        if abs_tokens:
            # every token in-tree -> first token is the destination, caller runs P1 on it
            return kind, abs_tokens[0], False
        # no explicit path -> destination defaults to cwd
        try:
            in_tree = cwd.is_relative_to(target)
        except (OSError, ValueError):
            return None, "", False
        return kind, "<cwd>", not in_tree
    # rule-a relabel (L1/D8): a `py -c` write/delete shape (shutil.rmtree / write / makedirs / …)
    # with an out-of-tree absolute path => write/delete recipe (NOT the introspection recipe).
    # shutil.rmtree + os.remove/unlink => delete; the rest => write. Only fires when the
    # command carries an out-of-tree absolute path AND a write token; pure in-tree `py -c` writes
    # are governed by the tool layer (the orchestrator does not Bash-write via `py -c` legitimately).
    if _PYC_RX.search(command):
        low = command.lower()
        if any(tok in low for tok in _PYC_WRITE_TOKENS):
            is_del = any(t in low for t in ("rmtree", "os.remove", "os.unlink"))
            kind = "delete" if is_del else "write"
            for tok in _ABS_PATH_TOKEN_RX.findall(command):
                try:
                    if not Path(tok).resolve().is_relative_to(target):
                        return kind, tok, True
                except (OSError, ValueError):
                    continue
    return None, "", False


def _write_recipe(domain: str, target, kind: str) -> str:
    """Write/delete out-of-tree recipe (peer of _read_recipe; shared by the tool-abstraction
    rule MultiEdit/NotebookEdit/ApplyPatch and the Bash write/delete/redirect rules). Writes
    point at the producer stdout absolute paths; deletes additionally call out irreversibility.
    target None => degrade (the caller already gated on a real target)."""
    tgt = target if target is not None else "<not pinned — resolve MGH_TARGET>"
    base = (
        f"  target tree = {tgt}\n"
        f"  Writes/Moves/Copies MUST land inside the target tree (your cwd's working project). "
        f"Use the producer's stdout path verbatim (checkpoint_path / rule_path / draft_path — "
        f"already absolute, inside <target>/.mgh-init | .claude/rules | docs/security-controls | "
        f".mgh-ut-init | docs/test-conventions, or a sentinel out_root). NEVER Bash "
        f"Set-Content / New-Item / tee / > redirect outside the tree; NEVER apply_patch / "
        f"MultiEdit / NotebookEdit outside the tree.")
    if kind == "delete":
        base += (
            "\n  Deletion is IRREVERSIBLE (no artifact is produced; the action cannot be rolled "
            "back). NEVER Remove-Item / del / rm / rmtree outside the target tree, including "
            "sibling modules — use a sanctioned primitive for whatever you intended instead.")
    return base



def _is_whole_aggregate_read(cmd: str, domain: str) -> bool:
    """True iff a Bash command shell-reads (cat/head/tail/type/Get-Content/gc) one of this
    domain's multi-unit aggregates. The read-verb guard prevents false positives on legit
    leaf invocations that reference an aggregate as a `--flag <path>` arg."""
    aggs = _AGGREGATES.get(domain, ())
    if not aggs or not _READ_VERB.search(cmd):
        return False
    low = cmd.lower()
    return any(a in low for a in aggs)


def _is_file_assoc_script_exec(cmd: str) -> bool:
    r"""True iff a Bash command executes a script-extension file via the shell's file
    association -- i.e. a script-ext path is the COMMAND BODY (PowerShell call-operator
    `& "<…>.py"` OR the first command token, quote-wrapped or bare like `./x.sh`) AND no
    explicit interpreter-launcher prefix precedes it in that simple command.

    Defense-in-depth Bash-command rule (peer of temp-I/O + aggregate-read). The observed
    Windows failure shape: opencode runs every Bash command under PowerShell
    (`tool/shell.ts`: win32 -> `powershell -Command …`); a degraded
    `& "…\chunk_sources.py" --out …` resolves the `.py` file association (e.g. Notepad on
    a machine where `.py` is associated with an editor), opening a GUI editor / "create
    file?" dialog that blocks the shell tool, hangs the subagent ack, and deadlocks the
    parent `task.wait`.

    Operand-vs-arg distinction: only the command-BODY position is matched, so
    `py foo.py`, `python "…\.py"`, `bash x.sh`, `pwsh -File x.ps1` PASS (explicit
    launcher -> interpreter, no file association), and a script path that appears only as
    a `--flag <path>` argument to a legitimately-launched command also passes. Regex over
    the observed shape (not a shell parser) -- does NOT claim exhaustive coverage of every
    possible file-association form."""
    # Only the FIRST simple command matters (before `;` / `|` / `&&` / `||`): the body
    # position is where file association bites. Splitting on these delimiters isolates it
    # so a trailing `; <something>.py` arg in a later clause does not false-trip the
    # leading-token anchor.
    first = re.split(r'[;|]', cmd, maxsplit=1)[0]
    m = _CMD_BODY_EXT_RX.search(first)
    if not m:
        return False
    # A leading call-operator `&` already implies file association (no launcher); otherwise
    # check the first non-empty token: if it is a known launcher prefix (incl. two-token
    # forms), this is an explicit-interpreter invocation -> PASS.
    if _CALL_OP_RX.search(first):
        return True
    toks = first.strip().split()
    if not toks:
        return True
    lead = toks[0].lower()
    if lead in ("py", "python", "python3", "python2", "bash", "sh", "dash", "zsh"):
        return False
    # two-token launcher forms: `pwsh -File`, `cmd /c`, …
    two = " ".join(t.lower() for t in toks[:2])
    if two in _LAUNCHER_PREFIXES:
        return False
    return True


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


def _is_temp_redirect_target(target: str) -> bool:
    """True iff a redirect target points at a known temp dir prefix ($env:TEMP / %TEMP% / /tmp /
    $TMPDIR) — these are handled by the retained _detect_temp_io defense, so the generalized
    redirect rule skips them (avoids double-flagging with the wrong recipe)."""
    return bool(_TEMP_WRITE_RX.search(">" + target))


def _redirect_in_sanctioned(target: str, domain, project_target, out_roots) -> bool:
    """For init/ut-init: True iff the redirect/mutation target lands inside a sanctioned
    subtree (P1/D5), reusing the same allowlist the Write/Edit tool layer uses. Returns True
    (pass / in-sanctioned) when the domain has no allowlist (sast/sra/srr — they only get the
    out-of-tree check), when project_target is None, the path is empty, or either side will not
    resolve. NOTE: returns True for in-sanctioned AND for degradable/no-allowlist cases; the
    caller already applied the out-of-tree check, so True here means 'OK to proceed'."""
    subtrees = _ALLOWLIST_SUBTREES.get(domain)
    if subtrees is None:
        return True
    return not _allowlist_write_blocked(target, project_target, out_roots, subtrees)


def _emit_bash_write_block(domain, cmd, kind, dest, target, out_roots):
    r"""Emit the stderr block for a Bash write/delete-verb (or `py -c` write shape) out-of-tree
    hit. kind = "write" | "delete". Handles the in-tree-but-not-sanctioned (P1/D5) case for
    init/ut-init too: a mutation verb destination inside the target root but outside a sanctioned
    subtree (root pollution: `Set-Content <target>\evil.txt`) fails loud, mirroring the
    Write/Edit tool layer. dest="<cwd>" => the cwd-drift leak (D4), reported as such."""
    location = dest if dest and dest != "<cwd>" else "<cwd> (outside the target tree)"
    sys.stderr.write(
        f"blocked: out-of-tree {kind} in {domain} run-domain: `{cmd}`\n"
        f"  destination = {location}\n"
        f"  The Write/Edit tool's confinement is bypassed by invoking a write/delete verb "
        f"(Set-Content / New-Item / Remove-Item / tee / …) directly in Bash with an "
        f"out-of-tree destination.\n{_write_recipe(domain, target, kind)}\n")


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
        # rule-a relabel (L1/D8): a `py -c` WRITE/DELETE shape with an out-of-tree path is
        # checked BEFORE the introspection rule. The prior _INTRO_TOKENS `open(`/`load(`/`.json`
        # falsely labelled `py -c "open('D:/out/f','w').write('x')"` as introspection, surfacing
        # the wrong (introspection) recipe. Now: write token + out-of-tree absolute path =>
        # write-side recipe. Order matters: this gate precedes _is_introspect_py_c so the write
        # shape wins when both a write token and an introspection token are present. Target
        # absent => _out_of_tree_mutation returns pass (degrade, same as every side).
        mut_kind, mut_dest, mut_oot = _out_of_tree_mutation(cmd, target, cwd)
        if mut_kind in ("write", "delete"):
            # out-of-tree (W1/W3/D4): always block. in-tree (P1/D5): block only for init/ut-init
            # when the destination is NOT inside a sanctioned subtree (root pollution). sast/sra/
            # srr have no allowlist, so an in-tree mutation destination passes (mirror of the
            # Write/Edit tool layer). dest="<cwd>" + in-tree => cwd is the run root, a sanctioned
            # location only when cwd itself is under a sanctioned subtree; treat "<cwd>" as
            # root-level for the P1 check (root pollution is the threat model).
            if mut_oot:
                _emit_bash_write_block(domain, cmd, mut_kind, mut_dest, target, out_roots)
                return 2
            if domain in _ALLOWLIST_SUBTREES:
                p1_dest = cwd if mut_dest == "<cwd>" else mut_dest
                if not _redirect_in_sanctioned(p1_dest, domain, target, out_roots):
                    sys.stderr.write(
                        f"blocked: in-tree {mut_kind} outside the sanctioned "
                        f"{_SUBTREE_LABELS.get(domain, domain)} subtrees in {domain} "
                        f"run-domain: `{cmd}`\n"
                        f"  The Write/Edit tool's positive allowlist is bypassed by invoking a "
                        f"write/delete verb directly in Bash (root pollution).\n"
                        f"{_write_recipe(domain, target, mut_kind)}\n")
                    return 2
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
        if _is_file_assoc_script_exec(cmd):
            sys.stderr.write(
                f"blocked: script executed via file association in {domain} run-domain.\n"
                f"  A script-extension path was used as the command body without an explicit "
                f"interpreter launcher (PowerShell call-operator `& \"<…>.py\"` or a bare "
                f"\"<…>.py\"/`./x.sh` as the command). On win32 opencode runs every Bash "
                f"command under PowerShell, so this resolves the `.py`/`.ps1` file "
                f"association (e.g. Notepad), opening a GUI editor / \"create file?\" dialog "
                f"that blocks the shell tool and deadlocks the run.\n"
                f"  Use the explicit-launcher form VERBATIM: `py \"<abs script>\" …` (or "
                f"`python`/`bash`/`pwsh -File`). NEVER `& \"<abs>.py\"`, NEVER a bare "
                f"\"<abs>.py\" command body.\n"
                f"  {_recipe(domain)}\n")
            return 2
        # read-side confinement, Bash escape route (D9): a file-search verb (rg/grep/findstr/
        # find/fd/ag/ack) invoked DIRECTLY in Bash bypasses the native Grep/grep tool's `path`
        # confinement. Block when its search scope (any explicit absolute-path argument OR the
        # implicit cwd anchor) is outside the MGH_TARGET tree. Operand-vs-arg: a command with
        # no file-search verb as a leading token (e.g. `py … --in x.java`) does NOT enter here.
        if _out_of_tree_file_search(cmd, target, cwd):
            sys.stderr.write(
                f"blocked: out-of-tree file search in {domain} run-domain: `{cmd}`\n"
                f"  The native Grep/grep tool's `path` confinement is bypassed by invoking a "
                f"file-search binary (rg/grep/findstr/find/…) directly in Bash with an "
                f"out-of-tree scope.\n{_read_recipe(domain, target)}\n")
            return 2
        # write confinement, Bash escape route (W2/D3): a `>`/`>>` redirect whose target resolves
        # OUTSIDE the MGH_TARGET tree (generalizes _TEMP_WRITE_RX, which matched only temp-dir
        # prefixes). The retained temp-I/O rule above is an independent defense (temp write +
        # read-back); this catches the non-temp out-of-tree redirect `echo x > D:\out\f.json`.
        # temp targets are still caught first by _detect_temp_io; here any remaining out-of-tree
        # redirect target fails loud. target absent => degrade (the resolve skips).
        if target is not None:
            for rm in _REDIRECT_RX.finditer(cmd):
                rdest = rm.group(1).strip('"\'')
                if not rdest or _is_temp_redirect_target(rdest):
                    continue
                if _is_out_of_tree(rdest, target):
                    if _redirect_in_sanctioned(rdest, domain, target, out_roots):
                        continue
                    sys.stderr.write(
                        f"blocked: out-of-tree redirect in {domain} run-domain: `{cmd}`\n"
                        f"  The Write/Edit tool's confinement is bypassed by a `>`/`>>` redirect "
                        f"to a path outside the target tree.\n"
                        f"{_write_recipe(domain, target, 'write')}\n")
                    return 2
                # in-tree redirect: init/ut-init ALSO require the target inside a sanctioned
                # subtree (P1/D5) — root pollution (`echo x > <target>\evil.txt`) fails loud.
                if domain in _ALLOWLIST_SUBTREES and not _redirect_in_sanctioned(
                        rdest, domain, target, out_roots):
                    sys.stderr.write(
                        f"blocked: in-tree redirect outside the sanctioned "
                        f"{_SUBTREE_LABELS.get(domain, domain)} subtrees in {domain} "
                        f"run-domain: `{cmd}`\n"
                        f"{_write_recipe(domain, target, 'write')}\n")
                    return 2
    elif tool in ("Read", "Glob", "Grep"):
        # read-side confinement, tool-abstraction layer (D1): a Read/Glob/Grep whose resolved
        # anchor (Read.file_path / Glob.path / Grep.path, defaulting to cwd) falls outside the
        # MGH_TARGET tree. The soft failure that interrupted runs (host permission prompt on a
        # cross-module read) becomes a fail-loud recipe. target absent => degrade to pass
        # (NEVER use cwd as a hard read block target when none was pinned).
        if _read_out_of_tree(ti, target, cwd):
            sys.stderr.write(
                f"blocked: read outside the MGH_TARGET tree in {domain} run-domain.\n"
                f"  {_read_recipe(domain, target)}\n")
            return 2
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        # path extraction: Write/Edit/MultiEdit carry file_path; NotebookEdit carries
        # notebook_path (.ipynb is an artifact, NOT a runtime script — it is NOT in _SCRIPT_EXTS;
        # NotebookEdit is confined by tree location only, same as Write/Edit).
        path = (ti.get("file_path") or ti.get("notebook_path") or ti.get("path") or "")
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
    elif tool == "ApplyPatch":
        # opencode multi-file mutating tool (add/update/delete/move); the .ts shim extracts every
        # `*** (Add|Update|Delete|Move to) File: <path>` marker into paths[] with a parallel
        # operations[] (glue only — single decision source). Each path is confined like Write/Edit:
        # script-ext block (add/update) + out-of-tree check + init/ut-init sanctioned-subtree
        # allowlist. delete operations surface the delete-side wording. ANY path hit => fail-loud.
        paths = ti.get("paths") or []
        ops = ti.get("operations") or []
        if isinstance(paths, list):
            for i, path in enumerate(paths):
                if not isinstance(path, str) or not path:
                    continue
                op = ops[i] if isinstance(ops, list) and i < len(ops) else ""
                kind = "delete" if op == "delete" else "write"
                if _is_blocked_script_write(path):
                    sys.stderr.write(
                        f"blocked: ApplyPatch add/update of a script (leaf scripts read-only) "
                        f"in {domain} run-domain: {path}\n  {_recipe(domain)}\n")
                    return 2
                if domain in _ALLOWLIST_SUBTREES:
                    if _allowlist_write_blocked(path, target, out_roots,
                                                _ALLOWLIST_SUBTREES[domain]):
                        sys.stderr.write(
                            f"blocked: ApplyPatch outside the sanctioned "
                            f"{_SUBTREE_LABELS.get(domain, domain)} subtrees in {domain} "
                            f"run-domain: {path}\n"
                            f"{_write_recipe(domain, target, kind)}\n")
                        return 2
                elif _is_out_of_tree(path, target):
                    sys.stderr.write(
                        f"blocked: ApplyPatch outside the MGH_TARGET tree in {domain} "
                        f"run-domain: {path}\n{_write_recipe(domain, target, kind)}\n")
                    return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
