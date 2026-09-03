#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
mgh_sdr_launch — one-command launcher for /mgh-sdr (the human/cron entry; NEVER called
by a host subagent). THIS SCRIPT SHIPS WITH INSTALL (core/scripts/), so a manager runs
the full review without cloning this dev repo:

  py mgh_sdr_launch.py --repo <abs-target> [--branch <ref>] [--base <ref>]
      [--host opencode|claude] [--dimensions <json>] [--multi-branch <file>]
      [--read-root <abs>]... [--dry-run]

Why a launcher: the two experience/safety problems of an external (frontend) repo are
solved OUTSIDE the host CLI session —
  1. permission interruption: the external-repo controlled retrieval (sdr_context.py)
     runs IN THIS PROCESS, before any host CLI is spawned. The host session (and its
     subagents) only ever sees materialized conclusion files => zero permission prompts
     inside the run. The explicitly confirmed external roots land in the disk sentinel's
     read_roots[] (tool-face read-only escape valve).
  2. lifecycle ownership: this process writes <repo>/.mgh-sdr/.active (with target +
     read_roots) before spawning and REMOVES it after the host CLI exits. A crash leaves
     the sentinel behind; the next launcher start detects a same-target residual,
     reuses + refreshes it (resume semantics) instead of silently locking daily dev.

Per-branch flow (single branch, or serially per --multi-branch line):
  gate (repo + host CLI in PATH; --host explicit > opencode > claude; none => exit 2 +
  recipe) -> run dir <repo>/.mgh-sdr/runs/<ts[-branch]>/ -> sdr_context.py (external
  retrieval + baseline + sensitive catalog, IN THIS PROCESS) -> sentinel write
  (read_roots = actually-searched roots + --read-root additions) -> orchestrator prompt
  file (verbatim absolute paths from the sdr_context stdout) -> spawn host CLI
  (`opencode run` with the task on stdin / `claude -p` likewise; claude gets a 480000ms
  soft-deadline note — claude Bash per-call cap 600000 x 0.8) -> sentinel removal.

--multi-branch <file>: a local text file, one branch name per line (`#` comments and
blank lines ignored); each branch runs the COMPLETE flow serially with its own run dir
(+= "-<branch-safe>") + report + sentinel lifecycle; a branch failure is recorded and
the loop continues; launcher exit 1 iff any branch failed.

--dry-run: gates + sdr_context + sentinel + prompt file, then STOPS before spawning
(zero host CLI invocation); the sentinel is KEPT (the next real run reuses it) — exit 0.

Exit codes (R5.3b): 0 all branches ok (incl. --dry-run) · 1 runtime failure (>=1 branch
failed / host CLI exited non-zero) · 2 misuse (argparse / host missing / repo not a git
work tree / branch ref missing in --multi-branch mode is a per-branch failure not a
launcher abort).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/subprocess/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SENTINEL_REL = Path(".mgh-sdr") / ".active"
RUNS_REL = Path(".mgh-sdr") / "runs"
DEFAULT_BASE = "master"
CLAUDE_TIME_BUDGET_MS = 480000   # claude Bash 600000ms cap x 0.8 (drain headroom)
OPENCODE_TIME_BUDGET_MS = 720000  # 900s assumed host allowance x 0.8


def _eprint(*a):
    print(*a, file=sys.stderr)


def _safe_name(s: str) -> str:
    import re
    return re.sub(r"[/\\:*?\"<>|]", "_", s).strip("_") or "branch"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _detect_host(explicit: str | None) -> str:
    """--host explicit > opencode in PATH > claude in PATH; none => exit 2 + recipe."""
    order = [explicit] if explicit else ["opencode", "claude"]
    for h in order:
        if h and shutil.which(h):
            return h
    if explicit:
        _eprint(f"error: --host {explicit!r} not found in PATH")
    else:
        _eprint("error: no host CLI found (neither `opencode` nor `claude` in PATH).\n"
                "recipe: install opencode or claude, or pass --host <opencode|claude> "
                "with the CLI on PATH; the review cannot run headless without a host.")
    sys.exit(2)


