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
    merge in sorted order while the combined slice stays within --max-standalone-bytes
    (a single oversize file is its own unit — merged-capped, never split mid-file).

Slice file: per-unit diff hunks (git default 3-line context) + file list + change types
(A/M/D/R) + routes. Draft path / markers: drafts live in `<checkpoints>/../drafts`
(deterministic sibling of the markers dir in the standard <run-dir>/ layout); slices in
--materialize. `pending[]` fields are ALL Path.resolve()-absolute and inside the repo
subtree (R5.3(b) fan-out path contract); `unit_id` is filesystem-safe (`/ \\ :` -> `_`,
NTFS ADS lesson) and unique (numeric suffix on collision).

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b):
  {"repo": "<abs>", "base": "...", "branch": "...", "empty": bool,
   "total": N, "done": M, "failed": F, "counts": {"interface": I, "standalone": S},
   "pending": [unit...], "offset": 0, "limit": K}
  unit = {unit_id, input_path, draft_path, done_marker, failed_marker, kind, route, unit_bytes}
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
marker or pending); violations exit 2 (R5.9).

Call-chain grouping (optional, codegraph-gated): when `<repo>/.codegraph/` exists AND a
`codegraph` binary is on PATH (env override MGH_CODEGRAPH_BIN for tests/operators), the
changed-method symbol set (deterministic local scan: annotations + method-decl brace
extent) is queried with `codegraph callees/callers --json` and the returned call edges
(restricted to the changed set) drive route-anchored downstream closures — every route
method's closure becomes ONE interface unit carrying the whole changed chain's hunks
(controller + changed service/dao), so cross-layer judgement (authz + SQL + validation)
stays inside a single subagent slice. Changed symbols unreachable from any route anchor
(reflection/DI residue or codegraph=off) fall to standalone units — split, never forced
into a chain. Shared downstream (a changed method called by >1 changed route) is split
per route: its hunks repeat inside each referencing interface slice (dedup left to the
renderer), never merged into one unit. No codegraph (or every query failing) degrades to
the annotation+directory grouping below — byte-identical to the no-codegraph baseline.
stdout carries `codegraph: true|false` (whether this run used call-chain grouping).

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

DEFAULT_MAX_STANDALONE_BYTES = 64 * 1024  # 64KB merge cap for standalone clusters

CODEGRAPH_LIMIT = 500    # callees/callers --limit: raise well above the CLI default 20 so
# a real changed-set edge is not truncated away behind unrelated same-name callers.
CODEGRAPH_TIMEOUT = 20   # per-query subprocess timeout; a hang degrades to no edges
CODEGRAPH_DIR = ".codegraph"

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

def _codegraph_bin() -> str | None:
    """Path to the codegraph binary (env override wins; else PATH). None = unavailable."""
    env = os.environ.get("MGH_CODEGRAPH_BIN")
    if env:
        p = Path(env)
        return str(p) if p.is_file() else None
    return shutil.which("codegraph")


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
    """codegraph is a grouping input ONLY when the repo is indexed (.codegraph/ dir)
    AND a binary resolves. Absent either -> fallback grouping (never a hard dep)."""
    return (repo / CODEGRAPH_DIR).is_dir() and _codegraph_bin() is not None


def _cg_query(repo: Path, sub: str, symbol: str) -> dict | None:
    """`codegraph <callers|callees> <symbol> --path <repo> --limit N --json` -> dict.

    ANY failure (no binary / nonzero exit / not-found info text / unparseable / timeout)
    returns None so the caller degrades per-symbol — never aborts the run."""
    bin_path = _codegraph_bin()
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


def _cg_edges(repo: Path, key: str) -> tuple[set[str], set[str]]:
    """(callers_keys, callees_keys) for a bare symbol name. Entries (name, filePath)
    are folded to `filePath::name` keys here; the caller matches them against the
    changed-symbol set (superset union across files is safe — the filter drops extras)."""
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
    in_str = in_ch = in_line_c = in_block_c = False
    for i in range(decl - 1, len(lines)):
        ln = lines[i]
        j = 0
        while j < len(ln):
            c = ln[j]
            if in_line_c:
                break
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
                    in_line_c = True
                    break
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


