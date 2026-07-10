#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
merge_augment — deterministic a5 for /mgh-sra: idempotently merge per-capability
augmentation drafts into the change's specs (<cap>/spec.md) and tasks.md via a
sentinel managed block, NON-destructively.

Managed block (one per target file):
    <!-- mgh-sra:begin -->
    ...augmented requirement / task entries (简体中文 prose, anchored)...
    <!-- mgh-sra:end -->

Idempotent (R5.3b): replaces only the managed block (or inserts if absent) and
preserves the block-OUTSIDE user content byte-for-byte across re-runs. Drafts are
JSON (see core/contracts/sra/augmentation.md) parsed deterministically. A snapshot
of each file's block-outside SHA is recorded so `--check` can prove user content
was not touched. All writes land under MGH_TARGET (the project subtree).

Zero runtime deps (Python >=3.10 stdlib: argparse/hashlib/json/re/sys/pathlib).

CLI contract (`--help` is the contract surface, R5.1):
  py merge_augment.py --change <name> [--drafts-dir <dir>] [--dry-run]
  py merge_augment.py --check [<change-name>]

  --change <name>   target change (default: newest under openspec/changes/)
  --drafts-dir      drafts dir (default: <change-root>/.mgh-sra/drafts)
  --dry-run         compute merges + write merge_state.json but do NOT edit specs/tasks
  --check [<name>]  post-merge validation: every touched file's block-OUTSIDE content
                    matches the snapshot recorded at merge time (exit 2 on drift), and
                    every managed block is well-formed (paired begin/end, single block).

stdout (structured JSON; stderr = diagnostics/progress only, R5.3b): a summary the
orchestrator folds into sra_manifest.json counts —
  {"merged":[{"capability","spec_path","requirements":N,"tasks":N,
              "referenced_controls":N,"dimensions":[...]}],
   "tasks_path":"...","written":bool,"checked":false}
In --check mode: {"check":"augment-merge","ok":bool,"files":N,"violations":[...]}.

Exit codes (R5.3b): 0 ok · 1 file missing / JSON malformed / change not found ·
2 misuse (argparse) or managed-block / snapshot violation (--check).
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BEGIN = "<!-- mgh-sra:begin -->"
END = "<!-- mgh-sra:end -->"
# The trailing `\n?` consumes the block's own trailing newline so the INSERT and
# REPLACE paths produce byte-identical output (idempotency): the rendered block
# always ends with `END\n`, and re-running replaces that exact span.
_BLOCK_RX = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", re.DOTALL)
_SECTION_RX = re.compile(r"(?m)^##\s+(?:ADDED|MODIFIED)\s+Requirements\s*$")


def _find_project_root(start: Path):
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / "openspec").is_dir():
            return cand
    return None


def _resolve_change(change):
    project_root = _find_project_root(Path.cwd())
    if project_root is None:
        print("error: not inside a project (no openspec/ dir found upward from cwd)",
              file=sys.stderr)
        sys.exit(1)
    changes_dir = project_root / "openspec" / "changes"
    if change:
        change_root = (changes_dir / change).resolve()
        if not change_root.is_dir():
            print(f"error: change not found: {change_root}", file=sys.stderr)
            sys.exit(1)
    else:
        candidates = [d for d in changes_dir.iterdir() if d.is_dir()]
        if not candidates:
            print(f"error: no unarchived changes under {changes_dir}", file=sys.stderr)
            sys.exit(1)
        change_root = max(candidates, key=lambda d: d.stat().st_mtime).resolve()
    return project_root, change_root


def _outside_text(content: str) -> str:
    """Block-outside content = file text with the managed block region removed."""
    return _BLOCK_RX.sub("", content, count=1)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_spec_block(draft: dict) -> str:
    """Render a draft's security_requirements as managed-block markdown."""
    lines = [BEGIN]
    dims = sorted({g.get("dimension") for g in draft.get("gaps", []) if g.get("dimension")})
    if dims:
        lines.append(f"<!-- 维度覆盖: {', '.join(dims)} (LLM 候选,需人工复核) -->")
    for req in draft.get("security_requirements", []):
        heading = req.get("heading", "Security requirement").strip()
        body = (req.get("body") or "").strip()
        lines.append("")
        lines.append(f"### Requirement: {heading}")
        if body:
            lines.append(body)
    lines.append(END)
    return "\n".join(lines) + "\n"