def _gate(repo: Path) -> None:
    if not repo.is_dir():
        _eprint(f"error: --repo not a directory: {repo}")
        sys.exit(2)
    if not (repo / ".git").exists() and _git(repo, "rev-parse", "--git-dir").returncode != 0:
        _eprint(f"error: not a git repository: {repo}\n"
                f"recipe: pass --repo <absolute git repo root>; the review targets a "
                f"branch diff, which requires a git working tree.")
        sys.exit(2)


def _current_branch(repo: Path) -> str:
    r = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode != 0:
        _eprint(f"error: cannot resolve current branch in {repo}: {(r.stderr or '').strip()}")
        sys.exit(2)
    return r.stdout.strip()


def _sentinel_body(repo: Path, read_roots: list[str]) -> dict:
    return {"domain": "mgh-sdr", "target": str(repo), "out_roots": [],
            "read_roots": read_roots, "v": 1}


def _write_sentinel(repo: Path, read_roots: list[str]) -> Path:
    sp = repo / SENTINEL_REL
    sp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sp.with_suffix(".tmp")
    tmp.write_text(json.dumps(_sentinel_body(repo, read_roots), ensure_ascii=False),
                   encoding="utf-8")
    import os
    os.replace(tmp, sp)
    return sp


def _remove_sentinel(repo: Path) -> None:
    try:
        (repo / SENTINEL_REL).unlink(missing_ok=True)
    except OSError as e:
        _eprint(f"warn: cannot remove sentinel: {e}")


def _residual_sentinel(repo: Path) -> dict | None:
    """Crash-residual detection: a same-target sentinel from a previous run is reused +
    refreshed (resume semantics), not silently locked."""
    sp = repo / SENTINEL_REL
    if not sp.is_file():
        return None
    try:
        body = json.loads(sp.read_text(encoding="utf-8"))
        if isinstance(body, dict) and body.get("target") == str(repo):
            _eprint(f"[launch] residual sentinel found for this target — reusing "
                    f"(resume semantics; run dir state on disk is the truth)")
            return body
    except (OSError, ValueError):
        pass
    return None


def _script_path(name: str) -> str:
    """Absolute path of a sibling leaf script (same install dir — the launcher ships
    co-located with the leaf scripts, R5.3a self-location)."""
    return str(Path(__file__).resolve().parent / name)


def _run_context(repo: Path, run_dir: Path, base: str, branch: str, dims: str | None,
                 read_roots: list[str]) -> dict:
    """sdr_context.py IN THIS PROCESS (external retrieval happens with the user's
    explicit authorization — the shell session that launched this command)."""
    cmd = [sys.executable, _script_path("sdr_context.py"),
           "--repo", str(repo), "--run-dir", str(run_dir),
           "--base", base, "--branch", branch]
    if dims:
        cmd += ["--dimensions", dims]
    for rr in read_roots:
        cmd += ["--read-root", rr]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        _eprint(f"error: sdr_context.py exited {r.returncode}:\n{(r.stderr or '')[-600:]}")
        sys.exit(1 if r.returncode == 1 else 2)
    ctx = json.loads(r.stdout)
    _eprint(f"[launch] baseline={ctx['baseline_bytes']}B truncated={ctx['baseline_truncated']}; "
            f"external={len(ctx['external_repos'])}; catalog={ctx['sensitive_catalog_source']}")
    return ctx


