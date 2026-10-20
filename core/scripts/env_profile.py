#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
env_profile — deterministic reader for the project environment profile
`<project>/.mgh/env-profile.json`. The profile is the machine-readable home for
project-level dispatch preferences (which fan-out dispatch form, native
concurrency, gateway quota); consumers read it through this ONE module so the
parse/validate semantics never diverge. Absent config = the established
defaults with ZERO behavior change for any existing command.

Usage:
  py env_profile.py --target <abs-project>          print the resolved profile
  py env_profile.py --target <abs-project> --check  same + fail-loud validation

Schema (all keys optional; unknown fields ignored):
  {"v": 1,
   "dispatch_mode": "auto|runner|native",
   "native_concurrency": <int 1..5>,
   "quota": {"calls": <int>0>, "window_s": <int>0>, "calls_per_unit": <int>0>}}

Semantics:
  missing file/dir  full defaults: dispatch_mode "auto" (resolves to the current
                    dispatch form — this is pinned; any refinement needs its own
                    spec change), native_concurrency 3, no quota.
  "auto"            the default resolution is the EXISTING dispatch form.
  "runner"/"native" explicit form selection (consumers wire these; this reader
                    only validates and resolves).
  quota             all three keys are REQUIRED when the quota object is present;
                    a half-configured quota is a config error, not "no quota".
  fail-closed       unparsable JSON / non-object / unknown or non-int v /
                    dispatch_mode outside the enum / native_concurrency outside
                    1..5 (non-int or bool included) / partial or non-positive
                    quota => CLI exit 2 + recipe (file path + violating field);
                    import form raises EnvProfileError (a ValueError subclass).
                    NEVER a silent fall-back to defaults — a "configured native
                    but actually ran runner" mismatch must blow up at startup.

Contract: stdout = one structured JSON line {target, config_path, exists,
profile{dispatch_mode, native_concurrency, quota}}; --check adds
{check: ok|failed, violations[]}. stderr = human diagnostics + recipes.
Exit codes: 0 ok (including "missing config = valid defaults") · 2 misuse
(bad/missing --target, config validation failure). Read-only: no mode of this
script ever writes a file. Zero runtime deps (Python >=3.10 stdlib).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

CONFIG_REL = Path(".mgh") / "env-profile.json"

DEFAULT_DISPATCH_MODE = "auto"
DEFAULT_NATIVE_CONCURRENCY = 3
DISPATCH_MODES = ("auto", "runner", "native")
CONCURRENCY_MIN = 1
CONCURRENCY_MAX = 5
_QUOTA_KEYS = ("calls", "window_s", "calls_per_unit")


def _eprint(*a):
    print(*a, file=sys.stderr)


class EnvProfileError(ValueError):
    """Raised by load() on any malformed/invalid profile (fail-closed; a
    ValueError subclass so generic exception handling stays natural)."""


class Profile:
    """Resolved profile values (pure data; as_dict() is the JSON face)."""

    __slots__ = ("dispatch_mode", "native_concurrency", "quota")

    def __init__(self, dispatch_mode: str = DEFAULT_DISPATCH_MODE,
                 native_concurrency: int = DEFAULT_NATIVE_CONCURRENCY,
                 quota: dict | None = None):
        self.dispatch_mode = dispatch_mode
        self.native_concurrency = native_concurrency
        self.quota = quota

    def as_dict(self) -> dict:
        return {"dispatch_mode": self.dispatch_mode,
                "native_concurrency": self.native_concurrency,
                "quota": self.quota}

    def __repr__(self):  # pragma: no cover — debugging convenience
        return f"Profile({self.as_dict()!r})"


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_body(body, path: Path) -> list[str]:
    """Schema/value validation shared by load() and --check. Returns the list of
    violations (empty = valid). `body` must already be a parsed JSON object."""
    v: list[str] = []
    if not isinstance(body, dict):
        return [f"config is not a JSON object ({type(body).__name__})"]
    ver = body.get("v", 1)
    if not _is_int(ver) or ver != 1:
        v.append(f"v must be the integer 1 (got {ver!r})")
    mode = body.get("dispatch_mode", DEFAULT_DISPATCH_MODE)
    if not isinstance(mode, str) or mode not in DISPATCH_MODES:
        v.append(f"dispatch_mode must be one of {'|'.join(DISPATCH_MODES)} "
                 f"(got {mode!r})")
    conc = body.get("native_concurrency", DEFAULT_NATIVE_CONCURRENCY)
    if not _is_int(conc) or not (CONCURRENCY_MIN <= conc <= CONCURRENCY_MAX):
        v.append(f"native_concurrency must be an integer "
                 f"{CONCURRENCY_MIN}..{CONCURRENCY_MAX} (got {conc!r})")
    quota = body.get("quota")
    if quota is not None:
        if not isinstance(quota, dict):
            v.append(f"quota must be an object with {', '.join(_QUOTA_KEYS)} "
                     f"(got {type(quota).__name__})")
        else:
            for k in _QUOTA_KEYS:
                qv = quota.get(k)
                if not _is_int(qv) or qv <= 0:
                    v.append(f"quota.{k} must be a positive integer (got "
                             f"{qv!r}; all three quota keys are required when "
                             f"quota is present)")
    return v


