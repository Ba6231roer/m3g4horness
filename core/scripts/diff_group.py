#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
diff_group — deterministic diff collection + interface-dimension grouping for /mgh-sdr.

Collects `git diff --no-color <base>..<branch>` in the target repo, splits changed files
into review units, materializes one read-only slice file per unit, and prints the
authoritative pending work-list as JSON on stdout (the fanout_runner --tier sdr single
pending source, same shape contract as list_clusters / list_scout_batches / list_rule_jobs).

Grouping rules (heuristic, NOT a promise — disclosed in the report):
  interface unit (kind=interface): a java web file whose branch version carries interface
    annotations. Class-level base route from `@RequestMapping("...")` above the class
    declaration; method-level mappings (@GetMapping/@PostMapping/@PutMapping/
    @DeleteMapping/@PatchMapping plus @RequestMapping/@Path/@GET/@POST/@PUT/@DELETE forms)
    located by line number in the branch content. Each method mapping whose line range
    intersects a diff hunk = one interface unit (route = base + method path) owning those
    hunks. Unclaimed hunks of an interface file (class-level changes, imports, fields) form
    one extra class-level unit (route = base route) — never dropped. Heuristic failure
    (no annotations / non-java project) degrades SAFELY: everything becomes standalone
    units, the flow does not fail.
  standalone unit (kind=standalone): every remaining file (non-interface java, config,
    SQL, frontend passthrough, deleted files, binaries) clustered by directory; clusters
    merge in sorted order while the combined slice MEASURES within --max-standalone-bytes
    (measured, never estimated — see the slice byte gate below).

Slice byte gate — the budget is a hard cap, not a target (an LLM context window is a
  physical ceiling; a soft target is no target at all). Every size judgement is the utf-8
  byte length of the RENDERED slice (`_SliceGate.bytes` -> `_render_slice`), i.e. the very
  renderer that materializes the file — NEVER a parallel estimator (an estimator and the
  artifact drift; this gate cannot). Packing-time member sizes use the same measurement.
  A unit over its cap runs three dispositions in order, first one that resolves it wins:
    1. lossless re-split — a multi-file unit over cap is greedy-packed by path into
       `-partN` continuation units, each measured <= cap; NO hunk is dropped and NO
       content is truncated (more units is the only cost);
    2. context slim — only for an atomic residue (one file left, never split mid-file):
       the DESCRIPTIVE blocks (ann_ctx / sym_ctx) are truncated to module-constant caps,
       visibly marked in the slice and recorded in `slimmed{}`. Evidence anchors are NEVER
       truncated: diff bodies, the "Files in this unit" list, the per-hunk `@@` locator
       headers and the header fields all stay intact;
    3. fail-loud, zero dispatch — still over cap -> exit 2 naming the unit_id, its cap,
       the measured bytes and the largest contributing file, BEFORE any slice file or
       grouping.json is written (zero side effects; fanout_runner --tier sdr passes exit 2
       through verbatim, so "nothing on disk to consume" == "no subagent spawned").

Exclusion filter (deterministic closed set, applied BEFORE any grouping, both modes):
  test trees / build outputs / generated code / static assets / lockfiles / build
  scripts never become review units (the real-repo first run produced 401 units, most
  of them tests and artifacts). The whitelist ALWAYS wins: *.sql, *Mapper.xml,
  application*.yml, *.properties, logback*.xml are the six-dimension review face and
  are NEVER excluded, even under a build dir. Exclusion is never silent: stdout
  `excluded{count, by_reason{}}` + the report's honesty boundary disclose it, and
  --include-excluded is the one-flag fallback restoring the full review.

Slice file (written with newline="" so its bytes ARE the rendered text — the gate's
measurement and the artifact must not differ by a platform newline translation): per-unit
diff hunks (git default 3-line context) + file list + change types
(A/M/D/R) + routes. Draft path / markers: drafts live in `<checkpoints>/../drafts`
(deterministic sibling of the markers dir in the standard <run-dir>/ layout); slices in
--materialize. `pending[]` fields are ALL Path.resolve()-absolute and inside the repo
subtree (R5.3(b) fan-out path contract); `unit_id` is filesystem-safe (`/ \\ :` -> `_`,
NTFS ADS lesson) and unique (numeric suffix on collision).

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "<abs>", "base": "...", "branch": "...", "empty": bool,
   "total": N, "done": M, "failed": F, "counts": {"interface": I, "standalone": S},
   "pending": [unit...], "offset": 0, "limit": K}
  unit = {unit_id, input_path, draft_path, done_marker, failed_marker, kind, route,
          unit_bytes, chain (interface units in codegraph mode; standalone/off = [])}
The same JSON is written to `<checkpoints>/../grouping.json` (the run's enumeration
record; fanout plan artifact + `--check` input).

Zero diff (the two refs are identical) -> exit 0, empty:true, pending:[] (the orchestrator
spawns no subagent and still renders a "no changes" report).

Resume: units with an existing `.done` marker are skipped (no re-materialization, excluded
from pending); `.failed` units are terminal (excluded, counted). `--resume` is accepted as
call-shape parity — disk markers are ALWAYS the truth source.

Exit codes (R5.3b): 0 ok (incl. empty) · 1 input error (--repo missing/not a dir) ·
2 misuse (argparse / bad budget) or GATE refusal (not a git repo, base/branch ref missing,
git command failed — fail-loud + stderr recipe; fanout_runner passes exit 2 through
verbatim, NEVER into a re-dispatch loop). `--check <run-dir>`: validates grouping.json +
slices + markers self-consistency (paths absolute + in subtree, exactly one terminal
marker or pending) and, when the run record carries a `budget{}`, that every pending
unit's `unit_bytes` is within its applicable cap and `slimmed{}` is well formed
(absent = old record, assertion skipped, still exit 0); violations exit 2.

