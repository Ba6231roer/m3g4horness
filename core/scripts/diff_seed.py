#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
diff_seed — compute the seed file set for incremental scanning from a git diff.

Stdlib only. Invoked by the scope-resolver before call-chain expansion.

Usage:
  py diff_seed.py --repo <root> --diff <ref> [--out scope_seed.json]
  py diff_seed.py --repo <root> --diff origin/main

Seed = files that are Added or Modified (or renamed-into) relative to <ref>.
Deleted files are NOT seeds, but are recorded separately so the call-chain
expander can still resolve symbols that used to live there.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

# Extensions we treat as scannable source (call-graph relevant).
SOURCE_EXT = {
    ".java", ".kt", ".scala", ".py", ".js", ".jsx", ".ts", ".tsx", ".go",
    ".cs", ".rb", ".php", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".m",
    ".swift", ".rs", ".clj", ".groovy", ".ts", ".sql",
}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def changed_files(repo: Path, ref: str):
    """Return (seed_paths, deleted_paths) relative to repo, POSIX style.

    Uses `git diff --name-status <ref>` (unstaged+staged vs ref). If <ref> is
    unknown, raises with the git error so the caller can surface it.
    """
    # Validate the ref resolves (avoids a confusing empty diff on a bad ref).
    _git(repo, "rev-parse", "--verify", ref if "..." not in ref else ref.split("...")[0])
    out = _git(repo, "diff", "--name-status", ref)
    seed, deleted = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        paths = parts[1:]
        if not paths:
            continue
        # Rename: Rxx  old  new -> new path is the seed.
        if status.startswith("R") or status.startswith("C"):
            target = paths[-1]
        elif status.startswith("D"):
            deleted.append(paths[0])
            continue
        else:
            target = paths[0]
        if Path(target).suffix.lower() in SOURCE_EXT:
            seed.append(target.replace("\\", "/"))
    # de-dup, preserve order
    seen = set(); seed = [x for x in seed if not (x in seen or seen.add(x))]
    seen = set(); deleted = [x for x in deleted if not (x in seen or seen.add(x))]
    return seed, deleted


def main():
    ap = argparse.ArgumentParser(description="compute incremental scan seed from git diff")
    ap.add_argument("--repo", required=True, help="repo root")
    ap.add_argument("--diff", required=True, help="git ref, e.g. origin/main or HEAD~3")
    ap.add_argument("--out", default=None, help="write JSON here (default: stdout summary)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    seed, deleted = changed_files(repo, args.diff)
    payload = {"ref": args.diff, "seed": seed, "deleted": deleted,
               "seed_count": len(seed), "deleted_count": len(deleted)}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
    if not seed:
        print(f"[diff_seed] no scannable changes vs '{args.diff}' — nothing to scan",
              file=sys.stderr)
    print(json.dumps({"seed_count": len(seed), "deleted_count": len(deleted),
                      "ref": args.diff}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