def _cluster_standalone(files: list[FileDiff], cap: int) -> list[tuple[str, list[FileDiff]]]:
    """Directory-cluster the standalone files; merge sorted dir groups while the merged
    slice stays within cap bytes (approximated by cumulative diff text length). A single
    oversize file stays its own unit (merge-capped, never split)."""
    by_dir: dict[str, list[FileDiff]] = {}
    for f in files:
        by_dir.setdefault(_dir_of(f.path), []).append(f)
    dirs = sorted(by_dir)
    def _size(fs: list[FileDiff]) -> int:
        return sum(sum(len(l) + 1 for _, _, ls in f.hunks for l in ls) + 64 for f in fs)
    buckets: list[tuple[str, list[FileDiff]]] = []
    for d in dirs:
        if buckets:
            name, members = buckets[-1]
            merged = members + by_dir[d]
            if _size(merged) <= cap:
                prefix = _common_prefix(_dir_of(m.path) for m in merged)
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
    """Approx slice size for a file restricted to `sel` hunk indices (diff text length)."""
    return sum(len(l) + 1 for i, (_s, _c, ls) in enumerate(fd.hunks)
               for l in ls if i in sel) + 64


def _cluster_standalone_sel(items: list[tuple[FileDiff, list[int]]],
                            cap: int) -> list[tuple[str, list[tuple[FileDiff, list[int]]]]]:
    """Directory-cluster residual (partially-claimed) files by their selected hunks;
    merge sorted dir groups while the merged selected size stays within cap. Mirrors
    `_cluster_standalone` but honours per-file hunk selection (a file split across an
    interface chain and a standalone leftover contributes only its leftover hunks)."""
    by_dir: dict[str, list[tuple[FileDiff, list[int]]]] = {}
    for fd, sel in items:
        by_dir.setdefault(_dir_of(fd.path), []).append((fd, sel))

    def _size(members: list[tuple[FileDiff, list[int]]]) -> int:
        return sum(_sel_hunks_size(fd, sel) for fd, sel in members)

    buckets: list[tuple[str, list[tuple[FileDiff, list[int]]]]] = []
    for d in sorted(by_dir):
        if buckets:
            name, members = buckets[-1]
            merged = members + by_dir[d]
            if _size(merged) <= cap:
                prefix = _common_prefix([_dir_of(fd.path) for fd, _ in merged])
                buckets[-1] = (prefix, merged)
                continue
        buckets.append((d, list(by_dir[d])))
    return buckets


class Unit:
    __slots__ = ("unit_id", "kind", "route", "files", "hunk_sel", "slice_bytes",
                 "ann_ctx")

    def __init__(self, unit_id: str, kind: str, route: str,
                 files: list[FileDiff], hunk_sel: dict | None = None,
                 ann_ctx: list[str] | None = None):
        self.unit_id = unit_id
        self.kind = kind
        self.route = route
        self.files = files
        self.hunk_sel = hunk_sel or {}   # file path -> list of hunk indices (interface only)
        self.slice_bytes = 0
        self.ann_ctx = ann_ctx or []     # annotation-context lines (call-chain interface only)


def _build_units(repo: Path, file_diffs: list[FileDiff], branch: str,
                 cap: int) -> list[Unit]:
    units: list[Unit] = []
    seen_ids: set[str] = set()

    def _uid(raw: str) -> str:
        base = _safe_name(raw) or "unit"
        cand, n = base, 1
        while cand in seen_ids:
            n += 1
            cand = f"{base}-{n}"
        seen_ids.add(cand)
        return cand

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

    for d, members in _cluster_standalone(standalone, cap):
        units.append(Unit(_uid(d), "standalone", "", members, None))
    return units