Call-chain grouping (optional, codegraph-gated): when `<repo>/.codegraph/` exists AND a
`codegraph` binary is on PATH (env override MGH_CODEGRAPH_BIN for tests/operators), the
changed-method symbol set (deterministic local scan: annotations + method-decl brace
extent) is queried with `codegraph callees/callers --json` and the returned call edges
drive route-anchored downstream closures — every route method's closure becomes ONE
interface unit carrying the whole changed chain's hunks (controller + changed
service/dao), so cross-layer judgement (authz + SQL + validation) stays inside a single
subagent slice. Upstream anchoring: a changed symbol with no changed-route owner walks
the CALLER edges (which codegraph already returned for the unchanged endpoints — kept,
not dropped) up <=2 hops; a route method found on the way (deterministic local
annotation scan of the caller's branch file) absorbs the symbol into its interface
unit, whose slice carries a bounded upstream-route source snippet. Shared-chain merge:
within the SAME controller file, routes whose downstream changed-symbol reach sets are
equal or subsets merge into one interface unit (`route` = semicolon-joined). Across
controller files routes stay split (hunks repeat per referencing slice; renderer dedups).
An interface unit past --max-interface-bytes (default 256KB) is deterministically split
into `-partN` units per route group. Chain materialization: every interface unit in
codegraph mode carries `chain[]` — the deterministic node projection of its route
anchor(s) down the ALREADY-RETURNED call edges (zero new codegraph queries; the
unchanged-downstream edges the changed-set filter previously dropped are consumed
here). Nodes: {fqn_short, label, file, line, change: changed|unchanged|external,
route?, branch_of?}; branch_of = host node index (fan-out, never a tree); dao methods
get a mapper-XML terminal node (change=external) from one deterministic repo *.xml
scan (namespace last segment = class stem ∧ statement id = method). Standalone units
and codegraph-off runs carry chain=[] (structure always present). Java residual files
no anchor/closure claims fall
to directory clustering + --max-standalone-bytes (same as non-java residuals — one unit
per file was reverted after the real-repo 401-unit run). No codegraph (or every query
failing) degrades to the annotation+directory grouping below — byte-identical to the
no-codegraph baseline. stdout carries `codegraph: true|false` (whether this run used
call-chain grouping) plus `codegraph_stats{...}` (capture diagnostics; all-zero but
present when off). Probe failure prints its reason (no .codegraph dir / no binary) to
stderr.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/re/shutil/subprocess/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Shared marker predicate (single source of the marker-path rule, imported by the
# resume reader too — a second copy of the concatenation is how "enumerator says
# pending while disk holds a marker" re-dispatch loops are born).
from sdr_tier import (codegraph_available, codegraph_bin,  # noqa: E402
                      codegraph_probe_reason, forward_done_ids,
                      forward_failed_ids, forward_marker_paths)

DEFAULT_MAX_STANDALONE_BYTES = 64 * 1024  # 64KB merge cap for standalone clusters
DEFAULT_MAX_INTERFACE_BYTES = 256 * 1024  # 256KB split cap for interface units

# Level-2 (context slim) caps for an atomic residue that is still over budget. Module
# constants on purpose: the real levers stay --max-standalone-bytes / --max-interface-bytes,
# so the CLI contract surface does not grow (the truncation limits are not a user knob).
# These are RESCUE floors, not comfort levels — a context block smaller than its cap cannot
# rescue anything, so the cap is the size above which truncation starts to buy back budget.
# Everything the reviewer cites (diff body, locators, file list) survives regardless, and
# the file list still names every file, so a truncated block costs addressing comfort, not
# coverage. Keep them small enough to be reachable on a real residue.
SLIM_ANN_CTX_MAX_BYTES = 1024   # annotation/upstream-route context block
SLIM_SYM_CTX_MAX_BYTES = 512    # per-file symbol table

CODEGRAPH_LIMIT = 500    # callees/callers --limit: raise well above the CLI default 20 so
# a real changed-set edge is not truncated away behind unrelated same-name callers.
CODEGRAPH_TIMEOUT = 20   # per-query subprocess timeout; a hang degrades to no edges
# The index dir name and the availability predicate live in `sdr_tier` (shared with
# `sdr_context.py`, which writes the run's codegraph signal) — see the import above.

# Upstream anchoring: BFS depth cap over the caller edges (2 hops, visited-guarded).
ANCHOR_MAX_HOPS = 2
# Bounded route-method source snippet in an upstream-anchored slice (~60 lines).
UPSTREAM_ROUTE_MAX_LINES = 60

# --- exclusion filter (deterministic closed set; the whitelist ALWAYS wins) ---
#
# Order matters: _EXCLUDE_WHITELIST_RX is checked FIRST — *.sql / *Mapper.xml /
# application*.yml / *.properties / logback*.xml are the six-dimension review face
# (SQL injection / sensitive data / config authz) and standalone clustering already
# makes them cheap, so they are NEVER excluded even under a build directory.
_EXCLUDE_WHITELIST_RX = re.compile(
    r"(?:^|/)[^/]*\.sql$"
    r"|[^/]*Mapper\.xml$"
    r"|application[^/]*\.ya?ml$"
    r"|(?:^|/)[^/]*\.properties$"
    r"|logback[^/]*\.xml$")
_EXCLUDE_RULES: list[tuple[str, "re.Pattern[str]"]] = [
    # test trees (java `src/test/java` covered by the src/test/ segment; python/frontend
    # `tests/` collected too) + test-style file names
    ("test-tree", re.compile(r"(?:^|/)src/test/"      # java: src/test/java/...
                             r"|(?:^|/)(?:tests?|__tests__)/"
                             r"|[^/]*Tests?\.java$"
                             r"|[^/]*IT\.java$")),
    # build outputs (any depth)
    ("build-output", re.compile(r"(?:^|/)(?:target|build|out|dist)(?:/|$)")),
    # generated code
    ("generated", re.compile(r"(?:^|/)(?:generated|generated-sources)(?:/|$)")),
    # static assets & third-party binaries (min.* bundles / sourcemaps included)
    ("static-asset", re.compile(r"\.(?:png|jpe?g|gif|ico|svg|webp|bmp|woff2?|ttf|otf|eot"
                                r"|map|pdf|zip|gz|jar|class)$"
                                r"|\.(?:min\.(?:js|css))$")),
    # lockfiles
    ("lockfile", re.compile(r"(?:^|/)(?:package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$")),
    # build scripts
    ("build-script", re.compile(r"(?:^|/)(?:pom\.xml|build\.gradle(?:\.kts)?"
                                r"|settings\.gradle(?:\.kts)?|mvnw(?:\.cmd|\.bat)?"
                                r"|gradlew(?:\.bat)?)$")),
]


def _exclude_reason(rel: str) -> str | None:
    """Reason label when the file is in the closed exclusion set, else None. The
    whitelist is checked first and always wins (review-face files stay in)."""
    p = rel.replace("\\", "/")
    if _EXCLUDE_WHITELIST_RX.search(p):
        return None
    for reason, rx in _EXCLUDE_RULES:
        if rx.search(p):
            return reason
    return None

# Class-level controller markers (branch file content scan).
_CONTROLLER_RX = re.compile(r"@(?:RestController|Controller)\b")
# Class-level base route: @RequestMapping("...") / @RequestMapping(value="...")
RequestMapping_RX = re.compile(
    r'@(?:RequestMapping)\s*\(\s*(?:value\s*=\s*)?"([^"]*)"')
_CLASS_DECL_RX = re.compile(r"\b(?:public\s+|final\s+|abstract\s+)*class\s+\w+")
# Method-level mapping annotations -> (annotation, path-arg-or-None). @RequestMapping is
# method-level ONLY when a method declaration follows within the look-ahead window.
_METHOD_MAPPING_RX = re.compile(
    r'@((?:Get|Post|Put|Delete|Patch)Mapping|RequestMapping|Path|GET|POST|PUT|DELETE)'
    r'(?:\s*\(\s*(?:value\s*=\s*)?"([^"]*)"[^)]*\)?)?')
_METHOD_DECL_RX = re.compile(r"\b(?:public|protected|private)\s+[\w<>\[\],.\s]+\s+\w+\s*\(")
_METHOD_LOOKAHEAD = 12   # lines between annotation and its method declaration
_CLASS_LOOKBACK = 10     # lines above the class declaration for the base-route scan

# Permission/authorization annotations worth surfacing as class-level context in a
# call-chain interface slice (so the reviewer sees the authz gate next to the route).
_PERM_ANNO_RX = re.compile(
    r"@(?:PreAuthorize|PostAuthorize|Secured|RolesAllowed|RequiresPermissions|"
    r"SaCheckPermission|SaCheckLogin|RequiresAuthentication|PermitAll|DenyAll)\b")

INTERFACE_EXTS = (".java",)


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(unit_id: str) -> str:
    """Filesystem-safe name (`/ \\ :` -> `_`; NTFS ADS lesson — a `:` in a filename is a
    alternate data stream separator)."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _gate(repo: Path, base: str, branch: str) -> None:
    """Fail-loud gate (exit 2 + recipe): not a git repo / ref missing. A gate refusal is
    'do not enter this run', never a unit crash."""
    if not (repo / ".git").exists() and _git(repo, "rev-parse", "--git-dir").returncode != 0:
        _eprint(f"error: not a git repository: {repo}\n"
                f"recipe: pass --repo <absolute git repo root>; /mgh-sdr reviews a "
                f"branch diff, so the target MUST be a git working tree.")
        sys.exit(2)
    for label, ref in (("--base", base), ("--branch", branch)):
        r = _git(repo, "rev-parse", "--verify", "--quiet", ref)
        if r.returncode != 0:
            _eprint(f"error: {label} ref not found in {repo}: {ref!r}\n"
                    f"recipe: list branches with `git branch -a` and re-run with an "
                    f"existing base/branch ref (defaults: --base master, --branch current).")
            sys.exit(2)


def _current_branch(repo: Path) -> str:
    r = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode != 0:
        _eprint(f"error: cannot resolve current branch in {repo}: {(r.stderr or '').strip()}")
        sys.exit(2)
    return r.stdout.strip()


# --- codegraph probe + call-edge acquisition (optional, D3) ------------------

def _cg_command(bin_path: str) -> list[str]:
    """How to exec the resolved binary: a .py/.pyw needs the interpreter (test seam);
    a .cmd/.bat needs cmd (npm shim on Windows); otherwise it is a native executable."""
    b = bin_path.lower()
    if b.endswith((".py", ".pyw")):
        return [sys.executable, bin_path]
    if b.endswith((".cmd", ".bat")):
        return ["cmd", "/c", bin_path]
    return [bin_path]


def _codegraph_available(repo: Path) -> bool:
    """Alias of the shared probe (kept as the local name this module's call sites
    use). The predicate itself lives in `sdr_tier` so the grouping decision and the
    run-config signal cannot be computed from different rules."""
    return codegraph_available(repo)


def _cg_query(repo: Path, sub: str, symbol: str) -> dict | None:
    """`codegraph <callers|callees> <symbol> --path <repo> --limit N --json` -> dict.

    ANY failure (no binary / nonzero exit / not-found info text / unparseable / timeout)
    returns None so the caller degrades per-symbol — never aborts the run."""
    bin_path = codegraph_bin()
    if not bin_path:
        return None
    cmd = _cg_command(bin_path) + [sub, symbol, "--path", str(repo),
                                   "--limit", str(CODEGRAPH_LIMIT), "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=CODEGRAPH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout or "")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _codegraph_probe_reason(repo: Path) -> str | None:
    """Alias of the shared probe reason (see `_codegraph_available`)."""
    return codegraph_probe_reason(repo)


def _cg_edges(repo: Path, key: str) -> tuple[set[str], set[str]]:
    """(callers_keys, callees_keys) for a bare symbol name. Entries (name, filePath)
    are folded to `filePath::name` keys here. Callers are kept VERBATIM including
    unchanged endpoints (upstream anchoring needs them; consumers match them against
    their own symbol set so extras are inert)."""
    callers: set[str] = set()
    callees: set[str] = set()
    for sub, acc in (("callers", callers), ("callees", callees)):
        data = _cg_query(repo, sub, key)
        if data is None:
            continue
        for e in data.get(sub, []) or []:
            if not isinstance(e, dict):
                continue
            name = e.get("name")
            fpath = e.get("filePath")
            if isinstance(name, str) and name and isinstance(fpath, str) and fpath:
                acc.add(f"{fpath.replace(chr(92), '/')}::{name}")
    return callers, callees


# --- diff parsing -----------------------------------------------------------

_FILE_HDR_RX = re.compile(r'^diff --git a/(.+?) b/(.+)$')
Binary_RX = re.compile(r"^Binary files .+ differ")

class FileDiff:
    __slots__ = ("path", "change_type", "hunks", "binary")

    def __init__(self, path: str, change_type: str):
        self.path = path
        self.change_type = change_type
        self.hunks: list[tuple[int, int, list[str]]] = []  # (new_start, new_count, lines)
        self.binary = False


def parse_diff(text: str) -> list[FileDiff]:
    """Parse a unified `git diff` body into per-file hunks (new-file line ranges)."""
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = _FILE_HDR_RX.match(ln)
        if m:
            path = m.group(2)
            change_type = "M"
            j = i + 1
            while j < len(lines) and not lines[j].startswith(("diff --git", "@@")) \
                    and not Binary_RX.match(lines[j]):
                if lines[j].startswith("new file mode"):
                    change_type = "A"
                elif lines[j].startswith("deleted file mode"):
                    change_type = "D"
                elif lines[j].startswith("rename from"):
                    change_type = "R"
                    path = m.group(2)
                j += 1
            cur = FileDiff(path, change_type)
            files.append(cur)
            i = j
            continue
        if Binary_RX.match(ln):
            if cur is not None:
                cur.binary = True
            i += 1
            continue
        hm = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", ln)
        if hm and cur is not None:
            start = int(hm.group(1))
            count = int(hm.group(2)) if hm.group(2) is not None else 1
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith(("diff --git", "@@")) \
                    and not Binary_RX.match(lines[i]):
                body.append(lines[i])
                i += 1
            cur.hunks.append((start, count, body))
            continue
        i += 1
    return files


# --- interface (java) analysis ----------------------------------------------

def _base_route(content: str) -> tuple[str, bool]:
    """(base route, is_controller) from the class-level annotation block."""
    lines = content.splitlines()
    is_ctrl = any(_CONTROLLER_RX.search(ln) for ln in lines[:80])
    base = ""
    for idx, ln in enumerate(lines):
        if _CLASS_DECL_RX.search(ln):
            for back in range(max(0, idx - _CLASS_LOOKBACK), idx):
                mm = RequestMapping_RX.search(lines[back])
                if mm:
                    base = mm.group(1)
            break
    return base, is_ctrl


def _method_mappings(content: str) -> list[tuple[int, str]]:
    """[(annotation_line_1based, method_path)] for method-level mapping annotations in the
    branch content. A mapping annotation counts as method-level iff a method declaration
    follows within _METHOD_LOOKAHEAD lines (class-level @RequestMapping has a class decl
    below, not a method decl)."""
    lines = content.splitlines()
    out = []
    for idx, ln in enumerate(lines):
        for m in _METHOD_MAPPING_RX.finditer(ln):
            anno, val = m.group(1), m.group(2) or ""
            window = "\n".join(lines[idx + 1: idx + 1 + _METHOD_LOOKAHEAD])
            if _METHOD_DECL_RX.search(window):
                path = val if val.startswith("/") and val else (f"/{val}" if val else "")
                out.append((idx + 1, path))
                break
    return out


def _hunk_intersects(hunk: tuple, lo: int, hi: int) -> bool:
    start, count, _ = hunk
    end = start + max(count, 1) - 1
    return not (end < lo or start > hi)


def _split_interface(path: str, content: str, hunks: list) -> list[tuple[str, list]]:
    """Interface file -> [(route, hunks)] (deterministic; unclaimed hunks keep a
    class-level unit so nothing is dropped from review)."""
    base, _is_ctrl = _base_route(content)
    methods = _method_mappings(content)
    claimed: list[tuple[str, list]] = []
    used: set[int] = set()
    for i, (anno_line, mpath) in enumerate(methods):
        hi = methods[i + 1][0] - 1 if i + 1 < len(methods) else len(content.splitlines())
        own = [h for j, h in enumerate(hunks) if _hunk_intersects(h, anno_line, hi)]
        if own:
            claimed.append((base + mpath, own))
            used.update(id(h) for h in own)
    rest = [h for h in hunks if id(h) not in used]
    if rest:
        claimed.append((base, rest))
    if not claimed:
        claimed = [(base, list(hunks))]
    return claimed


# --- deterministic java method-symbol scanner (call-chain mode) --------------

def _brace_end(lines: list[str], decl: int) -> int | None:
    """1-based end line of the method whose declaration starts at `decl` (1-based),
    brace-matched with a light lexer that ignores braces inside "..." / '...' /
    //- and /* */-comments. None = no opening brace (abstract/interface method or a
    declaration that never closes) -> not a body symbol."""
    depth, opened = 0, False
    in_str = in_ch = in_block_c = False
    for i in range(decl - 1, len(lines)):
        ln = lines[i]
        j = 0
        while j < len(ln):
            c = ln[j]
            if in_block_c:
                if c == "*" and j + 1 < len(ln) and ln[j + 1] == "/":
                    in_block_c = False
                    j += 2
                else:
                    j += 1
                continue
            if in_str:
                if c == "\\":
                    j += 2
                    continue
                if c == '"':
                    in_str = False
                j += 1
                continue
            if in_ch:
                if c == "\\":
                    j += 2
                    continue
                if c == "'":
                    in_ch = False
                j += 1
                continue
            if c == "/" and j + 1 < len(ln):
                nxt = ln[j + 1]
                if nxt == "/":
                    break   # line comment: the rest of THIS line is dead (state is
                            # per-line — a comment must not poison the next line)
                if nxt == "*":
                    in_block_c = True
                    j += 2
                    continue
            if c == '"':
                in_str = True
            elif c == "'":
                in_ch = True
            elif c == "{":
                depth += 1
                opened = True
            elif c == "}":
                depth -= 1
            j += 1
        if opened and depth <= 0:
            return i + 1
    return None


def _method_decl_lines(content: str) -> list[int]:
    """1-based declaration lines for accessor-style method/constructor signatures
    (public/protected/private [+ modifiers] + return type + name + `(`)."""
    out = []
    for idx, ln in enumerate(content.splitlines()):
        if _METHOD_DECL_RX.search(ln):
            out.append(idx + 1)
    return out


def _method_name_on_line(line: str) -> str | None:
    """Bare method name = the last identifier before the first '(' on the decl line."""
    head = line.split("(", 1)[0]
    m = re.search(r"([A-Za-z_$][\w$]*)\s*$", head.rstrip())
    return m.group(1) if m else None


def _anno_block(lines: list[str], decl: int, limit: int = 6) -> list[str]:
    """Contiguous annotation lines sitting directly above the declaration (mapping +
    permission annotations = the authz context of the method). Bounded."""
    block: list[str] = []
    for i in range(decl - 2, -1, -1):
        s = lines[i].strip()
        if s.startswith("@"):
            block.insert(0, s)
            if len(block) >= limit:
                break
        elif s == "":
            # a blank line stops the contiguous run (annotations sit tight on the decl)
            if block:
                break
            continue
        else:
            break
    return block


def _java_symbols(content: str) -> list[dict]:
    """Deterministic local symbol map of a branch-version java file:
    [{name, start(decl line), end(brace-close), route, ann:[@ lines]}].

    The no-codegraph fallback path needs these boundaries anyway, so they are ALWAYS
    computed here (single deterministic source); codegraph only supplies call edges.
    Route comes from a mapping annotation whose following declaration is this method
    (annotation -> next method decl within the look-ahead window)."""
    lines = content.splitlines()
    decls = _method_decl_lines(content)
    route_by_decl: dict[int, str] = {}
    for anno_line, path in _method_mappings(content):
        # a mapping annotation owns the NEAREST following declaration only (annotations
        # sit tight above their method); the look-ahead window in _method_mappings just
        # decides method-vs-class level, it must not bleed onto a later method.
        near = [d for d in decls if d > anno_line]
        if near:
            route_by_decl[min(near)] = path
    syms: list[dict] = []
    for d in decls:
        end = _brace_end(lines, d)
        name = _method_name_on_line(lines[d - 1])
        if end is None or not name:
            continue
        syms.append({"name": name, "start": d, "end": end, "route": route_by_decl.get(d, ""),
                     "ann": _anno_block(lines, d)})
    return syms


def _owning_symbol(syms: list[dict], hline: int | None) -> int | None:
    """Index of the innermost symbol whose body contains the hunk's anchor new-file
    line; None = file-level change (class annotation / import / field / no anchor)."""
    if hline is None:
        return None
    best, best_span = None, None
    for i, s in enumerate(syms):
        if s["start"] <= hline <= s["end"]:
            span = s["end"] - s["start"]
            if best_span is None or span < best_span:
                best, best_span = i, span
    return best


def _owning_hunk_symbol(syms: list[dict], hunk: tuple) -> int | None:
    """Ownership via the hunk's anchor candidates: the FIRST added line that falls
    inside a symbol wins (a hunk's leading '+' lines may be javadoc/blank between
    methods — the anchor must not strand on them when a later '+' line carries the
    actual new method); falls back to the first added line (file-level change)."""
    cands = _hunk_anchor_candidates(hunk)
    for hline in cands:
        o = _owning_symbol(syms, hline)
        if o is not None:
            return o
    return None


def _hunk_anchor_candidates(hunk: tuple) -> list[int]:
    """New-file positions of every added ('+') line in the hunk, in order (a
    leading 'add blank/javadoc' line and the actual code line both appear)."""
    start, _count, body = hunk
    cur, out = start, []
    for line in body:
        pre = line[:1]
        if pre in (" ", "+"):
            if pre == "+":
                out.append(cur)
            cur += 1
        # '-' consumes no new-file line; '\' no-newline marker is skipped
    return out


def _hunk_anchor_line(hunk: tuple) -> int | None:
    """New-file line anchoring the ACTUAL edit in a hunk, not the git 3-line context:
    the first added ('+') line's new-file position when the hunk adds anything; else the
    last new-file context line (a deletion-only hunk lives beside that context). Diff
    context that merely bleeds around an unrelated method must NOT attribute the change
    to that method — this is what separates a real body edit from a trailing comment."""
    start, _count, body = hunk
    cur, last_new = start, None
    for line in body:
        pre = line[:1]
        if pre in (" ", "+"):
            if pre == "+":
                return cur
            last_new = cur
            cur += 1
        # '-' consumes no new-file line; '\' no-newline marker is skipped
    return last_new


# --- clustering / enumeration -----------------------------------------------

def _dir_of(rel: str) -> str:
    p = rel.replace("\\", "/")
    return p.rsplit("/", 1)[0] if "/" in p else "."


def _cluster_standalone(files: list[FileDiff], cap: int,
                        gate: _SliceGate) -> list[tuple[str, list[FileDiff]]]:
    """Directory-cluster the standalone files; merge sorted dir groups while the merged
    slice MEASURES within cap bytes (`gate` = the renderer that materializes it, never a
    parallel estimator — the header / file-list / per-hunk locator lines are exactly what
    the old `Σ(diff lines) + 64/file` estimate missed). Route order and the "never split
    mid-file" rule are unchanged. A single oversize file stays its own unit here; a
    MULTI-file unit still over cap is re-split by the gate (level 1)."""
    by_dir: dict[str, list[FileDiff]] = {}
    for f in files:
        by_dir.setdefault(_dir_of(f.path), []).append(f)

    def _size(fs: list[FileDiff], name: str) -> int:
        return gate.bytes(_probe_unit(_safe_name(name) or "unit", "standalone", "", fs))

    buckets: list[tuple[str, list[FileDiff]]] = []
    for d in sorted(by_dir):
        if buckets:
            name, members = buckets[-1]
            merged = members + by_dir[d]
            prefix = _common_prefix(_dir_of(m.path) for m in merged)
            if _size(merged, prefix) <= cap:
                buckets[-1] = (prefix, merged)
                continue
        buckets.append((d, list(by_dir[d])))
    return buckets


def _common_prefix(dirs) -> str:
    parts = [d.split("/") for d in dirs]
    common: list[str] = []
    for level in zip(*parts):
        if all(p == level[0] for p in level):
            common.append(level[0])
        else:
            break
    return "/".join(common) if common else "mixed"


def _sel_hunks_size(fd: FileDiff, sel: list[int]) -> int:
    """Diff-text byte weight of a file restricted to `sel` hunk indices. This is NOT the
    slice budget judge (that is `_SliceGate.bytes`, measured on the rendered slice); it is
    only used to report the largest contributing file on a gate refusal."""
    return sum(len(l) + 1 for i, (_s, _c, ls) in enumerate(fd.hunks)
               for l in ls if i in sel)


def _cluster_standalone_sel(items: list[tuple[FileDiff, list[int]]], cap: int,
                            gate: _SliceGate, sym_of=None
                            ) -> list[tuple[str, list[tuple[FileDiff, list[int]]]]]:
    """Directory-cluster residual (partially-claimed) files by their selected hunks;
    merge sorted dir groups while the merged slice MEASURES within cap (`gate`). Mirrors
    `_cluster_standalone` but honours per-file hunk selection (a file split across an
    interface chain and a standalone leftover contributes only its leftover hunks), and
    `sym_of` — the per-file symbol table the java-residual caller will attach — so the
    probe measures the unit that will actually be materialized."""
    by_dir: dict[str, list[tuple[FileDiff, list[int]]]] = {}
    for fd, sel in items:
        by_dir.setdefault(_dir_of(fd.path), []).append((fd, sel))

    def _size(members: list[tuple[FileDiff, list[int]]], name: str) -> int:
        selmap = {fd.path: sel for fd, sel in members}
        sym = sym_of(members) if sym_of is not None else None
        return gate.bytes(_probe_unit(_safe_name(name) or "unit", "standalone", "",
                                      [fd for fd, _ in members], selmap, None, sym))

    buckets: list[tuple[str, list[tuple[FileDiff, list[int]]]]] = []
    for d in sorted(by_dir):
        if buckets:
            name, members = buckets[-1]
            merged = members + by_dir[d]
            prefix = _common_prefix([_dir_of(fd.path) for fd, _ in merged])
            if _size(merged, prefix) <= cap:
                buckets[-1] = (prefix, merged)
                continue
        buckets.append((d, list(by_dir[d])))
    return buckets


class Unit:
    __slots__ = ("unit_id", "kind", "route", "files", "hunk_sel", "slice_bytes",
                 "ann_ctx", "sym_ctx", "chain")

    def __init__(self, unit_id: str, kind: str, route: str,
                 files: list[FileDiff], hunk_sel: dict | None = None,
                 ann_ctx: list[str] | None = None,
                 sym_ctx: list[str] | None = None):
        self.unit_id = unit_id
        self.kind = kind
        self.route = route
        self.files = files
        self.hunk_sel = hunk_sel or {}   # file path -> list of hunk indices (interface only)
        self.slice_bytes = 0
        self.ann_ctx = ann_ctx or []     # annotation-context lines (call-chain interface only)
        self.sym_ctx = sym_ctx or []     # per-file symbol table (merged standalone clusters)
        self.chain: list[dict] = []      # materialized call chain (interface+codegraph only)


def _sym_table(syms: list[dict], limit: int = 40) -> list[str]:
    """Bounded per-file symbol table lines (method name + line extent) for merged
    standalone slices — the subagent keeps method-level addressing without a full read."""
    out = []
    for s in syms[:limit]:
        out.append(f"  {s['name']}  lines {s['start']}-{s['end']}"
                   + (f"  route {s['route']}" if s["route"] else ""))
    if len(syms) > limit:
        out.append(f"  ... (+{len(syms) - limit} more symbols)")
    return out


def _id_factory(seen_ids: set[str]):
    """Unit-id allocator: filesystem-safe stem (NTFS ADS lesson) + a numeric suffix on
    collision. Shared by the grouping builders AND the gate's level-1 re-split, so a
    split continuation can never collide with an id that already exists."""
    def _uid(raw: str) -> str:
        base = _safe_name(raw) or "unit"
        cand, n = base, 1
        while cand in seen_ids:
            n += 1
            cand = f"{base}-{n}"
        seen_ids.add(cand)
        return cand
    return _uid


def _probe_unit(unit_id: str, kind: str, route: str, files, hunk_sel=None,
                ann_ctx=None, sym_ctx=None, chain=None) -> Unit:
    """A candidate Unit used for MEASURING only (it becomes a real unit when accepted).
    The identity passed here MUST be the one the candidate carries if accepted: the
    renderer prints `unit_id`/`route`, so a stand-in identity would make the packing
    decision and the pre-write gate disagree by a few bytes. Copies every list — probing
    MUST NOT mutate the accumulator it is measured against."""
    u = Unit(unit_id, kind, route, list(files), dict(hunk_sel or {}),
             list(ann_ctx or []), list(sym_ctx or []))
    u.chain = list(chain or [])
    return u


class _SliceGate:
    """The slice byte gate. Its one measurement is `_render_slice(...)` -> utf-8 byte
    length: the SAME renderer that materializes the slice, so the number the packing
    decision uses, the number `pending[].unit_bytes` carries and the number `--check`
    asserts are one number, not three estimates. A renderer change moves the gate with it."""

    __slots__ = ("repo", "base", "branch", "raw_text")

    def __init__(self, repo: Path, base: str, branch: str, raw_text: str):
        self.repo, self.base, self.branch, self.raw_text = repo, base, branch, raw_text

    def text(self, unit: Unit) -> str:
        return _render_slice(self.repo, self.base, self.branch, unit, self.raw_text)

    def bytes(self, unit: Unit) -> int:
        return len(self.text(unit).encode("utf-8"))


def _build_units(repo: Path, file_diffs: list[FileDiff], branch: str,
                 cap: int, gate: _SliceGate) -> list[Unit]:
    units: list[Unit] = []
    _uid = _id_factory(set())

    interfaces: list[FileDiff] = []
    standalone: list[FileDiff] = []
    for fd in file_diffs:
        if fd.change_type != "D" and fd.path.lower().endswith(INTERFACE_EXTS):
            content = _branch_content(repo, fd.path, branch)
            if content is not None and (_base_route(content)[1] or _method_mappings(content)):
                interfaces.append(fd)
                base, _ = _base_route(content)
                for route, own in _split_interface(fd.path, content, fd.hunks):
                    idxs = [fd.hunks.index(h) for h in own]
                    units.append(Unit(_uid(f"{_stem(fd.path)}::{route or _stem(fd.path)}"),
                                      "interface", route, [fd], {fd.path: idxs}))
                continue
        standalone.append(fd)

    for d, members in _cluster_standalone(standalone, cap, gate):
        units.append(Unit(_uid(d), "standalone", "", members, None))
    return units


def _route_method_snippet(repo: Path, path: str, branch: str, name: str) -> list[str]:
    """Bounded upstream-route context: the (possibly unchanged) route method's annotation
    block + brace body, ~UPSTREAM_ROUTE_MAX_LINES lines with a truncation note. Local
    deterministic scan (same boundary source as the symbol map) — no extra queries."""
    content = _branch_content(repo, path, branch)
    if not content:
        return []
    lines = content.splitlines()
    routes = {d for d, _p in _method_mappings(content)}
    decls = [d for d in _method_decl_lines(content)
             if _method_name_on_line(lines[d - 1]) == name]
    decls.sort(key=lambda d: (d not in routes, d))   # prefer the mapping-annotated one
    for d in decls:
        end = _brace_end(lines, d)
        hi = min(end if end else d + UPSTREAM_ROUTE_MAX_LINES,
                 d + UPSTREAM_ROUTE_MAX_LINES)
        snippet = list(_anno_block(lines, d, limit=10))
        snippet += lines[d - 1:hi]
        if end and end > hi:
            snippet.append(f"... (truncated, method continues to line {end})")
        return snippet
    return []


def _anchor_upstream(repo: Path, branch: str, start_key: str, changed: dict,
                     caller_edges: dict[str, set[str]]) -> tuple[str, str, str] | None:
    """Walk caller edges up <=ANCHOR_MAX_HOPS from an unanchored changed symbol; the
    first waypoint that scans as a route method wins -> (route_key, route_str, file).
    Route detection = deterministic local annotation scan of the waypoint's branch file
    (`_java_symbols`, same boundary source everywhere). Waypoints are NOT expanded
    downward (caller direction only) and the visited set guards cycles. None = no route
    within the hop budget (the symbol falls to residual)."""
    visited = {start_key}
    frontier = [start_key]
    for _hop in range(ANCHOR_MAX_HOPS):
        nxt: list[str] = []
        for k in frontier:
            for up in sorted(caller_edges.get(k, ())):
                if up in visited:
                    continue
                visited.add(up)
                fpath, _sep, name = up.rpartition("::")
                if not fpath:
                    continue
                rec = changed.get(up)
                if rec is not None and rec["route"]:
                    return up, rec["route"], rec["file"]
                content = _branch_content(repo, fpath, branch)
                if content is None:
                    continue
                base = _base_route(content)[0]
                for s in _java_symbols(content):
                    if s["name"] == name and s["route"]:
                        return up, _route_str(base, s["route"]), fpath
                nxt.append(up)   # not a route method: keep walking callers only
        frontier = nxt
    return None


def _route_str(base: str, path: str) -> str:
    if not base:
        return path
    if not path:
        return base
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _fqn_short(path: str, name: str) -> str:
    """FQN short form = bare class name (or file name) . method
    (`com/x/y/controller/OrderController.java` + `submit` -> `OrderController.submit`;
    the full package path is recovered from the `file` column when disambiguation is
    needed). Non-java paths keep the file name; `name` empty -> bare class/file
    short form."""
    p = path.replace("\\", "/")
    if p.endswith(".java"):
        base = p[:-len(".java")].rsplit("/", 1)[-1]
    else:
        base = p.rsplit("/", 1)[-1]
    return f"{base}.{name}" if name else base


_MAPPER_NS_RX = re.compile(r'<mapper[^>]*namespace="([^"]*)"')
_MAPPER_STMT_RX = re.compile(r'<(?:insert|select|update|delete)\b[^>]*id="([^"]*)"')


def _mapper_index(repo: Path) -> dict:
    """One deterministic pass over the repo's `*.xml` (exclusion-set respected):
    {(namespace-last-segment, statement id): first xml repo-relative path}. The
    namespace's LAST segment must equal the dao class name (file stem) — `src/main/java`
    dir prefixes are not package segments, so a suffix match on the full dir-derived FQN
    would never hit real repos. XML is not in the codegraph graph: this index powers the
    deterministic mapper terminal hop (not a new query)."""
    idx: dict[tuple[str, str], str] = {}
    for xml in sorted(repo.rglob("*.xml")):
        rel = xml.relative_to(repo).as_posix()
        if _exclude_reason(rel):
            continue
        try:
            text = xml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nsm = _MAPPER_NS_RX.search(text)
        if nsm is None:
            continue
        stem = nsm.group(1).rsplit(".", 1)[-1]
        for sm in _MAPPER_STMT_RX.finditer(text):
            key = (stem, sm.group(1))
            if key not in idx or rel < idx[key]:
                idx[key] = rel
    return idx


def _key_class_method(key: str) -> tuple[str, str] | None:
    """`filePath::method` -> (java class stem, method) for .java keys; None otherwise
    (non-java files never get a mapper hop)."""
    fpath, _sep, name = key.rpartition("::")
    p = fpath.replace("\\", "/")
    if not p.endswith(".java") or not name:
        return None
    return p.rsplit("/", 1)[-1][:-len(".java")], name


def _chain_nodes(repo: Path, branch: str, anchors: list[tuple[str, str]],
                 changed: dict, down: dict[str, list[str]],
                 mapper_idx: dict) -> list[dict]:
    """Deterministic chain projection for ONE interface unit: the route method(s) (or
    the analysis-reachable unchanged upstream anchors) down the ALREADY-RETURNED call
    edges (`down`: raw-edge adjacency incl. the unchanged-downstream edges the
    changed-set filter previously dropped — zero new codegraph queries). Node order =
    linear main chain from the first anchor; a fan-out renders each child after the
    first as a branch (`branch_of` = host node index); a second anchor (merged
    multi-route unit) re-enters as a branch of the first entry. Nodes: {fqn_short,
    label, file, line, change: changed|unchanged|external, route?, branch_of?}. The
    unchanged upstream route entry carries the route + change=unchanged; mapper XML
    terminals (deterministic completion via `mapper_idx`) branch off their dao node."""
    content_cache: dict[str, str | None] = {}
    decl_cache: dict[tuple[str, str], int | None] = {}

    def _decl_line(fpath: str, name: str) -> int | None:
        ck = (fpath, name)
        if ck in decl_cache:
            return decl_cache[ck]
        if fpath not in content_cache:
            content_cache[fpath] = _branch_content(repo, fpath, branch)
        c = content_cache[fpath]
        out: int | None = None
        if c:
            lines = c.splitlines()
            for d in _method_decl_lines(c):
                if _method_name_on_line(lines[d - 1]) == name:
                    out = d
                    break
        decl_cache[ck] = out
        return out

    nodes: list[dict] = []
    index_of: dict[str, int] = {}

    def _emit(key: str, host_idx: int | None, via_route: str) -> int:
        existing = index_of.get(key)
        if existing is not None:
            return existing
        fpath, _sep, name = key.rpartition("::")
        rec = changed.get(key)
        ch = (rec["file"] if rec is not None else fpath) or fpath
        node = {"fqn_short": _fqn_short(ch, name),
                "label": f"{_stem(ch)}.{name}" if ch else name,
                "file": ch, "line": _decl_line(ch, name),
                "change": "changed" if rec is not None else "unchanged"}
        if via_route:
            node["route"] = via_route
        if host_idx is not None:
            node["branch_of"] = host_idx
        nodes.append(node)
        index_of[key] = len(nodes) - 1
        return index_of[key]

    def _resolve_children(children: list[str]) -> list[str]:
        """Interface/impl resolution (impl preferred): same-NAME siblings where exactly
        one file is interface-style (`I` + uppercase stem, e.g. IOrderService.java) keep
        only the impl twin; unresolvable same-name pairs (neither interface-style) stay
        BOTH (chain fidelity — the report's file column disambiguates)."""
        by_name: dict[str, list[str]] = {}
        for e in children:
            fpath, _sep, name = e.rpartition("::")
            by_name.setdefault(name, []).append(e)
        out: list[str] = []
        for name, keys in by_name.items():
            if len(keys) > 1:
                non_iface = [k for k in keys
                             if not (len(_stem(k.rpartition("::")[0])) > 1
                                     and _stem(k.rpartition("::")[0])[0] == "I"
                                     and _stem(k.rpartition("::")[0])[1:2].isupper())]
                if 0 < len(non_iface) < len(keys):
                    out.extend(sorted(non_iface))
                    continue
            out.extend(sorted(keys))
        return sorted(out)

    for n, (ak, aroute) in enumerate(anchors):
        # first anchor = the entry (no branch_of); a merged unit's other anchors
        # re-enter as branches of the entry (the route strings carry the full list)
        _emit(ak, 0 if n > 0 else None, aroute)
        if ak not in index_of:
            continue
        seen = {ak}
        frontier: list[tuple[str, int]] = [(ak, index_of[ak])]
        while frontier:
            key, idx = frontier.pop(0)
            children = _resolve_children(down.get(key) or [])
            for ci, e in enumerate(children):
                if e in seen:
                    continue
                seen.add(e)
                child = _emit(e, idx if ci > 0 else None, "")
                frontier.append((e, child))
            # mapper XML terminal hop (deterministic; every java node is a potential dao)
            cm = _key_class_method(key)
            term_rel = mapper_idx.get(cm) if cm is not None else None
            if term_rel is not None:
                tkey = f"xml::{cm[0]}::{cm[1]}"
                if tkey not in index_of:
                    fname = term_rel.rsplit("/", 1)[-1]
                    nodes.append({"fqn_short": fname,
                                  "label": f"{fname}:{cm[1]}",
                                  "file": term_rel, "line": None,
                                  "change": "external", "branch_of": idx})
                    index_of[tkey] = len(nodes) - 1
    return nodes


def _split_interface_budget(hosts: list[dict], iface_cap: int, uid,
                            gate: _SliceGate) -> list[Unit]:
    """Enforce --max-interface-bytes. A host's constituents are its per-route bodies
    (files + hunk selection + ann); under budget they emit as ONE unit (';'-joined
    route); over budget they greedy-pack (route-sorted, deterministic) into `-partN`
    units, each carrying its own route string + independent slice path. A single
    constituent over the cap is further split across its files (sorted, greedy).
    EVERY decision here is the MEASURED slice size (`gate`), not a sum of per-file
    estimates: an accumulator's size is re-measured as a whole, because the rendered
    union is not the sum of its parts (one shared header, and a file shared by two
    constituents renders once). A part still over cap after this (one oversize file,
    never split mid-file) is the atomic residue the gate's level 2/3 handles. The host's
    materialized chain rides EVERY part (a unit-level record, not a slice-budget body)."""
    out: list[Unit] = []

    def _fill(u: Unit, con: dict) -> None:
        for fd in con["files"]:
            if fd not in u.files:
                u.files.append(fd)
        for p, idxs in con["selmap"].items():
            u.hunk_sel[p] = sorted(set(u.hunk_sel.get(p, ())) | set(idxs))
        if con["ann"]:
            u.ann_ctx.extend(con["ann"])

    def _join(acc: Unit, con: dict) -> Unit:
        """Probe: `acc` with `con` absorbed. Non-mutating — the accumulator is only ever
        advanced once the measurement says the joint unit still fits."""
        probe = _probe_unit(acc.unit_id, acc.kind, acc.route, acc.files, acc.hunk_sel,
                            acc.ann_ctx, acc.sym_ctx, acc.chain)
        if con["route"] and con["route"] not in probe.route.split(";"):
            probe.route = f"{probe.route};{con['route']}"
        _fill(probe, con)
        return probe

    def _with_file(acc: Unit, fd: FileDiff, sel: list[int]) -> Unit:
        """Probe: `acc` with one more (file, hunk subset) absorbed — the file-level twin of
        `_join` (same non-mutating discipline)."""
        probe = _probe_unit(acc.unit_id, acc.kind, acc.route, acc.files, acc.hunk_sel,
                            acc.ann_ctx, acc.sym_ctx, acc.chain)
        if fd not in probe.files:
            probe.files.append(fd)
        probe.hunk_sel[fd.path] = sorted(
            set(probe.hunk_sel.get(fd.path, ())) | set(sel))
        return probe

    def _new_part(host: dict, route: str, ann) -> Unit:
        u = Unit(uid(f"{host['base_id']}-part{len(parts) + 1}"),
                 "interface", route, [], {}, list(ann))
        u.chain = host.get("chain", [])
        return u

    for host in hosts:
        cons = host["constituents"]
        whole = host["unit"]
        for c in cons:
            _fill(whole, c)
        if gate.bytes(whole) <= iface_cap:
            out.append(whole)
            continue
        # over budget: greedy-pack constituents in route order into -partN units
        parts: list[Unit] = []
        acc: Unit | None = None
        for c in sorted(cons, key=lambda c: c["route"]):
            if c["bytes"] > iface_cap:
                # single constituent over cap: flush, then split it across its files
                if acc is not None:
                    parts.append(acc)
                    acc = None
                for fd in sorted(c["files"], key=lambda f: f.path):
                    sel = c["selmap"].get(fd.path, list(range(len(fd.hunks))))
                    if acc is not None and gate.bytes(
                            _with_file(acc, fd, sel)) > iface_cap:
                        parts.append(acc)
                        acc = None
                    if acc is None:
                        acc = _new_part(host, c["route"], c["ann"])
                    acc.files.append(fd)
                    acc.hunk_sel[fd.path] = sorted(
                        set(acc.hunk_sel.get(fd.path, ())) | set(sel))
                if acc is not None:
                    parts.append(acc)
                    acc = None
                continue
            if acc is not None and gate.bytes(_join(acc, c)) > iface_cap:
                parts.append(acc)
                acc = None
            if acc is None:
                acc = _new_part(host, c["route"], c["ann"])
            else:
                _fill(acc, c)
        if acc is not None:
            parts.append(acc)
        out.extend(parts)
    return out


def _build_units_callchain(repo: Path, file_diffs: list[FileDiff], branch: str,
                           cap: int, iface_cap: int,
                           stats: dict, gate: _SliceGate) -> list[Unit]:
    """codegraph-gated call-chain grouping. Only called when the probe succeeded
    (`_codegraph_available`); every codegraph failure degrades per-symbol.

    Changed java methods (deterministic local symbol scan) are queried for call
    edges; every changed ROUTE method's downstream closure becomes one interface unit
    (route method + changed service/dao it reaches) with the chain's hunks merged into
    one slice. Upstream anchoring (<=2 caller hops): a changed symbol no changed route
    owns walks the ALREADY-RETURNED caller edges (unchanged endpoints kept) to an
    unchanged route method, whose interface unit absorbs it (slice carries a bounded
    route-method snippet; `anchors_upstream` counts anchored symbols). Shared-chain
    merge: within the SAME controller file, routes whose downstream changed-symbol
    reach sets are equal or subsets merge into one unit (`route` = ';'-joined;
    `chain_merged` counts the absorbed routes); across controller files they stay
    split. An interface unit past `iface_cap` is deterministically split into
    `-partN` units per route group. Java residual files (no anchor/closure claim) fall
    to directory clustering + `cap` — same path as non-java residuals, with a bounded
    per-file symbol table in the slice header."""
    units: list[Unit] = []
    _uid = _id_factory(set())

    # 1. per-java-file symbol map + hunk ownership (deterministic local scan).
    finfo: dict[str, dict] = {}
    for fd in file_diffs:
        if fd.change_type == "D" or not fd.path.lower().endswith(INTERFACE_EXTS):
            continue
        content = _branch_content(repo, fd.path, branch)
        if content is None:
            continue
        syms = _java_symbols(content)
        base, is_ctrl = _base_route(content)
        if fd.change_type == "A":
            # a NEW file: every symbol in it is added — all hunks belong to all symbols
            # (the hunk anchor sits on the package/import header, outside every body;
            # per-hunk ownership would strand the whole file and silently drop it from
            # the changed-symbol set)
            owner = list(range(len(syms))) if syms else [None] * len(fd.hunks)
        else:
            owner = [_owning_hunk_symbol(syms, h) for h in fd.hunks]
        finfo[fd.path] = {"fd": fd, "syms": syms, "base": base, "owner": owner,
                          "is_iface": bool(is_ctrl or syms and any(s["route"] for s in syms))}

    def _key(path: str, name: str) -> str:
        return f"{path.replace(chr(92), '/')}::{name}"

    # 2. changed-symbol set (methods owning >=1 hunk); route anchors carry a route.
    changed: dict[str, dict] = {}
    for path, info in finfo.items():
        for i, s in enumerate(info["syms"]):
            owned = [j for j, o in enumerate(info["owner"]) if o == i]
            if not owned:
                continue
            key = _key(path, s["name"])
            full_route = _route_str(info["base"], s["route"]) if s["route"] else ""
            rec = changed.get(key)
            if rec is None:
                rec = {"file": path, "name": s["name"], "route": full_route,
                       "hunks": set(), "ann": s["ann"]}
                changed[key] = rec
            rec["hunks"].update(owned)
            if full_route and not rec["route"]:
                rec["route"], rec["ann"] = full_route, s["ann"]
    stats["symbols_queried"] = len(changed)
    anchors = sorted((k for k, r in changed.items() if r["route"]),
                     key=lambda k: (changed[k]["file"], changed[k]["name"]))
    stats["anchors_changed"] = len(anchors)

    # 3. call edges: callees restricted to the changed set build the downstream
    #    adjacency; callers are kept VERBATIM (incl. unchanged endpoints) in
    #    caller_edges for upstream anchoring. RAW callee edges (incl. unchanged
    #    endpoints — previously dropped by the `if e in adjacency` filter) are retained
    #    in raw_down keyed by the CALLER key: the chain projection consumes them (zero
    #    new codegraph queries).
    edge_cache: dict[str, tuple[set[str], set[str]]] = {}
    adjacency: dict[str, set[str]] = {k: set() for k in changed}
    caller_edges: dict[str, set[str]] = {}
    raw_down: dict[str, set[str]] = {}
    edges_captured = 0
    for key, rec in changed.items():
        ck = edge_cache.get(rec["name"])
        if ck is None:
            ck = _cg_edges(repo, rec["name"])
            edge_cache[rec["name"]] = ck
        callers, callees = ck
        edges_captured += len(callers) + len(callees)
        caller_edges.setdefault(key, set()).update(callers)
        raw_down.setdefault(key, set()).update(callees)
        # invert the caller side: an edge (unchanged upstream anchor -> changed key)
        # is downstream raw data for the anchor (its own callees were never queried —
        # the anchor is not in the changed set)
        for e in callers:
            raw_down.setdefault(e, set()).add(key)
        for e in callees:
            if e in adjacency:
                adjacency[key].add(e)      # key calls e
        for e in callers:
            if e in adjacency:
                adjacency[e].add(key)      # e calls key
    stats["edges_captured"] = edges_captured
    stats["edges_in_changed_set"] = sum(len(v) for v in adjacency.values())

    def _closure(ak: str) -> set[str]:
        reach = {ak}
        frontier = [ak]
        while frontier:
            nxt = []
            for k in frontier:
                for t in adjacency.get(k, ()):
                    if t not in reach:
                        reach.add(t)
                        nxt.append(t)
            frontier = nxt
        return reach

    def _cons_unit(route: str, ann: list[str], anchor: str | None = None) -> dict:
        """One route constituent (mutable body: files + hunk selection + ann + the
        anchor key that projects the chain). Hunks are attached via `_absorb` so
        leftovers never double-count."""
        return {"route": route, "files": [], "selmap": {}, "ann": ann,
                "anchor": anchor}

    def _absorb(con: dict, reach: set[str]) -> None:
        """Claim a changed-symbol reach set into a constituent (create or extend):
        append files, union per-file hunk selections; mark hunks claimed. Shared
        downstream hunks legitimately repeat across constituents (renderer dedups)."""
        by_file: dict[str, set[int]] = {}
        for k in reach:
            r = changed[k]
            fd = finfo[r["file"]]["fd"]
            by_file.setdefault(fd.path, set()).update(
                i for i in r["hunks"] if i < len(fd.hunks))
        for path in sorted(by_file):
            fd = finfo[path]["fd"]
            idxs = set(by_file[path]) - set(con["selmap"].get(fd.path, ()))
            if not idxs:
                continue
            if fd not in con["files"]:
                con["files"].append(fd)
            con["selmap"][fd.path] = sorted(set(con["selmap"].get(fd.path, ())) | idxs)
            claimed.setdefault(fd.path, set()).update(idxs)

    def _con_bytes(con: dict, base_id: str) -> int:
        """Measured size of ONE constituent as it would render in a unit of its own. The
        probe identity is the host's base_id: a constituent alone in a part materializes as
        `_uid(base_id)`. A `-partN` continuation id is a few bytes longer, which the gate's
        level-1 re-split absorbs (it re-measures the real units before writing)."""
        return gate.bytes(_probe_unit(_safe_name(base_id) or "unit", "interface",
                                      con["route"], con["files"], con["selmap"],
                                      con["ann"]))

    # 4. route-anchored downstream closure -> one constituent per route anchor.
    claimed: dict[str, set[int]] = {}
    route_units: list[dict] = []   # {route, file(controller), reach, downstream, ann}
    for ak in anchors:
        rec = changed[ak]
        ann = [f"{rec['file']}: {a}" for a in rec.get("ann", [])]
        base = finfo[rec["file"]]["base"]
        if base:
            ann.append(f"{rec['file']}: class base route {base!r}")
        reach = _closure(ak)
        route_units.append({"route": rec["route"], "file": rec["file"],
                            "reach": reach, "downstream": reach - {ak}, "ann": ann,
                            "anchor": ak})

    # 4b. shared-chain merge: within ONE controller file, absorb routes whose
    #     DOWNSTREAM set (closure minus the anchor itself) equals another's or is a
    #     subset — "both routes call the same changed service method" merges, distinct
    #     downstreams stay split. Cross-file merges NEVER happen (the anchoring
    #     controller's authz face is the review unit boundary). chain_merged counts
    #     the absorbed routes.
    route_units.sort(key=lambda ru: (ru["file"], -len(ru["downstream"]), ru["route"]))
    hosts: list[dict] = []
    for ru in route_units:
        host = next((h for h in hosts if h["file"] == ru["file"]
                     and (ru["downstream"] <= h["downstream"])), None)
        if host is None:
            host = {"file": ru["file"], "reach": set(), "downstream": set(),
                    "base_id": f"{_stem(ru['file'])}::{ru['route'] or _stem(ru['file'])}",
                    "constituents": []}
            hosts.append(host)
        elif any(c["route"] == ru["route"] for c in host["constituents"]):
            continue   # same route already present (union semantics): never double
        else:
            stats["chain_merged"] += 1
        host["reach"] |= ru["reach"]
        host["downstream"] |= ru["downstream"]
        con = _cons_unit(ru["route"], ru["ann"], ru["anchor"])
        _absorb(con, ru["reach"])
        host["constituents"].append(con)

    # 4c. upstream anchoring: changed symbols no changed-route closure claimed walk
    #     caller edges up <=2 hops to a (possibly unchanged) route method; hits join
    #     (or create) that route's host.
    claimed_syms = set().union(*[h["reach"] for h in hosts]) if hosts else set()
    for k in sorted(k for k in changed if k not in claimed_syms):
        rec = changed[k]
        hit = _anchor_upstream(repo, branch, k, changed, caller_edges)
        if hit is None:
            continue
        uk, route, ufile = hit
        stats["anchors_upstream"] += 1
        host = next((h for h in hosts if h["file"] == ufile
                     and any(c["route"] == route for c in h["constituents"])), None)
        uname = uk.rpartition("::")[2]
        if host is None:
            host = {"file": ufile, "reach": set(),
                    "base_id": f"{_stem(ufile)}::{route or _stem(ufile)}",
                    "constituents": []}
            hosts.append(host)
        host["reach"].add(k)
        if any(c["route"] == route for c in host["constituents"]):
            con = next(c for c in host["constituents"] if c["route"] == route)
            if con.get("anchor") is None:
                con["anchor"] = uk   # chain entry = the unchanged route method
        else:
            snippet = _route_method_snippet(repo, ufile, branch, uname)
            # rides the Annotation context fence; the snippet itself is bounded
            ann = ([f"upstream-route {route} (unchanged) at {ufile}::{uname}"]
                   + snippet)
            con = _cons_unit(route, ann, uk)
            host["constituents"].append(con)
        _absorb(con, {k})

    # 4d. chain materialization: per host, project each constituent's anchor (the
    #     changed route method, or the unchanged upstream route for anchored units)
    #     down the raw edges (deterministic; zero new codegraph queries) -> chain[].
    mapper_idx = _mapper_index(repo)
    down_sorted = {k: sorted(v) for k, v in raw_down.items()}
    stats["chains_materialized"] = 0

    def _impl_preferring_anchor(cands: list[str]) -> str:
        """Interface/impl resolution (impl preferred): among same-name candidates,
        prefer the one whose file stem is NOT interface-style (`I` + uppercase, e.g.
        IOrderService), then the lexicographic key order (deterministic)."""
        def _rank(k: str) -> tuple:
            stem = _stem(changed[k]["file"])
            iface_style = (len(stem) > 1 and stem[0] == "I" and stem[1].isupper())
            return (iface_style, k)
        return sorted(cands, key=_rank)[0]

    for h in hosts:
        anchor_pairs: list[tuple[str, str]] = []
        for c in h["constituents"]:
            ak = c.get("anchor")
            if ak is None:
                cands = [k for k in changed
                         if changed[k]["route"] == c["route"]]
                if cands:
                    ak = _impl_preferring_anchor(sorted(cands))
            if ak is not None:
                anchor_pairs.append((ak, c["route"]))
        if anchor_pairs:
            h["chain"] = _chain_nodes(repo, branch, anchor_pairs, changed,
                                      down_sorted, mapper_idx)
            stats["chains_materialized"] += 1
        else:
            h["chain"] = []
        for c in h["constituents"]:
            c["bytes"] = _con_bytes(c, h["base_id"])
        h["unit"] = Unit(_uid(h["base_id"]), "interface",
                         ";".join(c["route"] for c in h["constituents"]), [], {}, [])
        h["unit"].chain = h["chain"]
    units.extend(_split_interface_budget(hosts, iface_cap, _uid, gate))

    # 5. leftovers: interface-file unclaimed hunks keep a class-level interface unit;
    #    java residuals now take directory clustering + budget (same as non-java —
    #    one-unit-per-file was reverted after the real-repo 401-unit run), with a
    #    bounded per-file symbol table so method-level addressing survives the merge;
    #    non-java / deleted residuals keep plain directory clustering + budget.
    residual_java: list[tuple[FileDiff, list[int], dict]] = []
    residual_other: list[tuple[FileDiff, list[int]]] = []
    for fd in file_diffs:
        unclaimed = [i for i in range(len(fd.hunks))
                     if i not in claimed.get(fd.path, ())]
        if not unclaimed:
            continue
        info = finfo.get(fd.path)
        if info is not None and info["is_iface"]:
            units.append(Unit(_uid(f"{_stem(fd.path)}::{info['base'] or 'class'}"),
                              "interface", info["base"], [fd], {fd.path: unclaimed}))
            continue
        if info is not None:
            residual_java.append((fd, unclaimed, info))
            continue
        residual_other.append((fd, unclaimed))
    jinfo = {fd.path: info for fd, _sel, info in residual_java}

    def _res_sym(members) -> list[str]:
        """The symbol table a java-residual cluster renders (bounded, per file). Also the
        clustering probe's input: the table is slice BODY, so a cluster that fits only
        without it is a cluster that does not fit."""
        sym: list[str] = ["## Files & symbols in this cluster (branch version)"]
        for fd, _sel in members:
            sym.append(f"- {fd.path}")
            sym.extend(_sym_table(jinfo[fd.path]["syms"]))
        return sym

    for name, members in _cluster_standalone_sel(
            [(fd, sel) for fd, sel, _ in residual_java], cap, gate, _res_sym):
        selmap = {fd.path: sel for fd, sel in members}
        files = [fd for fd, _ in members]
        units.append(Unit(_uid(name), "standalone", "", files, selmap, None,
                          _res_sym(members)))
    for name, members in _cluster_standalone_sel(residual_other, cap, gate):
        selmap = {fd.path: sel for fd, sel in members}
        files = [fd for fd, _ in members]
        units.append(Unit(_uid(name), "standalone", "", files, selmap))
    return units


def _stem(rel: str) -> str:
    p = rel.replace("\\", "/").rsplit("/", 1)[-1]
    return p.rsplit(".", 1)[0] if "." in p else p


def _branch_content(repo: Path, path: str, branch: str) -> str | None:
    r = _git(repo, "show", f"{branch}:{path}")
    return r.stdout if r.returncode == 0 else None


def _render_slice(repo: Path, base: str, branch: str, unit: Unit,
                  raw_text: str) -> str:
    out = [f"# SDR review unit slice — {unit.unit_id}",
           f"kind: {unit.kind}",
           f"route: {unit.route}" if unit.kind == "interface" else "route: (standalone cluster)",
           f"repo: {repo}",
           f"diff range: {base}..{branch}",
           "",
           "## Files in this unit",
           ]
    for fd in unit.files:
        note = " (binary)" if fd.binary else ""
        out.append(f"- {fd.path} [{fd.change_type}]{note}")
    if unit.ann_ctx:
        out += ["", "## Annotation context (branch version)", "```"]
        out.extend(unit.ann_ctx)
        out.append("```")
    if unit.sym_ctx:
        out += ["", "## Files & symbols in this cluster (branch version)"]
        out.extend(unit.sym_ctx)
    out += ["", "## Diff hunks (unified, 3-line context)", "```diff"]
    for fd in unit.files:
        sel = unit.hunk_sel.get(fd.path) if unit.hunk_sel else None
        for i, (start, count, body) in enumerate(fd.hunks):
            if sel is not None and i not in sel:
                continue
            out.append(f"@@ {fd.path} @@ new-file lines {start}+{count}")
            out.extend(body)
    out += ["```", "",
            "Read-only slice materialized by diff_group.py; review against the baseline."]
    return "\n".join(out) + "\n"


# --- slice byte gate: over-budget dispositions (level 1 / 2 / 3) ------------

def _sym_ctx_of(unit: Unit, paths: set[str] | None = None) -> list[str]:
    """The symbol-table block restricted to `paths` (the cluster header line and any line
    that is not a per-file section head are kept — they carry no file attribution)."""
    if not unit.sym_ctx or paths is None:
        return list(unit.sym_ctx)
    out: list[str] = []
    keep = False
    for line in unit.sym_ctx:
        if line.startswith("- "):
            keep = line[2:].strip() in paths
        if keep:
            out.append(line)
    return out


def _part_of(u: Unit, part_id: str, files: list[FileDiff]) -> Unit:
    """One level-1 continuation unit. LOSSLESS: `files` partition the parent's files, each
    carrying its parent hunk selection, so the union of the parts' hunks equals the
    parent's. `ann_ctx` (which has no per-file attribution) rides every part; `sym_ctx`
    follows its file."""
    paths = {fd.path for fd in files}
    sel = ({p: s for p, s in u.hunk_sel.items() if p in paths} if u.hunk_sel else {})
    p = _probe_unit(part_id, u.kind, u.route, files, sel, u.ann_ctx,
                    _sym_ctx_of(u, paths), u.chain)
    return p


def _split_unit_files(u: Unit, cap: int, gate: _SliceGate, uid) -> list[Unit]:
    """Level 1 — lossless re-split of a MULTI-file unit that measures over `cap`: greedy
    pack its files in path order (deterministic; NEVER split mid-file) into `-partN`
    continuation units, each measured <= cap. The only cost is more units: no hunk is
    dropped and no content is truncated, so this level never loses coverage. A part whose
    single file already exceeds `cap` is left whole — it is the atomic residue levels 2/3
    exist for (a file is never split mid-file)."""
    files = sorted(u.files, key=lambda f: f.path)
    parts: list[Unit] = []
    cur: list[FileDiff] = []
    cur_id: str | None = None
    for fd in files:
        if cur_id is None:
            cur_id = uid(f"{u.unit_id}-part{len(parts) + 1}")
            cur = [fd]
            continue
        if gate.bytes(_part_of(u, cur_id, cur + [fd])) <= cap:
            cur = cur + [fd]
            continue
        parts.append(_part_of(u, cur_id, cur))
        cur_id = uid(f"{u.unit_id}-part{len(parts) + 1}")
        cur = [fd]
    if cur_id is not None:
        parts.append(_part_of(u, cur_id, cur))
    return parts


def _truncate_lines(value, limit: int):
    """Head-first truncation of one descriptive context field to `limit` utf-8 bytes,
    with the dropped-line count and the original size kept for the visible marker.
    Handles both shapes (list of lines / one string). Deterministic: same field + same
    limit -> same result, no clock, no sampling."""
    lines = value.splitlines() if isinstance(value, str) else list(value)
    orig = len("\n".join(lines).encode("utf-8"))
    if orig <= limit:
        return value, 0, orig
    kept: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        nxt = used + len(line.encode("utf-8")) + (1 if kept else 0)
        if nxt > limit:
            break
        kept.append(line)
        used = nxt
    dropped = len(lines) - len(kept)
    marker = f"… (截断:{dropped} 行 / 原 {orig} 字节)"
    # the marker itself is slice bytes: back off until the whole block fits the cap
    while kept and used + 1 + len(marker.encode("utf-8")) > limit:
        kept.pop()
        used = len("\n".join(kept).encode("utf-8")) if kept else 0
        dropped = len(lines) - len(kept)
        marker = f"… (截断:{dropped} 行 / 原 {orig} 字节)"
    if isinstance(value, str):
        return ("\n".join(kept + [marker])), dropped, orig
    return kept + [marker], dropped, orig


def _slim_context(u: Unit, cap: int, gate: _SliceGate) -> dict[str, int]:
    """Level 2 — truncate the DESCRIPTIVE context blocks of an atomic residue that is
    still over `cap`. Returns `{field: original bytes}` for what was truncated ({} when
    the blocks already fit the module caps).

    Evidence anchors are NEVER touched: `fd.hunks[].body` (the diff itself), the
    "Files in this unit" list, the per-hunk `@@ <path> @@ new-file lines N+C` locators,
    and the `kind`/`route`/`repo`/`diff range` header fields all describe the change and
    are what the reviewer cites. `ann_ctx`/`sym_ctx` only help locate it — and the
    unchanged-route snippet inside `ann_ctx` is an authz anchor, which is exactly why the
    truncation is marked visibly in the slice instead of being silently dropped."""
    slimmed: dict[str, int] = {}
    for field, limit in (("ann_ctx", SLIM_ANN_CTX_MAX_BYTES),
                         ("sym_ctx", SLIM_SYM_CTX_MAX_BYTES)):
        value = getattr(u, field)
        if not value:
            continue
        if len("\n".join(value if isinstance(value, list) else [value]
                         ).encode("utf-8")) <= limit:
            continue
        kept, _dropped, orig = _truncate_lines(value, limit)
        setattr(u, field, kept)
        slimmed[field] = orig
    return slimmed


def _largest_contributor(u: Unit) -> str:
    """The file whose selected diff body weighs most (the thing to shrink, review alone or
    raise the cap for). Ties break on path so the refusal message is deterministic."""
    best, best_sz = "", -1
    for fd in sorted(u.files, key=lambda f: f.path):
        sel = u.hunk_sel.get(fd.path) if u.hunk_sel else None
        if sel is None:
            sel = list(range(len(fd.hunks)))
        sz = _sel_hunks_size(fd, sel)
        if sz > best_sz:
            best, best_sz = fd.path, sz
    return best


def _gate_units(units: list[Unit], gate: _SliceGate, uid, skip: set[str],
                iface_cap: int, stand_cap: int) -> tuple[list[Unit], dict[str, dict]]:
    """Apply the slice byte gate to every unit about to be materialized.

    `skip` = units already terminal on disk (.done / .failed): their ids, markers and
    slices are the resume truth source, so they are passed through untouched — re-splitting
    one would orphan its marker and re-open finished work.

    Level 3 exits the process BEFORE any slice file or grouping.json exists. That is the
    whole point: the dispatcher consumes disk, so zero artifacts == zero subagents, no
    matter how the caller reacts to the exit code."""
    out: list[Unit] = []
    slim_records: dict[str, dict] = {}
    over: list[tuple[Unit, int, int]] = []
    work = list(units)
    while work:
        u = work.pop(0)
        if u.unit_id in skip:
            out.append(u)
            continue
        cap = iface_cap if u.kind == "interface" else stand_cap
        if gate.bytes(u) <= cap:
            out.append(u)
            continue
        if len(u.files) > 1:                       # level 1: lossless re-split
            work[0:0] = _split_unit_files(u, cap, gate, uid)
            continue
        rec = _slim_context(u, cap, gate)          # level 2: context slim (atomic residue)
        if gate.bytes(u) <= cap:
            if rec:
                slim_records[u.unit_id] = rec
            out.append(u)
            continue
        over.append((u, cap, gate.bytes(u)))       # level 3: fail-loud, zero dispatch
    if over:
        _eprint(f"error: {len(over)} unit(s) still over their slice byte budget after "
                f"re-split + context slim — refusing to dispatch oversize review units "
                f"(exit 2, zero side effects: no slice, no grouping.json, no subagent).")
        for u, cap, size in over:
            _eprint(f"  - {u.unit_id}: {size} bytes > cap {cap} "
                    f"(kind={u.kind}, files={len(u.files)}, "
                    f"largest contributing file: {_largest_contributor(u)})")
        _eprint("recipe: raise the cap (`--max-standalone-bytes` for standalone clusters, "
                "`--max-interface-bytes` for interface units), narrow the diff range "
                "(`--base`/`--branch`) so this file's change is smaller, or review the "
                "listed file(s) out-of-band and re-run. A single file's diff body is the "
                "one thing this gate will never truncate.")
        sys.exit(2)
    return out, slim_records


# --- main -------------------------------------------------------------------

def _enumerate(args) -> dict:
    repo = Path(args.repo)
    if not repo.is_dir():
        _eprint(f"error: --repo not a directory: {repo}")
        sys.exit(1)
    repo = repo.resolve()
    branch = args.branch or _current_branch(repo)
    base = args.base
    _gate(repo, base, branch)

    r = _git(repo, "diff", "--no-color", f"{base}..{branch}")
    if r.returncode != 0:
        _eprint(f"error: git diff failed: {(r.stderr or '').strip()[:400]}\n"
                f"recipe: verify both refs exist (`git rev-parse --verify <ref>`) and "
                f"the work tree is readable; re-run with explicit --base/--branch.")
        sys.exit(2)
    all_diffs = parse_diff(r.stdout)

    # exclusion filter: closed set, applied BEFORE any grouping; --include-excluded
    # is the one-flag fallback restoring the full review. Never silent (excluded{}).
    if args.include_excluded:
        file_diffs = all_diffs
        excluded = {"count": 0, "by_reason": {}}
    else:
        kept: list[FileDiff] = []
        by_reason: dict[str, int] = {}
        for fd in all_diffs:
            reason = _exclude_reason(fd.path)
            if reason is None:
                kept.append(fd)
            else:
                by_reason[reason] = by_reason.get(reason, 0) + 1
        file_diffs = kept
        excluded = {"count": len(all_diffs) - len(kept), "by_reason": by_reason}
    excluded_in_diff = excluded["count"] > 0

    checkpoints = Path(args.checkpoints).resolve()
    checkpoints.mkdir(parents=True, exist_ok=True)
    slices_dir = Path(args.materialize).resolve() if args.materialize else None
    grouping_path = checkpoints.parent / "grouping.json"

    gate = _SliceGate(repo, base, branch, r.stdout)

    probe_reason = _codegraph_probe_reason(repo) if not _codegraph_available(repo) else None
    cg_on = bool(file_diffs) and probe_reason is None
    stats = {k: 0 for k in ("symbols_queried", "edges_captured", "edges_in_changed_set",
                            "anchors_changed", "anchors_upstream", "chain_merged",
                            "chains_materialized")}
    if cg_on:
        units = _build_units_callchain(repo, file_diffs, branch,
                                       args.max_standalone_bytes,
                                       args.max_interface_bytes, stats, gate)
    else:
        units = _build_units(repo, file_diffs, branch, args.max_standalone_bytes,
                             gate) if file_diffs else []

    # Marker judgment is FORWARD over the canonical unit ids produced above (shared
    # predicate) — never a filename glob. Glob counts legacy/orphan markers whose
    # name maps to no current unit id; the forward computation is the same one the
    # resume reader runs, so "pending here" and "pending on resume" cannot diverge.
    unit_ids = [u.unit_id for u in units]
    done = forward_done_ids(checkpoints, unit_ids)
    failed = forward_failed_ids(checkpoints, unit_ids)

    # Slice byte gate, BEFORE anything is written. Units already terminal on disk are
    # passed through (their markers/slices are the resume truth source); every unit about
    # to be materialized is measured on its RENDERED text and put through the three-level
    # ladder (lossless re-split -> context slim -> fail-loud exit 2). The refusal path
    # leaves zero artifacts, so the dispatcher has nothing to consume.
    gate_skip = set(done) | (set() if args.include_failed else set(failed))
    units, slim_records = _gate_units(units, gate, _id_factory(set(unit_ids)),
                                      gate_skip, args.max_interface_bytes,
                                      args.max_standalone_bytes)

    pending = []
    counts = {"interface": 0, "standalone": 0}
    all_units = []
    for u in units:
        counts[u.kind] += 1
        # full-unit projection for the renderer's 简报表 rows (pending[] drops .done
        # units; the report needs EVERY unit with its route/chain even after fan-out)
        all_units.append({
            "unit_id": u.unit_id, "kind": u.kind, "route": u.route,
            "chain": u.chain,
            "status": ("failed" if u.unit_id in failed
                       else "done" if u.unit_id in done else "pending"),
        })
        if u.unit_id in done or (u.unit_id in failed
                                 and not args.include_failed):
            continue  # .done: skip re-materialization; .failed: terminal
        # (--include-failed: a failed unit falls through — its slice is
        # re-materialized and it re-enters pending[] under its canonical
        # unit_id with the same forward-derived failed_marker path, for the
        # dispatcher's --retry-failed flow. The all_units status row above
        # still reports the marker truth "failed".)
        # `unit_bytes` is the gate's own measurement of the text being written — not a
        # post-write stat(). Same renderer, same number: the budget judgement and the
        # artifact cannot disagree (a --check assertion, not a convention).
        slice_text = gate.text(u)
        u.slice_bytes = len(slice_text.encode("utf-8"))
        spath = (slices_dir / f"{u.unit_id}.slice.md") if slices_dir else None
        if spath is not None:
            spath.parent.mkdir(parents=True, exist_ok=True)
            # newline="" pins the file to the rendered text byte-for-byte. Default text
            # mode would translate \n to os.linesep, so on Windows the artifact would be
            # one byte per line LARGER than the gate measured — the exact judge/artifact
            # divergence this gate exists to remove. Readers are unaffected (universal
            # newlines normalize on read).
            spath.write_text(slice_text, encoding="utf-8", newline="")
        draft_path, done_marker, failed_marker = forward_marker_paths(checkpoints,
                                                                     u.unit_id)
        pending.append({
            "unit_id": u.unit_id,
            "input_path": str(spath) if spath else "",
            "draft_path": draft_path,
            "done_marker": done_marker,
            "failed_marker": failed_marker,
            "kind": u.kind,
            "route": u.route,
            "unit_bytes": u.slice_bytes,
            # which descriptive context blocks were truncated for this unit and their
            # pre-truncation size ({} = intact). Disclosed in the report's honesty
            # boundary: a slimmed unit's input completeness is below a normal unit's.
            "slimmed": slim_records.get(u.unit_id, {}),
            # materialized call chain (interface units, codegraph mode; standalone and
            # codegraph-off units carry [] — the structure is always present)
            "chain": u.chain,
            # baseline + external-conclusion locations (verbatim absolute; produced by
            # sdr_context.py in the standard layout — a missing file means that step did
            # not run and the subagent skips it)
            "baseline_path": str((checkpoints.parent / "baseline.md").resolve()),
            "external_dir": str((checkpoints.parent / "external").resolve()),
        })

    req_limit = args.limit if args.limit is not None else len(pending)
    page = pending[args.offset: args.offset + max(0, req_limit)]
    result = {
        "repo": str(repo),
        "base": base,
        "branch": branch,
        # `empty` = nothing to review AT ALL (zero diff). A diff fully eaten by the
        # exclusion filter is NOT empty: files arrived, none entered review — the
        # distinction is observable via excluded.count + total == 0.
        "empty": not all_diffs,
        "excluded_nonempty": excluded_in_diff and not units,
        "codegraph": cg_on,
        "total": len(units),
        # EVERY unit (done/pending/failed) with route + chain — the renderer's 简报表
        # row source (pending[] is re-enumeration output and drops finished units)
        "units": all_units,
        "done": len(done),
        "failed": len(failed),
        "counts": counts,
        "excluded": excluded,
        # the caps this run actually enforced (--check reads them back: it gets the run
        # dir only, never the flags, so the run record must carry its own budget truth)
        "budget": {"max_standalone_bytes": args.max_standalone_bytes,
                   "max_interface_bytes": args.max_interface_bytes},
        "codegraph_stats": {**stats, "excluded_files": excluded["count"]},
        "pending": page,
        "offset": args.offset,
        "limit": req_limit,
    }
    if probe_reason:
        _eprint(f"[diff_group] codegraph probe off: {probe_reason}")
    grouping_path.parent.mkdir(parents=True, exist_ok=True)
    grouping_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    reason_summary = ",".join(f"{k}={v}" for k, v in sorted(excluded["by_reason"].items())) \
        or "-"
    _eprint(f"[diff_group] {base}..{branch}: {len(all_diffs)} file(s) "
            f"(excluded {excluded['count']}: {reason_summary}) -> "
            f"{counts['interface']} interface + {counts['standalone']} standalone unit(s); "
            f"codegraph={'on' if cg_on else 'off'} "
            f"anchors_changed={stats['anchors_changed']} "
            f"anchors_upstream={stats['anchors_upstream']} "
            f"chain_merged={stats['chain_merged']} "
            f"done={len(done)} failed={len(failed)} pending={len(pending)} "
            f"(grouping: {grouping_path})")
    if excluded_in_diff and not units:
        _eprint("[diff_group] NOTE: every changed file was excluded by the closed set; "
                "no review units were produced (re-run with --include-excluded to "
                "review them anyway). This is NOT a zero-diff run.")
    return result


def _check(run_dir: Path) -> int:
    gp = run_dir / "grouping.json"
    if not gp.is_file():
        _eprint(f"error: grouping.json not found in run dir: {run_dir}\n"
                f"recipe: run diff_group.py --materialize <run-dir>/slices first "
                f"(it writes grouping.json into the run dir).")
        return 2
    try:
        g = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        _eprint(f"error: malformed grouping.json: {e}")
        return 2
    repo = Path(g.get("repo", ""))
    violations = []
    units = g.get("pending", [])
    # budget: NEW field — the caps this run enforced. Absent (old grouping.json) means the
    # per-unit cap assertion cannot be evaluated and is skipped, same incremental contract
    # as excluded / codegraph_stats / chain[].
    stand_cap = iface_cap = None
    budget = g.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or not all(
                isinstance(budget.get(k), int)
                for k in ("max_standalone_bytes", "max_interface_bytes")):
            violations.append(f"budget malformed (want {{max_standalone_bytes: int, "
                              f"max_interface_bytes: int}}): {budget!r}")
        else:
            stand_cap, iface_cap = (budget["max_standalone_bytes"],
                                    budget["max_interface_bytes"])
    for u in units:
        for field in ("input_path", "draft_path", "done_marker", "failed_marker"):
            v = u.get(field, "")
            if not v or not Path(v).is_absolute():
                violations.append(f"{u.get('unit_id')}: {field} not absolute: {v!r}")
                continue
            try:
                p = Path(v).resolve()
                if repo.is_dir() and not (p == repo or repo in p.parents):
                    violations.append(f"{u.get('unit_id')}: {field} outside repo subtree: {v}")
            except (OSError, ValueError):
                violations.append(f"{u.get('unit_id')}: {field} unresolvable: {v!r}")
        ip = Path(u.get("input_path", ""))
        if u.get("input_path") and not ip.is_file():
            violations.append(f"{u.get('unit_id')}: slice missing: {ip}")
        dm = Path(u["done_marker"]).exists() if u.get("done_marker") else False
        fm = Path(u["failed_marker"]).exists() if u.get("failed_marker") else False
        if dm and fm:
            violations.append(f"{u.get('unit_id')}: both .done and .failed markers exist")
        # route shape: a merged interface unit carries ';'-joined routes (no empties)
        route = u.get("route")
        if isinstance(route, str) and ";" in route:
            segs = [s.strip() for s in route.split(";")]
            if any(not s for s in segs):
                violations.append(f"{u.get('unit_id')}: multi-route has empty segment: "
                                  f"{route!r}")
        elif route is not None and not isinstance(route, str):
            violations.append(f"{u.get('unit_id')}: route not a string: {route!r}")
        # part units (id carries -partN) must own their matching slice file
        uid = str(u.get("unit_id", ""))
        ip_name = Path(u.get("input_path", "")).name
        if uid and ip_name and not ip_name.startswith(f"{uid}.slice.md"):
            violations.append(f"{uid}: slice name {ip_name!r} disagrees with unit_id")
        # chain[]: incremental field — absent (old grouping.json) is fine; present, it
        # must be a list of nodes with the required fields + legal branch_of indices.
        chain = u.get("chain")
        if chain is not None:
            if not isinstance(chain, list):
                violations.append(f"{uid}: chain not a list: {type(chain).__name__}")
                continue
            for ci, nd in enumerate(chain):
                if not isinstance(nd, dict):
                    violations.append(f"{uid}: chain[{ci}] not an object")
                    continue
                for f in ("fqn_short", "label", "file", "change"):
                    if not isinstance(nd.get(f), str) or not nd.get(f):
                        violations.append(f"{uid}: chain[{ci}] missing field {f}")
                if nd.get("change") not in ("changed", "unchanged", "external"):
                    violations.append(f"{uid}: chain[{ci}] bad change: "
                                      f"{nd.get('change')!r}")
                ln = nd.get("line")
                if ln is not None and not isinstance(ln, int):
                    violations.append(f"{uid}: chain[{ci}] line not int|null: {ln!r}")
                bo = nd.get("branch_of")
                if bo is not None:
                    if not isinstance(bo, int) or bo < 0 or bo >= len(chain) or bo == ci:
                        violations.append(f"{uid}: chain[{ci}] branch_of illegal: {bo!r}")
        # slimmed: incremental field — absent (old grouping.json) is fine; present it must
        # be a field -> original-bytes map ({} = intact).
        sl = u.get("slimmed")
        if sl is not None and (not isinstance(sl, dict)
                               or not all(isinstance(k, str) and isinstance(v, int)
                                          for k, v in sl.items())):
            violations.append(f"{uid}: slimmed malformed (want {{field: original_bytes}}): "
                              f"{sl!r}")
        # the budget assertion itself: only with a recorded budget (see below), and only
        # for a unit that carries the measured size.
        if stand_cap is not None:
            cap = iface_cap if u.get("kind") == "interface" else stand_cap
            ub = u.get("unit_bytes")
            if isinstance(ub, int) and ub > cap:
                violations.append(f"{uid}: unit_bytes {ub} > {u.get('kind')} cap {cap} "
                                  f"(the slice byte gate was bypassed for this run)")
    for field in ("base", "branch", "counts"):
        if field not in g:
            violations.append(f"grouping.json missing field: {field}")
    # excluded / codegraph_stats: NEW fields — validated structurally when present,
    # silently skipped when absent (old grouping.json stays --check-clean; backward
    # compat is part of the contract).
    exc = g.get("excluded")
    if exc is not None:
        if not isinstance(exc, dict) or not isinstance(exc.get("count", 0), int) \
                or not isinstance(exc.get("by_reason", {}), dict) \
                or not all(isinstance(v, int) for v in exc.get("by_reason", {}).values()):
            violations.append(f"excluded malformed (want {{count:int, by_reason:int}}): {exc!r}")
        elif exc["count"] != sum(exc["by_reason"].values()):
            violations.append(f"excluded.count != sum(by_reason): {exc!r}")
    cgs = g.get("codegraph_stats")
    if cgs is not None and not isinstance(cgs, dict):
        violations.append(f"codegraph_stats not an object: {cgs!r}")
    # units[]: full-unit projection for the renderer — same chain validation as
    # pending[], plus kind/status closed-set and route-typing. Absent (old
    # grouping.json) = fine; present it must be structurally sound.
    allu = g.get("units")
    if allu is not None:
        if not isinstance(allu, list):
            violations.append(f"units not a list: {type(allu).__name__}")
        else:
            ids = [u.get("unit_id") for u in allu if isinstance(u, dict)]
            if len(ids) != len(set(ids)):
                violations.append("units has duplicate unit_id entries")
            for u in allu:
                if not isinstance(u, dict):
                    violations.append(f"units item not an object: {u!r}")
                    continue
                if u.get("kind") not in ("interface", "standalone"):
                    violations.append(f"{u.get('unit_id')}: bad kind: {u.get('kind')!r}")
                if u.get("status") not in ("done", "pending", "failed"):
                    violations.append(f"{u.get('unit_id')}: bad status: "
                                      f"{u.get('status')!r}")
                if not isinstance(u.get("route"), str):
                    violations.append(f"{u.get('unit_id')}: route not a string")
                ch = u.get("chain")
                if ch is not None and not isinstance(ch, list):
                    violations.append(f"{u.get('unit_id')}: chain not a list")
            if g.get("total") != len(allu):
                violations.append(f"units length {len(allu)} != total {g.get('total')}")
    if violations:
        _eprint(f"error: diff_group --check: {len(violations)} violation(s):")
        for v in violations:
            _eprint(f"  - {v}")
        _eprint("recipe: fix or re-run `diff_group.py --repo <abs> --base <ref> "
                "--branch <ref> --checkpoints <run-dir>/markers --materialize "
                "<run-dir>/slices` (idempotent; .done units are skipped).")
        return 2
    _eprint(f"[diff_group] --check ok: {len(units)} pending unit(s) consistent "
            f"({run_dir})")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="deterministic diff collection + interface-dimension grouping for "
                    "/mgh-sdr (pending work-list producer for fanout_runner --tier sdr)")
    ap.add_argument("--repo", help="absolute target git repo root")
    ap.add_argument("--base", default="master", help="base ref (default master)")
    ap.add_argument("--branch", default="", help="branch ref (default: current branch)")
    ap.add_argument("--checkpoints", help="markers dir (.done/.failed; default layout "
                                          "<run-dir>/markers)")
    ap.add_argument("--inputs-dir", help=argparse.SUPPRESS)  # reserved; drafts derive from
    # <checkpoints>/../drafts (deterministic run-dir layout) so fanout_runner forwards
    # only --repo/--base/--branch/--checkpoints/--materialize.
    ap.add_argument("--materialize", metavar="<slices-dir>",
                    help="write one read-only slice per pending unit into this dir "
                         "(+ draft_path/marker absolute paths in pending[])")
    ap.add_argument("--max-standalone-bytes", type=int,
                    default=DEFAULT_MAX_STANDALONE_BYTES,
                    help=f"standalone cluster merge cap in bytes (default "
                         f"{DEFAULT_MAX_STANDALONE_BYTES}) — judged on the MEASURED "
                         f"slice, not an estimate; a cluster over cap is re-split "
                         f"losslessly, then context-slimmed, then refused (exit 2, no "
                         f"slice written, no subagent dispatched)")
    ap.add_argument("--max-interface-bytes", type=int,
                    default=DEFAULT_MAX_INTERFACE_BYTES,
                    help=f"interface unit split cap in bytes (default "
                         f"{DEFAULT_MAX_INTERFACE_BYTES}; over-budget merged units "
                         f"split into -partN units) — judged on the MEASURED slice; a "
                         f"unit still over cap is re-split losslessly, then "
                         f"context-slimmed, then refused (exit 2, no slice written, no "
                         f"subagent dispatched)")
    ap.add_argument("--include-excluded", action="store_true",
                    help="fallback: do NOT apply the closed exclusion filter (tests, "
                         "build outputs, static assets, lockfiles, build scripts "
                         "re-enter review; excluded count becomes 0)")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max pending items per page (default: all)")
    ap.add_argument("--resume", action="store_true",
                    help="call-shape parity: disk markers are ALWAYS the truth source "
                         "(.done units skipped, .failed terminal)")
    ap.add_argument("--include-failed", action="store_true",
                    help="re-list failed units into pending[] under their canonical "
                         "unit_id with their existing .failed marker path (slices "
                         "re-materialized; identity from this enumerator's forward "
                         "derivation, never filename stems; opt-in for the "
                         "dispatcher's --retry-failed flow). Default off keeps "
                         "stdout byte-identical")
    ap.add_argument("--check", metavar="<run-dir>",
                    help="validate a run dir's grouping.json + slices + markers "
                         "(fail-loud exit 2; R5.9)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        if args.repo or args.checkpoints or args.materialize:
            _eprint("error: --check takes only <run-dir> (mutually exclusive with "
                    "enumeration flags)")
            return 2
        return _check(Path(args.check).resolve())
    if not args.repo:
        _eprint("error: --repo is required (or use --check <run-dir>)")
        return 2
    if args.offset < 0:
        _eprint("error: --offset must be >= 0")
        return 2
    if args.max_standalone_bytes < 0:
        _eprint("error: --max-standalone-bytes must be >= 0")
        return 2
    if args.max_interface_bytes < 0:
        _eprint("error: --max-interface-bytes must be >= 0")
        return 2
    if not args.materialize:
        _eprint("error: --materialize <slices-dir> is required for enumeration "
                "(per-unit read-only slices)")
        return 2
    if not args.checkpoints:
        _eprint("error: --checkpoints <markers-dir> is required for enumeration "
                "(default layout <run-dir>/markers)")
        return 2

    result = _enumerate(args)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
