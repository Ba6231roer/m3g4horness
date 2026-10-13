#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
mgh_sdr_launch — one-command launcher for /mgh-sdr (the human/cron entry; NEVER called
by a host subagent). THIS SCRIPT SHIPS WITH INSTALL (core/scripts/), so a manager runs
the full review without cloning this dev repo:

  py mgh_sdr_launch.py --repo <abs-target> [--branch <ref>] [--base <ref>]
      [--host opencode|claude] [--dimensions <json>] [--multi-branch <file>]
      [--read-root <abs>]... [--model <provider/model>] [--open] [--dry-run]

Why a launcher: the two experience/safety problems of an external (frontend) repo are
solved OUTSIDE the host CLI session —
  1. permission interruption: the external-repo controlled retrieval (sdr_context.py)
     runs IN THIS PROCESS, before any host CLI is spawned. The host session (and its
     subagents) only ever sees materialized conclusion files => zero permission prompts
     inside the run. The explicitly confirmed external roots land in the disk sentinel's
     read_roots[] (tool-face read-only escape valve). AUTHORIZATION: retrieval is gated
     on the project config <repo>/.mgh/read-roots.json — a DECLARED repo that is not
     configured there is NEVER read (zero reads): this process skips it (stderr warn),
     omits it from the sentinel read_roots[], and discloses it via stdout/
     orchestrator-prompt `pending_approval[]` for the host-session user decision
     (approve => `sdr_context.py --approve-external <abs>` — one command closing approve +
     config write + retrieval, ONLY after the USER explicitly approved — or the equivalent
     `read_roots_config.py --add` + re-run this launcher with the same arguments; the
     config takes effect on the next run). The gate is judged twice with
     the same resolve-normalized semantics — inside sdr_context.py before retrieval AND
     here before the sentinel write (version-skew defense).
  2. lifecycle ownership: this process writes <repo>/.mgh-sdr/.active (with target +
     read_roots) before spawning and REMOVES it after the host CLI exits. A crash leaves
     the sentinel behind; the next launcher start detects a same-target residual,
     reuses + refreshes it (resume semantics) instead of silently locking daily dev.