def _build_units_callchain(repo: Path, file_diffs: list[FileDiff], branch: str,
                           cap: int) -> list[Unit]:
    """codegraph-gated call-chain grouping (D1/D2/D4). Only called when the probe
    succeeded (`_codegraph_available`); every codegraph failure degrades per-symbol.

    Changed java methods (deterministic local symbol scan) are queried for call
    edges; every changed ROUTE method's downstream closure becomes one interface unit
    (route method + changed service/dao it reaches) with the chain's hunks merged into
    one slice. Changed methods unreachable from any route (reflection/DI residue, or
    codegraph with no edges) and file-level hunks fall to standalone residual — split,
    never force-merged. A downstream method reached by >1 route repeats inside each
    referencing interface slice (shared-downstream-per-interface, D4); renderer dedups.
    Interface-file hunks left over after route-anchoring keep a class-level interface
    unit (route = base) so nothing drops and a base-route change stays an interface
    signal."""
    units: list[Unit] = []
    seen_ids: set[str] = set()

    def _uid(raw: str) -> str:
        base = _safe_name(raw) or "unit"
        cand, n = base, 1
        while cand in seen_ids:
            n += 1
            cand = f"{base}-{n}"
        seen_ids.add(cand)
        return cand

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
        owner = [_owning_symbol(syms, _hunk_anchor_line(h)) for h in fd.hunks]
        finfo[fd.path] = {"fd": fd, "syms": syms, "base": base, "owner": owner,
                          "is_iface": bool(is_ctrl or syms and any(s["route"] for s in syms))}

    def _key(path: str, name: str) -> str:
        return f"{path.replace(chr(92), '/')}::{name}"

    # 2. changed-symbol set (methods owning >=1 hunk); route anchors carry a route.
    def _route_str(base: str, path: str) -> str:
        if not base:
            return path
        if not path:
            return base
        return f"{base.rstrip('/')}/{path.lstrip('/')}"

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
    anchors = sorted((k for k, r in changed.items() if r["route"]),
                     key=lambda k: (changed[k]["file"], changed[k]["name"]))

    # 3. call edges restricted to the changed set (superset union per name is safe —
    #    endpoints are matched back by filePath+name so extras are dropped).
    edge_cache: dict[str, tuple[set[str], set[str]]] = {}
    adjacency: dict[str, set[str]] = {k: set() for k in changed}
    for key, rec in changed.items():
        ck = edge_cache.get(rec["name"])
        if ck is None:
            ck = _cg_edges(repo, rec["name"])
            edge_cache[rec["name"]] = ck
        callers, callees = ck
        for e in callees:
            if e in adjacency:
                adjacency[key].add(e)      # key calls e
        for e in callers:
            if e in adjacency:
                adjacency[e].add(key)      # e calls key

    # 4. route-anchored downstream closure -> one interface unit per route anchor.
    claimed: dict[str, set[int]] = {}
    for ak in anchors:
        rec = changed[ak]
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
        by_file: dict[str, list[dict]] = {}
        for k in reach:
            r = changed[k]
            by_file.setdefault(r["file"], []).append(r)
        files: list[FileDiff] = []
        selmap: dict[str, list[int]] = {}
        ann: list[str] = []
        for path in sorted(by_file):
            info = finfo[path]
            fd = info["fd"]
            files.append(fd)
            idxs = sorted(i for r in by_file[path] for i in r["hunks"] if i < len(fd.hunks))
            selmap[fd.path] = idxs
            claimed.setdefault(fd.path, set()).update(idxs)
        base = finfo[rec["file"]]["base"]
        for a in rec.get("ann", []):
            ann.append(f"{rec['file']}: {a}")
        if base:
            ann.append(f"{rec['file']}: class base route {base!r}")
        units.append(Unit(_uid(f"{_stem(rec['file'])}::{rec['route'] or _stem(rec['file'])}"),
                          "interface", rec["route"], files, selmap, ann))

    # 5. leftovers: interface-file unclaimed hunks keep a class-level interface unit;
    #    java residuals are one standalone unit PER FILE (a changed method unreachable
    #    from any route is its own component — split, never force-merged across files,
    #    D1 "拆多个不硬塞"); non-java / deleted residuals keep directory clustering +
    #    budget so a config/SQL sweep stays few units.
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
            units.append(Unit(_uid(_stem(fd.path)), "standalone", "", [fd],
                              {fd.path: unclaimed}))
            continue
        residual_other.append((fd, unclaimed))
    for name, members in _cluster_standalone_sel(residual_other, cap):
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
    file_diffs = parse_diff(r.stdout)

    checkpoints = Path(args.checkpoints).resolve()
    checkpoints.mkdir(parents=True, exist_ok=True)
    slices_dir = Path(args.materialize).resolve() if args.materialize else None
    drafts_dir = checkpoints.parent / "drafts"
    grouping_path = checkpoints.parent / "grouping.json"

    done, failed = _markers(checkpoints)
    cg_on = bool(file_diffs) and _codegraph_available(repo)
    if cg_on:
        units = _build_units_callchain(repo, file_diffs, branch,
                                       args.max_standalone_bytes)
    else:
        units = _build_units(repo, file_diffs, branch, args.max_standalone_bytes) \
            if file_diffs else []

    pending = []
    counts = {"interface": 0, "standalone": 0}
    for u in units:
        counts[u.kind] += 1
        if u.unit_id in done or u.unit_id in failed:
            continue  # .done: skip re-materialization; .failed: terminal
        slice_text = _render_slice(repo, base, branch, u, r.stdout)
        spath = (slices_dir / f"{u.unit_id}.slice.md") if slices_dir else None
        if spath is not None:
            spath.parent.mkdir(parents=True, exist_ok=True)
            spath.write_text(slice_text, encoding="utf-8")
            u.slice_bytes = spath.stat().st_size
        pending.append({
            "unit_id": u.unit_id,
            "input_path": str(spath) if spath else "",
            "draft_path": str((drafts_dir / f"{u.unit_id}.json").resolve()),
            "done_marker": str((checkpoints / f"{u.unit_id}.done").resolve()),
            "failed_marker": str((checkpoints / f"{u.unit_id}.failed").resolve()),
            "kind": u.kind,
            "route": u.route,
            "unit_bytes": u.slice_bytes,
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
        "empty": not file_diffs,
        "codegraph": cg_on,
        "total": len(units),
        "done": len(done),
        "failed": len(failed),
        "counts": counts,
        "pending": page,
        "offset": args.offset,
        "limit": req_limit,
    }
    grouping_path.parent.mkdir(parents=True, exist_ok=True)
    grouping_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    _eprint(f"[diff_group] {base}..{branch}: {len(file_diffs)} file(s) -> "
            f"{counts['interface']} interface + {counts['standalone']} standalone unit(s); "
            f"codegraph={'on' if cg_on else 'off'} "
            f"done={len(done)} failed={len(failed)} pending={len(pending)} "
            f"(grouping: {grouping_path})")
    return result


def _markers(checkpoints: Path) -> tuple[set, set]:
    done, failed = set(), set()
    if checkpoints.is_dir():
        for p in checkpoints.glob("*.done"):
            done.add(p.name[:-len(".done")])
        for p in checkpoints.glob("*.failed"):
            failed.add(p.name[:-len(".failed")])
    return done, failed


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
    for field in ("base", "branch", "counts"):
        if field not in g:
            violations.append(f"grouping.json missing field: {field}")
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
                         f"{DEFAULT_MAX_STANDALONE_BYTES})")
    ap.add_argument("--offset", type=int, default=0, help="page offset (default 0)")
    ap.add_argument("--limit", type=int, default=None,
                    help="max pending items per page (default: all)")
    ap.add_argument("--resume", action="store_true",
                    help="call-shape parity: disk markers are ALWAYS the truth source "
                         "(.done units skipped, .failed terminal)")
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