def _resolve(body: dict) -> Profile:
    quota = body.get("quota")
    # unknown keys inside quota are dropped (ignored, like top-level ones), so
    # the resolved value face is exactly the three-key shape
    clean = ({k: quota[k] for k in _QUOTA_KEYS if k in quota}
             if isinstance(quota, dict) else None)
    return Profile(dispatch_mode=body.get("dispatch_mode",
                                          DEFAULT_DISPATCH_MODE),
                   native_concurrency=body.get("native_concurrency",
                                               DEFAULT_NATIVE_CONCURRENCY),
                   quota=clean)


def load(target) -> Profile:
    """Import-form reader. Missing file/dir => defaults; anything malformed
    raises EnvProfileError (fail-closed, NEVER silent defaults)."""
    path = Path(target) / CONFIG_REL
    if not path.is_file():
        return Profile()
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EnvProfileError(f"{path}: unparsable config: {e}") from e
    violations = _validate_body(body, path)
    if violations:
        raise EnvProfileError(f"{path}: " + "; ".join(violations))
    return _resolve(body)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="read + validate the project environment profile "
                    "<project>/.mgh/env-profile.json (dispatch form / native "
                    "concurrency / quota; missing config = current-behavior "
                    "defaults, malformed config = fail-closed exit 2)")
    ap.add_argument("--target", metavar="<abs>",
                    help="absolute project root holding .mgh/env-profile.json")
    ap.add_argument("--check", action="store_true",
                    help="fail-loud validation: schema + value ranges "
                         "(dispatch_mode auto|runner|native, "
                         "native_concurrency integer 1..5, quota "
                         "{calls,window_s,calls_per_unit} all positive); "
                         "violations => exit 2 + recipe; read-only")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if not args.target:
        _eprint("error: --target <abs-project> is required")
        return 2
    target = Path(args.target)
    if not target.is_dir():
        _eprint(f"error: --target not a directory: {target}")
        return 2
    target = target.resolve()
    path = target / CONFIG_REL

    payload = {"target": str(target), "config_path": str(path),
               "exists": path.is_file(), "profile": Profile().as_dict()}
    code = 0
    if not path.is_file():
        _eprint(f"[env-profile] no config at {path} — defaults apply "
                f"(dispatch_mode auto = current dispatch form, "
                f"native_concurrency {DEFAULT_NATIVE_CONCURRENCY}, no quota)")
    else:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            body = None
            violations = [f"unparsable config: {e}"]
        else:
            violations = _validate_body(body, path)
        if violations:
            code = 2
            payload["profile"] = None
            if args.check:
                payload["check"] = "failed"
                payload["violations"] = violations
            _eprint(f"error: env-profile validation failed ({path}):")
            for v in violations:
                _eprint(f"  - {v}")
            _eprint("recipe: fix or delete the config — a malformed profile is "
                    "NEVER silently treated as defaults (a 'configured native "
                    "but actually ran runner' mismatch must fail at startup).")
        else:
            profile = _resolve(body)
            payload["profile"] = profile.as_dict()
            if args.check:
                payload["check"] = "ok"
                payload["violations"] = []
            _eprint(f"[env-profile] ok ({path}): dispatch_mode="
                    f"{profile.dispatch_mode} native_concurrency="
                    f"{profile.native_concurrency} "
                    f"quota={profile.quota if profile.quota else 'none'}")
    if args.check and code == 0:
        payload["check"] = "ok"
        payload["violations"] = []
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