def _render_tasks_block(all_tasks: list) -> str:
    lines = [BEGIN]
    for t in all_tasks:
        s = t.strip() if isinstance(t, str) else str(t)
        if s:
            lines.append(s if s.startswith("- ") else f"- {s}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def _place_spec_block(content: str, block_text: str) -> str:
    """Replace existing managed block in place; else insert after the first
    ADDED|MODIFIED Requirements header; else append at EOF. Block-outside bytes
    are preserved (only the block region changes). `block_text` ends with `END\n`."""
    if BEGIN in content and END in content:
        return _BLOCK_RX.sub(lambda _: block_text, content, count=1)
    m = _SECTION_RX.search(content)
    if m:
        nl = content.find("\n", m.end())
        insert_at = (nl + 1) if nl != -1 else len(content)
        return content[:insert_at] + block_text + content[insert_at:]
    prefix = content
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix:
        prefix += "\n"  # one blank line between user content and the managed block
    return prefix + block_text


def _place_tasks_block(content: str, block_text: str) -> str:
    if BEGIN in content and END in content:
        return _BLOCK_RX.sub(lambda _: block_text, content, count=1)
    prefix = content
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix:
        prefix += "\n"
    return prefix + block_text


def _new_spec(cap: str, block_text: str) -> str:
    return f"# {cap}\n\n## ADDED Requirements\n\n{block_text}"


def _run_merge(args):
    project_root, change_root = _resolve_change(args.change)
    drafts_dir = Path(args.drafts_dir).resolve() if args.drafts_dir \
        else (change_root / ".mgh-sra" / "drafts")
    if not drafts_dir.is_dir():
        print(f"error: drafts dir not found: {drafts_dir}", file=sys.stderr)
        return 1
    drafts = sorted(drafts_dir.glob("*.md"))
    if not drafts:
        print(f"warn: no drafts in {drafts_dir}; nothing to merge", file=sys.stderr)

    specs_dir = change_root / "specs"
    tasks_path = change_root / "tasks.md"
    state_path = change_root / ".mgh-sra" / "merge_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    merged, all_tasks, state_files = [], [], {}
    for dp in drafts:
        try:
            draft = json.loads(dp.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"error: draft not valid JSON ({dp.name}): {e}", file=sys.stderr)
            return 2
        if not isinstance(draft, dict):
            print(f"error: draft {dp.name} is not a JSON object", file=sys.stderr)
            return 2
        cap = draft.get("capability") or dp.stem
        spec_path = specs_dir / cap / "spec.md"

        block_text = _render_spec_block(draft)
        existing = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        if spec_path.is_file():
            new_content = _place_spec_block(existing, block_text)
        else:
            new_content = _new_spec(cap, block_text)

        if not args.dry_run:
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(new_content, encoding="utf-8")
        state_files[str(spec_path.relative_to(change_root)).replace("\\", "/")] = _sha(_outside_text(new_content))

        sec_reqs = draft.get("security_requirements", [])
        sec_tasks = draft.get("security_tasks", [])
        all_tasks.extend(sec_tasks)
        ref_controls = {g.get("recommended_control", {}).get("name")
                        for g in draft.get("gaps", [])
                        if g.get("recommended_control")}
        dims = sorted({g.get("dimension") for g in draft.get("gaps", []) if g.get("dimension")})
        merged.append({
            "capability": cap,
            "spec_path": str(spec_path),
            "requirements": len(sec_reqs),
            "tasks": len(sec_tasks),
            "referenced_controls": len({c for c in ref_controls if c}),
            "dimensions": dims,
        })

    # tasks.md block (aggregated across all drafts)
    tasks_block = _render_tasks_block(all_tasks)
    tasks_existing = tasks_path.read_text(encoding="utf-8") if tasks_path.is_file() else ""
    tasks_new = _place_tasks_block(tasks_existing, tasks_block) if all_tasks else tasks_existing
    if all_tasks and not args.dry_run:
        tasks_path.write_text(tasks_new, encoding="utf-8")
    if all_tasks:
        state_files["tasks.md"] = _sha(_outside_text(tasks_new))

    if not args.dry_run:
        state_path.write_text(json.dumps({"files": state_files}, ensure_ascii=False, indent=2),
                              encoding="utf-8")

    written = not args.dry_run and bool(drafts)
    summary = {"merged": merged, "tasks_path": str(tasks_path),
               "written": written, "checked": False}
    print(f"[merge_augment] change={change_root.name} drafts={len(drafts)} "
          f"specs={len(merged)} tasks={len(all_tasks)} written={written}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _run_check(args):
    project_root, change_root = _resolve_change(args.check or args.change)
    state_path = change_root / ".mgh-sra" / "merge_state.json"
    if not state_path.is_file():
        print(f"error: no merge_state.json at {state_path} (run merge first)", file=sys.stderr)
        return 1
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"error: merge_state.json malformed: {e}", file=sys.stderr)
        return 1
    files = state.get("files") or {}
    violations = []
    for rel, expected_sha in files.items():
        fp = change_root / rel
        if not fp.is_file():
            violations.append(f"{rel}: file missing since merge")
            continue
        content = fp.read_text(encoding="utf-8")
        n_blocks = len(_BLOCK_RX.findall(content))
        if n_blocks > 1:
            violations.append(f"{rel}: {n_blocks} managed blocks (expected ≤1)")
        if (BEGIN in content) != (END in content):
            violations.append(f"{rel}: unpaired managed-block sentinel")
        actual_sha = _sha(_outside_text(content))
        if actual_sha != expected_sha:
            violations.append(f"{rel}: block-OUTSIDE content changed since merge")
    ok = not violations
    summary = {"check": "augment-merge", "ok": ok, "files": len(files), "violations": violations}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[merge_augment] --check {change_root.name}: files={len(files)} ok={ok} "
          f"violations={len(violations)}", file=sys.stderr)
    return 0 if ok else 2


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="a5 for /mgh-sra: idempotent non-destructive managed-block merge "
                    "of augmentation drafts into change specs + tasks")
    ap.add_argument("--change", help="target change name (default: newest under openspec/changes/)")
    ap.add_argument("--drafts-dir", help="drafts dir (default: <change-root>/.mgh-sra/drafts)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute + write merge_state.json but do NOT edit specs/tasks")
    ap.add_argument("--check", nargs="?", const="", default=None, metavar="CHANGE",
                    help="post-merge validation: block-outside content matches snapshot + "
                         "managed blocks well-formed (optional change name; default newest)")
    args = ap.parse_args()

    if args.check is not None:
        return _run_check(args)
    return _run_merge(args)


if __name__ == "__main__":
    sys.exit(main())
