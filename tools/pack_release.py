#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""pack_release.py — zip a staging install tree into a distribution package
(add-mgh-opencode-pack; called by install.sh --pack, never by any mgh-* shell).

Input : --staging <dir>   a completed opencode staging install
        --out <zip>       output path (parent dirs auto-created; overwrite = idempotent)
Output: stdout = one JSON summary line {"staging","out","files","bytes"}; stderr = diagnostics
Exit  : 0 ok / 2 misuse or failure (staging missing, output unwritable, bytecode residue)

Before zipping, deterministically strips build-machine residue from the staging tree
(__pycache__ dirs and loose .pyc/.pyo files), then asserts none remain — the shipped
zip never carries foreign-machine bytecode.
"""
import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

BYTECODE_SUFFIXES = {".pyc", ".pyo"}


def _strip_bytecode(staging: Path) -> None:
    for d in list(staging.rglob("__pycache__")):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
    for f in staging.rglob("*"):
        if f.is_file() and f.suffix.lower() in BYTECODE_SUFFIXES:
            f.unlink()


def _bytecode_leftovers(staging: Path):
    return [p for p in staging.rglob("*")
            if p.name == "__pycache__"
            or (p.is_file() and p.suffix.lower() in BYTECODE_SUFFIXES)]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Zip a staging install tree into a distribution package (opencode release).")
    ap.add_argument("--staging", required=True,
                    help="staging directory holding a completed install")
    ap.add_argument("--out", required=True,
                    help="output zip path (overwrites; parent dirs created)")
    args = ap.parse_args(argv)

    staging = Path(args.staging)
    if not staging.is_dir():
        print(f"✗ staging dir missing: {staging}", file=sys.stderr)
        return 2
    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"✗ cannot create output dir {out.parent}: {e}", file=sys.stderr)
        return 2

    _strip_bytecode(staging)
    leftovers = _bytecode_leftovers(staging)
    if leftovers:
        print("✗ bytecode residue survived stripping (remove manually and retry):",
              file=sys.stderr)
        for p in leftovers[:20]:
            print(f"  {p}", file=sys.stderr)
        return 2

    files = sorted(p for p in staging.rglob("*") if p.is_file())
    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            for f in files:
                z.write(f, arcname=f.relative_to(staging).as_posix())
    except OSError as e:
        print(f"✗ zip write failed: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"staging": str(staging), "out": str(out),
                      "files": len(files), "bytes": out.stat().st_size}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