Per-branch flow (single branch, or serially per --multi-branch line):
  BRANCH PRE-CHECK (git rev-parse --verify: the ref must resolve; a failed check is a
  deterministic early failure — zero host spawn, zero LLM spend, zero run dir / sentinel /
  prompt side effects — recorded FAILED and the sweep continues; true run, --dry-run,
  single-branch and --multi-branch all share this same first gate) -> gate (repo + host
  CLI in PATH; --host explicit > opencode > claude; none => exit 2 + recipe) -> run dir
  <repo>/.mgh-sdr/runs/<ts[-branch]>/ -> sdr_context.py (external retrieval + baseline +
  sensitive catalog, IN THIS PROCESS, which also co-writes the guard sentinel + the
  run_config.json codegraph signal) -> sentinel refresh (idempotent; read_roots =
  actually-searched roots + --read-root additions, re-judged against the project config
  as the second authorization gate) -> orchestrator prompt file (verbatim absolute paths
  from the sdr_context stdout) -> spawn host CLI (`opencode run --print-logs --log-level
  ERROR` with the task on stdin / `claude -p` likewise; claude gets a 480000ms
  soft-deadline note — claude Bash per-call cap 600000 x 0.8; the child env is spawned
  WITHOUT `PWD` so the host resolves the project by the explicit cwd = the target repo)
  -> sentinel removal -> report claim: the ONLY accepted source is THIS branch's run-dir
  `sdr_manifest.json` `report` field (the renderer's deterministic co-product); missing
  manifest or report file not on disk => FAILED (no-report) — a repo-root
  `mgh-sdr-*.html` glob is NEVER consulted, so cross-branch report claiming is
  structurally impossible.

--multi-branch <file>: a local text file, one branch name per line (`#` comments and
blank lines ignored); each branch runs the COMPLETE flow serially with its own run dir
(+= "-<branch-safe>") + report + sentinel lifecycle; a branch failure is recorded and
the loop continues; launcher exit 1 iff any branch failed.

--dry-run: the SAME branch pre-check runs first (an unresolvable branch ref fails the
dry-run too — a green smoke must not bless an invalid branch list), then gates +
sdr_context + sentinel + prompt file, then STOPS before spawning (zero host CLI
invocation); the sentinel is KEPT (the next real run reuses it) — exit 0 only if every
branch passed the pre-check.

--model <provider/model>: passed through to the host CLI verbatim (`opencode run
--model` / `claude -p --model`); omitted => no model flag is appended (the host's own
default applies).

Exit codes (R5.3b): 0 all branches ok (incl. --dry-run) · 1 runtime failure (>=1 branch
FAILED: branch not found / sdr_context failed / host CLI exited non-zero / host exited 0
but produced no report) · 2 misuse (argparse / host missing / repo not a git work tree).
A branch ref that does not resolve is a per-branch FAILED (exit 1 via the failure
summary), NEVER a launcher abort.

Zero runtime deps (Python >=3.10 stdlib: argparse/json/subprocess/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import os
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
# fanout_runner four-level invariant: stall-timeout-s < call-timeout-s < budget-ms x 0.8.
# Values here pair with the budgets above (480000->360 / 720000->540); fanout_runner
# re-validates at spawn time (exit 2 on violation).
CALL_TIMEOUT_S = {"claude": 360, "opencode": 540}
STALL_TIMEOUT_S = 300


def _eprint(*a):
    print(*a, file=sys.stderr)


class _UpstreamOutputError(Exception):
    """sdr_context stdout missing/misshaped (fix-mgh-sdr-docs-shell-alignment L2):
    consumed as a per-branch FAILED record (stderr reason, later branches continue,
    exit-code semantics unchanged) — NEVER a bare traceback out of the launcher."""


def _req(ctx: dict, key: str):
    """Hard field access over upstream stdout with a typed failure (L2)."""
    try:
        v = ctx[key]
    except (KeyError, TypeError) as e:
        raise _UpstreamOutputError(f"sdr_context stdout missing field {key!r}") from e
    if v is None:
        raise _UpstreamOutputError(f"sdr_context stdout field {key!r} is null")
    return v


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
    """Idempotent REFRESH of `<repo>/.mgh-sdr/.active` (same content source as
    `sdr_context._write_run_state`, which always runs earlier in this process).

    It is kept (rather than deleted as redundant) because it is the second
    authorization judgment: the roots are re-checked against the project config
    immediately before the host CLI is spawned, so a version-skewed sibling cannot
    leak an unapproved root into `read_roots[]`. Same semantics, same content
    source — not a second truth."""
    sp = repo / SENTINEL_REL
    sp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sp.with_suffix(".tmp")
    tmp.write_text(json.dumps(_sentinel_body(repo, read_roots), ensure_ascii=False),
                   encoding="utf-8")
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


def _approved_read_roots(repo: Path) -> set[str]:
    """Resolve-normalized strings of <repo>/.mgh/read-roots.json entries that exist and
    are directories. Twin of sdr_context._approved_read_roots (same fail-closed
    semantics as the guard's config reader) — the launcher re-judges the gate before the
    sentinel write so a version-skewed sibling cannot leak an unapproved root into
    read_roots[]."""
    cfg = repo / ".mgh" / "read-roots.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    roots = data.get("read_roots")
    if not isinstance(roots, list):
        return set()
    out: set[str] = set()
    for r in roots:
        if not isinstance(r, str) or not r.strip():
            continue
        try:
            p = Path(r.strip()).resolve()
        except OSError:
            continue
        if p.is_dir():
            out.add(str(p))
    return out


def _is_approved(path: str, approved: set[str]) -> bool:
    try:
        return str(Path(path).resolve()) in approved
    except OSError:
        return False


def _run_context(repo: Path, run_dir: Path, base: str, branch: str, dims: str | None,
                 read_roots: list[str], no_codegraph: bool = False) -> dict:
    """sdr_context.py IN THIS PROCESS (external retrieval happens with the user's
    explicit authorization — the shell session that launched this command). It also
    co-writes the guard sentinel and the `run_config.json` codegraph signal; the
    launcher's own `_write_sentinel` below is a same-source idempotent refresh."""
    cmd = [sys.executable, _script_path("sdr_context.py"),
           "--repo", str(repo), "--run-dir", str(run_dir),
           "--base", base, "--branch", branch]
    if dims:
        cmd += ["--dimensions", dims]
    if no_codegraph:
        cmd += ["--no-codegraph"]
    for rr in read_roots:
        cmd += ["--read-root", rr]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if r.returncode != 0:
        _eprint(f"error: sdr_context.py exited {r.returncode}:\n{(r.stderr or '')[-600:]}")
        sys.exit(1 if r.returncode == 1 else 2)
    # L2 upstream-output guard: a missing/garbled/misshaped stdout (version-skewed
    # sibling, broken install) is a per-branch FAILED — never a bare traceback.
    try:
        ctx = json.loads(r.stdout)
        _eprint(f"[launch] baseline={ctx['baseline_bytes']}B truncated={ctx['baseline_truncated']}; "
                f"external={len(ctx['external_repos'])}; "
                f"pending_approval={len(ctx.get('pending_approval') or [])}; "
                f"catalog={ctx['sensitive_catalog_source']}")
    except (ValueError, KeyError, TypeError) as e:
        raise _UpstreamOutputError(
            f"sdr_context stdout unparsable or misshaped ({e!r}) — upstream artifact "
            f"unusable; run dir kept on disk for inspection") from e
    return ctx


def _build_prompt(repo: Path, run_dir: Path, base: str, branch: str, ctx: dict,
                  host: str) -> str:
    """Orchestrator prompt file: verbatim absolute paths from the sdr_context stdout.
    The host agent's ONLY job is steps 2-5 of the shell (diff_group -> fanout -> render);
    step 1 (external retrieval) is ALREADY done here — the prompt says so explicitly so
    the orchestrator never re-reads an external repo. The sensitive catalog is pointed
    at as a read-only file path, NEVER embedded (no truncation happens on this object):
    the task template carries the path to every subagent, same shape as the external
    conclusions."""
    ext = ctx.get("external_repos", [])
    skipped = ctx.get("external_skipped", [])
    catalog_path = ctx.get("sensitive_catalog_path") \
        or str((run_dir / "sensitive_catalog.json").resolve())
    lines = [
        "执行 /mgh-sdr 编排(单分支)。运行域已激活(哨兵已由 launcher 写入,含 read_roots);"
        "sdr_context 已完成——**NEVER** 重跑外部仓检索、**NEVER** 读外部仓原文路径。",
        "",
        f"repo(绝对根): {repo}",
        f"branch: {branch}",
        f"base: {base}",
        f"run 目录(绝对,产物全部落此): {run_dir}",
        f"检查基线(已投影): {_req(ctx, 'baseline_path')}"
        f" (truncated={_req(ctx, 'baseline_truncated')})",
        f"敏感目录来源: {_req(ctx, 'sensitive_catalog_source')}"
        f"(解析后目录已物化为 run 目录内独立文件——subagent 任务消息只携带该文件只读路径,"
        f"NEVER 内嵌对象本体,NEVER 截断)",
        f"敏感目录文件(只读,绝对路径): {catalog_path}",
        f"外部仓结论目录: {run_dir / 'external'}"
        + (f"({len(ext)} 仓: {', '.join(e['slug'] for e in ext)})"
           if ext else "(无:未声明/不可达降级)"),
    ]
    if skipped:
        lines.append(f"外部仓跳过披露: {'; '.join(skipped)}")
    pending = ctx.get("pending_approval") or []
    if pending:
        lines += [
            "",
            "外部仓待批(存量设计声明、但未经用户写入项目配置;本次零检索,相关检查面未覆盖):",
            *[f"- {p}" for p in pending],
            "处理:在宿主会话向用户呈现以上清单并请求决策。同意 → 推荐:给 step 1 的 "
            f"`sdr_context.py` 加 `--approve-external <以上绝对路径>`(逐仓可重复)重跑一次"
            "——批准 + 写配置 + 检索一条命令闭环(该 flag 仅在宿主会话获用户明示同意后传入);"
            "等价路径:逐仓执行 "
            f"`py {_script_path('read_roots_config.py')} --target {repo} --add <以上绝对路径>`"
            f"(写 <repo>/.mgh/read-roots.json,即时生效),然后重跑本 launcher 同参数完成检索;"
            "拒绝 → 不写配置,按当前降级继续,报告如实披露。",
            "铁律:**NEVER 未经用户明确同意写配置**。",
        ]
    time_budget = CLAUDE_TIME_BUDGET_MS if host == "claude" else OPENCODE_TIME_BUDGET_MS
    call_timeout = CALL_TIMEOUT_S[host]
    lines += [
        "",
        "按 /mgh-sdr 命令壳的 Orchestration flow 执行 step 2 起:",
        "2. `py <mgh-core>/scripts/diff_group.py --repo <repo> --base <base> --branch <branch> "
        "--checkpoints <run>/markers --materialize <run>/slices`;empty:true → 直接 step 4;"
        "跑 `--check <run>`。",
        f"3. `py <mgh-core>/scripts/fanout_runner.py --tier sdr --repo <repo> --base <base> "
        f"--branch <branch> --checkpoints <run>/markers --inputs-dir <run>/slices "
        f"--time-budget-ms {time_budget} --call-timeout-s {call_timeout} "
        f"--stall-timeout-s {STALL_TIMEOUT_S}`(带 per-call `timeout` ≥ "
        f"{time_budget}ms 跑;四级超时不变式已按此组合满足,NEVER 省略 call/stall 两级)"
        f";partial:true → 同参重派;退出码 2 → 转述 stderr 停止。",
        "4. `py <mgh-core>/scripts/render_sdr_report.py --run-dir <run> --repo <repo>`;"
        "跑 `--check <run>`。",
        "5. 打印报告绝对路径 + counts;声明「发现是 LLM 候选需人工复核」;`rm <repo>/.mgh-sdr/.active`。",
        "",
        "铁律:NEVER Write 脚本扩展名;NEVER `py -c` 内省;NEVER Read 叶子 .py 源码;路径一律用"
        "脚本 stdout 给定的绝对路径逐字透传。",
    ]
    return "\n".join(lines) + "\n"


def _spawn_host(host: str, repo: Path, prompt: str, model: str | None = None) -> int:
    """Spawn the host CLI with the task message on stdin; return its exit code.

    opencode gets `--print-logs --log-level ERROR` (provider-shaped failures must be
    diagnosable from this process's stderr — an error envelope line alone is not);
    claude takes no log flags. `--model` is passed through verbatim to either host,
    appended only when given. Env hygiene: the child env is `os.environ` WITHOUT `PWD`
    — opencode resolves the project by `PWD ?? cwd`, so an inherited PWD (whatever dir
    this launcher was started from) would land the session in the WRONG project; with
    it stripped the host falls back to the explicit cwd = the target repo. claude takes
    the same path (it does not read PWD; stripping is harmless)."""
    if host == "opencode":
        cmd = [shutil.which("opencode") or "opencode", "run",
               "--print-logs", "--log-level", "ERROR"]
    else:
        cmd = [shutil.which("claude") or "claude", "-p"]
    if model:
        cmd += ["--model", model]
    _eprint(f"[launch] spawning {host} (task on stdin; cwd={repo})")
    try:
        env = {k: v for k, v in os.environ.items() if k != "PWD"}
        r = subprocess.run(cmd, input=prompt, cwd=str(repo), env=env, text=True,
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
             read_roots: list[str], dry_run: bool,
             no_codegraph: bool = False,
             model: str | None = None) -> tuple[bool, str, list[str]]:
    """One complete branch flow. Returns (ok, report_path_or_reason, pending_approval)."""
    # BRANCH PRE-CHECK — the very first act, before ANY side effect (run dir creation,
    # sdr_context, sentinel, prompt file, spawn): the ref must resolve to an object in
    # the target repo (wide form: branch / tag / short SHA all pass, matching what
    # `git diff base..branch` accepts). Failure is a deterministic early failure — zero
    # host spawn, zero LLM spend, zero artifacts. True run, --dry-run, single-branch and
    # --multi-branch all share this one gate (a green --dry-run therefore really vouches
    # for the branch list).
    if _git(repo, "rev-parse", "--verify", "--quiet", branch).returncode != 0:
        _eprint(f"[launch] branch {branch}: FAILED pre-check (ref does not resolve) — "
                f"zero spawn, zero artifacts; sweep continues")
        return False, f"branch not found: {branch}", []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = repo / RUNS_REL / (f"{ts}-{_safe_name(branch)}")
    run_dir.mkdir(parents=True, exist_ok=True)
    _residual_sentinel(repo)
    try:
        ctx = _run_context(repo, run_dir, base, branch, dims, read_roots, no_codegraph)
    except SystemExit:
        return False, f"sdr_context failed for {branch}", []
    except _UpstreamOutputError as e:
        # L2: upstream stdout unusable => this branch records FAILED (reason on
        # stderr via the summary), later branches continue; a sentinel the step
        # already wrote stays for the recovery entries to detect (same failure-path
        # sentinel semantics as the sdr_context-exit branch above)
        return False, f"sdr_context upstream output unusable for {branch}: {e}", []
    pending = list(ctx.get("pending_approval") or [])
    for p in pending:
        _eprint(f"[launch] WARN: external repo declared but NOT approved — zero reads, "
                f"skipped, pending user approval: {p}\n"
                f"  approve (recommended): re-run sdr_context.py for this run dir with "
                f"--approve-external {p} (carry it ONLY after the USER explicitly "
                f"approved in the host session; one command closes approve + config "
                f"write + retrieval)\n"
                f"  approve (equivalent): py {_script_path('read_roots_config.py')} "
                f"--target {repo} --add {p}   (writes <repo>/.mgh/read-roots.json), "
                f"then re-run this command unchanged")
    # sentinel read_roots = ACTUALLY SEARCHED external roots (+ operator --read-root);
    # NEVER a user-supplied catch-all (read_roots minimalism). Every retrieved root is
    # re-judged against the project config here (second gate judgment — sdr_context
    # already gated before retrieval; this catches version skew).
    approved = _approved_read_roots(repo)
    roots = sorted({e["path"] for e in ctx.get("external_repos", []) if e.get("path")
                    and _is_approved(e["path"], approved)}
                   | set(read_roots))
    _write_sentinel(repo, roots)
    _eprint(f"[launch] sentinel written (read_roots={len(roots)} root(s))")
    try:
        prompt = _build_prompt(repo, run_dir, base, branch, ctx, host)
    except _UpstreamOutputError as e:
        # L2: hard field access over the upstream record failed => per-branch FAILED,
        # not a traceback; the just-refreshed sentinel stays (recovery entries detect
        # + re-arm it; the next launcher start reuses it)
        return False, f"sdr_context upstream output unusable for {branch}: {e}", []
    prompt_path = run_dir / "orchestrator_prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    _eprint(f"[launch] orchestrator prompt: {prompt_path}")
    if dry_run:
        _eprint("[launch] --dry-run: sentinel + prompt + sdr_context artifacts ready; "
                "NOT spawning the host CLI (sentinel kept for the next real run)")
        return True, str(prompt_path), pending
    code = _spawn_host(host, repo, prompt, model)
    # the host session's step 5 also removes the sentinel; this is the launcher-side
    # guarantee (covers host crash-exit paths that skip step 5)
    _remove_sentinel(repo)
    if code != 0:
        return False, f"host CLI exited {code} for {branch}", pending
    # Report claim: the ONLY source is THIS branch's run-dir sdr_manifest.json `report`
    # field (the renderer's deterministic co-product, atomically written in the same
    # transaction as the report — a successful render always leaves the manifest, so a
    # missing manifest / missing report file means the render never happened => FAILED,
    # never a repo-root `mgh-sdr-*.html` mtime guess: cross-branch claiming is
    # structurally impossible on this path).
    report = None
    try:
        manifest = json.loads((run_dir / "sdr_manifest.json").read_text(encoding="utf-8"))
        cand = manifest.get("report")
        if isinstance(cand, str) and Path(cand).is_file():
            report = cand
    except (OSError, ValueError):
        pass
    if report is None:
        return False, f"no report produced for {branch}", pending
    return True, report, pending


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
    ap.add_argument("--model", metavar="<provider/model>",
                    help="model id passed through to the host CLI (`opencode run "
                         "--model` / `claude -p --model`); omitted => no model flag "
                         "is appended (the host's own default applies)")
    ap.add_argument("--no-codegraph", action="store_true",
                    help="mark the codegraph SIGNAL off in the run's run_config.json "
                         "(dispatcher-side `{{codegraph}}` placeholder becomes off). The "
                         "signal is otherwise DERIVED by sdr_context.py from the repo "
                         "(`<repo>/.codegraph/` present AND a `codegraph` binary on PATH) "
                         "— the same predicate the grouping stage uses, so both entries "
                         "report the same fact without a flag. This flag affects the "
                         "SIGNAL ONLY: grouping always probes for itself, so reviewers "
                         "judge conservatively without the grouping changing")
    ap.add_argument("--open", action="store_true",
                    help="open each branch's HTML report in the default browser as it "
                         "completes (stdlib webbrowser; default off — the launcher "
                         "stays side-effect-free unless this flag is passed)")
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
    pending_all: list[str] = []
    for branch in branches:
        _eprint(f"[launch] === branch {branch} ===")
        ok, outcome, pending = _run_one(repo, branch, args.base, host, args.dimensions,
                                        args.read_root or [], args.dry_run,
                                        args.no_codegraph, args.model)
        pending_all.extend(p for p in pending if p not in pending_all)
        if ok:
            reports.append(outcome)
            _eprint(f"[launch] branch {branch}: ok -> {outcome}")
            # --open only fires on an actual report file (a --dry-run's outcome is the
            # orchestrator prompt path, never opened)
            if args.open and outcome.endswith(".html") and Path(outcome).is_file():
                import webbrowser
                webbrowser.open(Path(outcome).resolve().as_uri())
        else:
            failed.append(f"{branch}: {outcome}")
            _eprint(f"[launch] branch {branch}: FAILED ({outcome})")

    if failed:
        _eprint(f"[launch] FAILED BRANCHES ({len(failed)}):")
        for f in failed:
            _eprint(f"  - {f}")
        if pending_all:
            _eprint("[launch] pending_approval (external repos skipped, need user "
                    "approval):")
            for p in pending_all:
                _eprint(f"  - {p}")
        return 1
    print(json.dumps({"launcher": "mgh_sdr_launch", "host": host, "branches": branches,
                      "reports": reports, "dry_run": bool(args.dry_run),
                      "pending_approval": pending_all},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