def _build_prompt(repo: Path, run_dir: Path, base: str, branch: str, ctx: dict,
                  host: str) -> str:
    """Orchestrator prompt file: verbatim absolute paths from the sdr_context stdout.
    The host agent's ONLY job is steps 2-5 of the shell (diff_group -> fanout -> render);
    step 1 (external retrieval) is ALREADY done here — the prompt says so explicitly so
    the orchestrator never re-reads an external repo."""
    ext = ctx.get("external_repos", [])
    skipped = ctx.get("external_skipped", [])
    lines = [
        "执行 /mgh-sdr 编排(单分支)。运行域已激活(哨兵已由 launcher 写入,含 read_roots);"
        "sdr_context 已完成——**NEVER** 重跑外部仓检索、**NEVER** 读外部仓原文路径。",
        "",
        f"repo(绝对根): {repo}",
        f"branch: {branch}",
        f"base: {base}",
        f"run 目录(绝对,产物全部落此): {run_dir}",
        f"检查基线(已投影): {ctx['baseline_path']}"
        f" (truncated={ctx['baseline_truncated']})",
        f"敏感目录来源: {ctx['sensitive_catalog_source']}"
        f"(敏感目录对象逐字透传给 subagent task,见下)",
        f"敏感目录对象: {json.dumps(ctx['sensitive_catalog'], ensure_ascii=False)[:4000]}",
        f"外部仓结论目录: {run_dir / 'external'}"
        + (f"({len(ext)} 仓: {', '.join(e['slug'] for e in ext)})"
           if ext else "(无:未声明/不可达降级)"),
    ]
    if skipped:
        lines.append(f"外部仓跳过披露: {'; '.join(skipped)}")
    time_budget = CLAUDE_TIME_BUDGET_MS if host == "claude" else OPENCODE_TIME_BUDGET_MS
    lines += [
        "",
        "按 /mgh-sdr 命令壳的 Orchestration flow 执行 step 2 起:",
        "2. `py <mgh-core>/scripts/diff_group.py --repo <repo> --base <base> --branch <branch> "
        "--checkpoints <run>/markers --materialize <run>/slices`;empty:true → 直接 step 4;"
        "跑 `--check <run>`。",
        f"3. `py <mgh-core>/scripts/fanout_runner.py --tier sdr --repo <repo> --base <base> "
        f"--branch <branch> --checkpoints <run>/markers --inputs-dir <run>/slices "
        f"--time-budget-ms {time_budget}`;partial:true → 同参重派;退出码 2 → 转述 stderr 停止。",
        "4. `py <mgh-core>/scripts/render_sdr_report.py --run-dir <run> --repo <repo>`;"
        "跑 `--check <run>`。",
        "5. 打印报告绝对路径 + counts;声明「发现是 LLM 候选需人工复核」;`rm <repo>/.mgh-sdr/.active`。",
        "",
        "铁律:NEVER Write 脚本扩展名;NEVER `py -c` 内省;NEVER Read 叶子 .py 源码;路径一律用"
        "脚本 stdout 给定的绝对路径逐字透传。",
    ]
    return "\n".join(lines) + "\n"


def _spawn_host(host: str, repo: Path, prompt: str) -> int:
    """Spawn the host CLI with the task message on stdin; return its exit code."""
    if host == "opencode":
        cmd = [shutil.which("opencode") or "opencode", "run"]
    else:
        cmd = [shutil.which("claude") or "claude", "-p"]
    _eprint(f"[launch] spawning {host} (task on stdin; cwd={repo})")
    try:
        r = subprocess.run(cmd, input=prompt, cwd=str(repo), text=True,
                           encoding="utf-8", errors="replace")
    except OSError as e:
        _eprint(f"error: host spawn failed: {e}")
        return 1
    return r.returncode


def _read_multi_branch(path: Path) -> list[str]:
    if not path.is_file():
        _eprint(f"error: --multi-branch file not found: {path}")
        sys.exit(2)
    branches = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        ln = raw.strip()
        if ln and not ln.startswith("#") and ln not in branches:
            branches.append(ln)
    if not branches:
        _eprint(f"error: --multi-branch file has no branch entries: {path}")
        sys.exit(2)
    return branches


