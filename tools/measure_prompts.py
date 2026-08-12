#!/usr/bin/env python3
"""Measure prompt/agent/fragment files for prompt-length budgeting.

Dev-time tool (tools/, NOT distributed; stdlib-only per R2). Feeds the
150K-context prompt-budget analysis (see docs/) and the future R5.6 budget
lint. Self-contained, any cwd (R5.3a); stdout=JSON / stderr=progress (R5.3b).

What it measures per file (all EXACT, deterministic):
  lines, chars (code points), cjk chars, ascii chars, other multibyte, utf-8 bytes.

Token estimate (RANGE — tokenizers differ; state the model, never claim exact):
  ascii  : 4.0 chars/token   (well-established for English/code/markdown)
  cjk/other multibyte : <cjk-ratio> chars/token
    default central 1.5, low 2.0 (more efficient), high 1.2 (less efficient)
  => reported as {low, mid, high}; budget decisions anchor in chars/lines.

Usage:
  py tools/measure_prompts.py [paths...]            # files or dirs (recurse *.md)
  py tools/measure_prompts.py --root .              # measure the known prompt tree
  py tools/measure_prompts.py --group-by prefix:N   # roll up by path prefix (first N segs)
"""
import argparse
import json
import re
import sys
from pathlib import Path

# CJK + CJK punctuation + fullwidth forms. Treat all as "dense" (inefficient) tokens.
CJK_RE = re.compile(r"[　-〿㐀-鿿豈-﫿＀-￯\U00020000-\U0002a6df]")


def measure_text(text: str) -> dict:
    chars = len(text)
    cjk = len(CJK_RE.findall(text))
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    other = chars - cjk - ascii_chars  # other multibyte (accented, emoji, etc.) — treat dense
    bytes_utf8 = len(text.encode("utf-8"))
    lines = text.count("\n") + (0 if text.endswith("\n") else (1 if text else 0))
    return {"lines": lines, "chars": chars, "cjk": cjk,
            "ascii": ascii_chars, "other": other, "bytes": bytes_utf8}


def token_range(m: dict, cjk_low=2.0, cjk_high=1.2, cjk_mid=1.5) -> dict:
    """chars-per-token: higher ratio = fewer tokens (more efficient)."""
    dense = m["cjk"] + m["other"]

    def tk(chars_per_token: float) -> float:
        return m["ascii"] / 4.0 + dense / chars_per_token
    return {"low_tokens": round(tk(cjk_low)),   # most efficient estimate
            "mid_tokens": round(tk(cjk_mid)),
            "high_tokens": round(tk(cjk_high))}  # least efficient estimate


def iter_files(paths):
    for p in paths:
        path = Path(p)
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("*.md"))
        else:
            print(f"skip (not found): {p}", file=sys.stderr)


def measure_one(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    m = measure_text(text)
    m["path"] = str(path).replace("\\", "/")
    m.update(token_range(m))
    return m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure prompt files for budget analysis.")
    ap.add_argument("paths", nargs="*", help="files or dirs (recurse *.md)")
    ap.add_argument("--root", help="measure the known mgh-* prompt tree under this repo root")
    ap.add_argument("--group-by", dest="group_by",
                    help="roll up by path prefix: 'prefix:N' = first N path segments")
    args = ap.parse_args(argv)

    files = list(args.paths) if args.paths else []
    if args.root:
        root = Path(args.root)
        # Known prompt-bearing locations (mirrors AGENTS.md 目录布局).
        files += [root / "AGENTS.md", root / "CLAUDE.md",
                  root / "releases" / "claude-code" / "commands",
                  root / "releases" / "claude-code" / "agents",
                  root / "releases" / "opencode" / "command",
                  root / "releases" / "opencode" / "agent",
                  root / "core" / "prompts"]

    if not files:
        ap.error("no paths given (pass paths or --root)")

    measured = [measure_one(f) for f in iter_files(files)]

    # Aggregate totals (deterministic).
    agg = {"lines": sum(m["lines"] for m in measured),
           "chars": sum(m["chars"] for m in measured),
           "cjk": sum(m["cjk"] for m in measured),
           "ascii": sum(m["ascii"] for m in measured),
           "other": sum(m["other"] for m in measured),
           "bytes": sum(m["bytes"] for m in measured),
           "low_tokens": sum(m["low_tokens"] for m in measured),
           "mid_tokens": sum(m["mid_tokens"] for m in measured),
           "high_tokens": sum(m["high_tokens"] for m in measured),
           "count": len(measured)}

    out = {"files": measured, "totals": agg}

    if args.group_by and args.group_by.startswith("prefix:"):
        n = int(args.group_by.split(":", 1)[1])
        groups: dict[str, dict] = {}
        for m in measured:
            segs = m["path"].split("/")
            key = "/".join(segs[:n]) if n <= len(segs) else "/".join(segs[:-1])
            g = groups.setdefault(key, {"lines": 0, "bytes": 0, "mid_tokens": 0,
                                        "high_tokens": 0, "count": 0})
            g["lines"] += m["lines"]; g["bytes"] += m["bytes"]
            g["mid_tokens"] += m["mid_tokens"]; g["high_tokens"] += m["high_tokens"]
            g["count"] += 1
        out["groups"] = groups

    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    sys.stderr.write(f"measured {agg['count']} files; "
                     f"totals mid≈{agg['mid_tokens']} tokens "
                     f"(low {agg['low_tokens']} / high {agg['high_tokens']}); "
                     f"{agg['lines']} lines / {agg['bytes']} bytes\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