def _run_one(repo: Path, branch: str, base: str, host: str, dims: str | None,
             read_roots: list[str], dry_run: bool) -> tuple[bool, str]:
    """One complete branch flow. Returns (ok, report_path_or_reason)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = repo / RUNS_REL / (f"{ts}-{_safe_name(branch)}")
    run_dir.mkdir(parents=True, exist_ok=True)
    _residual_sentinel(repo)
    try:
        ctx = _run_context(repo, run_dir, base, branch, dims, read_roots)
    except SystemExit:
        return False, f"sdr_context failed for {branch}"
    # sentinel read_roots = ACTUALLY SEARCHED external roots (+ operator --read-root);
    # NEVER a user-supplied catch-all (read_roots minimalism).
    roots = sorted({e["path"] for e in ctx.get("external_repos", []) if e.get("path")}
                   | set(read_roots))
    _write_sentinel(repo, roots)
    _eprint(f"[launch] sentinel written (read_roots={len(roots)} root(s))")
    prompt = _build_prompt(repo, run_dir, base, branch, ctx, host)
    prompt_path = run_dir / "orchestrator_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    _eprint(f"[launch] orchestrator prompt: {prompt_path}")
    if dry_run:
        _eprint("[launch] --dry-run: sentinel + prompt + sdr_context artifacts ready; "
                "NOT spawning the host CLI (sentinel kept for the next real run)")
        return True, str(prompt_path)
    try:
        code = _spawn_host(host, repo, prompt)
    finally:
        pass
    # the host session's step 5 also removes the sentinel; this is the launcher-side
    # guarantee (covers host crash-exit paths that skip step 5)
    _remove_sentinel(repo)
    if code != 0:
        return False, f"host CLI exited {code} for {branch}"
    reports = sorted(repo.glob("mgh-sdr-*.md"), key=lambda p: p.stat().st_mtime)
    report = str(reports[-1]) if reports else "(report not found — check host output)"
    return True, report


def main():
    ap = argparse.ArgumentParser(
        description="one-command launcher for /mgh-sdr (human/cron entry; external-repo "
                    "retrieval + sentinel + orchestrator prompt in this process, then "
                    "spawn the host CLI — zero permission prompts inside the run)")
    ap.add_argument("--repo", help="absolute target git repo root")
    ap.add_argument("--branch", default="", help="branch ref (default: current branch)")
    ap.add_argument("--base", default=DEFAULT_BASE,
                    help=f"base ref (default {DEFAULT_BASE})")
    ap.add_argument("--host", choices=["opencode", "claude"],
                    help="host CLI (default: opencode in PATH, else claude)")
    ap.add_argument("--dimensions", metavar="<inline-json>",
                    help="dimension set JSON, e.g. '{\"dimensions\":[\"sql-injection\"]}'")
    ap.add_argument("--multi-branch", metavar="<file>",
                    help="text file, one branch name per line (# comments ignored); "
                         "serial full flow per branch, failures recorded + continue")
    ap.add_argument("--read-root", action="append", metavar="<abs>",
                    help="extra confirmed read-only root for sentinel read_roots[] "
                         "(repeatable)")
    ap.add_argument("--dry-run", action="store_true",
                    help="gates + sdr_context + sentinel + prompt file, NO host spawn")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if not args.repo:
        _eprint("error: --repo <abs-target> is required")
        return 2
    repo = Path(args.repo).resolve()
    _gate(repo)
    host = _detect_host(args.host)
    branches = _read_multi_branch(Path(args.multi_branch)) if args.multi_branch \
        else [args.branch or _current_branch(repo)]

    failed: list[str] = []
    reports: list[str] = []
    for branch in branches:
        _eprint(f"[launch] === branch {branch} ===")
        ok, outcome = _run_one(repo, branch, args.base, host, args.dimensions,
                               args.read_root or [], args.dry_run)
        if ok:
            reports.append(outcome)
            _eprint(f"[launch] branch {branch}: ok -> {outcome}")
        else:
            failed.append(f"{branch}: {outcome}")
            _eprint(f"[launch] branch {branch}: FAILED ({outcome})")

    if failed:
        _eprint(f"[launch] FAILED BRANCHES ({len(failed)}):")
        for f in failed:
            _eprint(f"  - {f}")
        return 1
    print(json.dumps({"launcher": "mgh_sdr_launch", "host": host, "branches": branches,
                      "reports": reports, "dry_run": bool(args.dry_run)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
