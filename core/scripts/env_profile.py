#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
env_profile — deterministic reader + resolver for the project environment profile
`<project>/.mgh/env-profile.json`. The profile is the machine-readable home for
project-level dispatch preferences (which fan-out dispatch form, native
concurrency, gateway quota); consumers read it through this ONE module so the
parse/validate/resolve semantics never diverge.

Usage:
  py env_profile.py --target <abs-project> [--consumer sdr|init|generic]
  py env_profile.py --target <abs-project> --consumer sdr --check

Schema (all keys optional; unknown fields ignored):
  {"v": 1,
   "dispatch_mode": "auto|runner|native",
   "native_concurrency": <int 1..5>,
   "quota": {"calls": <int>0, "window_s": <int>0, "calls_per_unit": <int>0>}}

Semantics:
  missing file/dir  full defaults: dispatch_mode "auto" (resolved by the rules
                    below), native_concurrency 3, no quota.
  "auto"            resolve from host face + consumer (below).
  "runner"/"native" explicit form selection; ALWAYS wins over the default rules.
  host face         where these scripts are INSTALLED: a path segment `.opencode`
                    => "opencode", `.claude` => "claude", anything else (dsh
                    `mgh-core/`, a dev tree, a custom copy) => "other". Callers
                    may pass an explicit host face (the launcher derives it from
                    its --host / PATH detection and overrides the path probe).
  consumer          the calling command surface, passed explicitly by callers:
                    `/mgh-sdr` = "sdr", `/mgh-init` = "init"; anything else
                    (default) = "generic".
  default form      consumer ∈ {sdr, init} AND host_face == "opencode" =>
                    "native" (the opencode-face default for both consumers);
                    every other consumer/face combination => "runner"
                    (the pre-existing behavior, byte-identical for the
                    claude/dsh faces and the generic consumer).
  quota             all three keys are REQUIRED when the quota object is present;
                    a half-configured quota is a config error, not "no quota".
  fail-closed       unparsable JSON / non-object / unknown or non-int v /
                    dispatch_mode outside the enum / native_concurrency outside
                    1..5 (non-int or bool included) / partial or non-positive
                    quota => CLI exit 2 + recipe (file path + violating field);
                    import form raises EnvProfileError (a ValueError subclass).
                    NEVER a silent fall-back to defaults — a "configured native
                    but actually ran runner" mismatch must blow up at startup.

Native asset gate: `require_native_assets()` is the ONE presence check for the
installed opencode native assets, parameterized by SURFACE (which command's
native form is activating): `surface="sdr"` checks the `sdr-review-native`
agent beside the mgh-core tree + the sdr wave-discipline fragment inside it;
`surface="init"` checks the `init-scout-native` agent + the init scout
wave-discipline fragment. The orchestration surfaces call it when the resolved
form is native on the opencode face; a missing asset is a fail-loud recipe
(reinstall or explicit runner), NEVER a silent fall-back to the subprocess form.

Contract: stdout = one structured JSON line {target, config_path, exists,
profile{dispatch_mode, native_concurrency, quota}, host_face, consumer, form,
source}; --check adds {check: ok|failed, violations[]}. `source` is "profile"
when dispatch_mode is an explicit runner/native value and "host-default" when
the form came from the host/consumer default rules. stderr = human diagnostics
+ recipes. Exit codes: 0 ok (including "missing config = valid defaults") ·
2 misuse (bad/missing --target, bad --consumer, config validation failure).
Read-only: no mode of this script ever writes a file. Zero runtime deps
(Python >=3.10 stdlib).
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

# Dispatch-form resolution dimensions (see the module docstring).
HOST_FACES = ("opencode", "claude", "other")
DEFAULT_HOST_FACE = "other"
CONSUMERS = ("sdr", "init", "generic")
DEFAULT_CONSUMER = "generic"
# Consumers whose opencode-face default resolves native (the user-approved
# native-dispatch rollout: /mgh-sdr first, /mgh-init second — scout layer in
# this change, aggregate layers inherit via the same default).
NATIVE_DEFAULT_CONSUMERS = ("sdr", "init")
FORMS = ("native", "runner")
DEFAULT_FORM = "runner"
SOURCE_PROFILE = "profile"
SOURCE_HOST_DEFAULT = "host-default"

# Installed native assets per surface (opencode face): each surface's agent
# lives in the host's `agent/` dir beside mgh-core; its wave-discipline
# fragment lives inside mgh-core. The gate is parameterized by surface so each
# command checks ITS OWN assets through the ONE shared helper (a scout run
# checking the sdr assets would both miss scout gaps and false-block on sdr).
NATIVE_AGENT = "sdr-review-native"
NATIVE_AGENT_REL = Path("agent") / f"{NATIVE_AGENT}.md"
NATIVE_FRAGMENT_REL = Path("prompts") / "fragments" / "sdr-native-dispatch.md"
INIT_NATIVE_AGENT = "init-scout-native"
INIT_NATIVE_AGENT_REL = Path("agent") / f"{INIT_NATIVE_AGENT}.md"
INIT_NATIVE_FRAGMENT_REL = (Path("prompts") / "fragments"
                            / "init-scout-native-dispatch.md")
NATIVE_SURFACES = {
    "sdr": (NATIVE_AGENT_REL, NATIVE_FRAGMENT_REL),
    "init": (INIT_NATIVE_AGENT_REL, INIT_NATIVE_FRAGMENT_REL),
}
DEFAULT_SURFACE = "sdr"


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


class Resolution:
    """A profile plus the resolved dispatch form (host face × consumer). Pure
    data; `as_dict()` is the CLI/consumer JSON face."""

    __slots__ = ("profile", "host_face", "consumer", "form", "source",
                 "profile_exists")

    def __init__(self, profile: Profile, host_face: str, consumer: str, form: str,
                 source: str, profile_exists: bool):
        self.profile = profile
        self.host_face = host_face
        self.consumer = consumer
        self.form = form
        self.source = source
        self.profile_exists = profile_exists

    def as_dict(self) -> dict:
        return {"host_face": self.host_face, "consumer": self.consumer,
                "form": self.form, "source": self.source,
                "profile_exists": self.profile_exists,
                "profile": self.profile.as_dict()}

    def __repr__(self):  # pragma: no cover — debugging convenience
        return f"Resolution({self.as_dict()!r})"


def detect_host_face(script_path=None, explicit: str | None = None) -> str:
    """Host install face: an explicit value wins (`--host`/PATH detection in the
    launcher); otherwise the path segments of this module's install location
    decide — `.opencode` => opencode, `.claude` => claude, anything else (dsh
    `mgh-core/`, dev tree, custom copy) => other. Deterministic, never guesses
    from the target project's contents (a multi-face install is judged by the
    copy that is actually running)."""
    if explicit is not None:
        if explicit not in HOST_FACES:
            raise ValueError(f"host_face must be one of {'|'.join(HOST_FACES)} "
                             f"(got {explicit!r})")
        return explicit
    path = Path(script_path if script_path is not None else __file__).resolve()
    segments = {seg.lower() for seg in path.parts}
    if ".opencode" in segments:
        return "opencode"
    if ".claude" in segments:
        return "claude"
    return "other"


def resolve_form(profile: Profile, host_face: str = DEFAULT_HOST_FACE,
                 consumer: str = DEFAULT_CONSUMER) -> str:
    """Resolved dispatch form. Explicit runner/native ALWAYS wins; the default
    rules make the native-default consumers (sdr, init) native on the opencode
    face. Every other consumer/face combination keeps the established
    subprocess form."""
    if host_face not in HOST_FACES:
        raise ValueError(f"host_face must be one of {'|'.join(HOST_FACES)} "
                         f"(got {host_face!r})")
    if consumer not in CONSUMERS:
        raise ValueError(f"consumer must be one of {'|'.join(CONSUMERS)} "
                         f"(got {consumer!r})")
    if profile.dispatch_mode in ("native", "runner"):
        return profile.dispatch_mode
    if consumer in NATIVE_DEFAULT_CONSUMERS and host_face == "opencode":
        return "native"
    return DEFAULT_FORM


def resolve(target, consumer: str = DEFAULT_CONSUMER,
            host_face: str | None = None, script_path=None) -> Resolution:
    """Load + validate + resolve in ONE call (the consumers' single entry). A
    malformed profile raises EnvProfileError exactly like load()."""
    profile = load(target)
    face = detect_host_face(script_path=script_path, explicit=host_face)
    form = resolve_form(profile, face, consumer)
    source = (SOURCE_PROFILE if profile.dispatch_mode in ("native", "runner")
              else SOURCE_HOST_DEFAULT)
    return Resolution(profile=profile, host_face=face, consumer=consumer,
                      form=form, source=source,
                      profile_exists=(Path(target) / CONFIG_REL).is_file())


def missing_native_assets(mgh_core_root, surface: str = DEFAULT_SURFACE) -> list[str]:
    """Absolute paths of the native-dispatch assets absent from this install
    tree for the given surface (`sdr` = the `sdr-review-native` agent + its
    wave-discipline fragment; `init` = the `init-scout-native` agent + its
    fragment). The agent lives in the host `agent/` dir (sibling of mgh-core),
    the fragment inside mgh-core. Empty list = complete. Presence only — never
    parses their content."""
    agent_rel, fragment_rel = NATIVE_SURFACES[surface]
    root = Path(mgh_core_root).resolve()
    candidates = (root.parent / agent_rel, root / fragment_rel)
    return [str(p) for p in candidates if not p.is_file()]


def require_native_assets(mgh_core_root,
                          surface: str = DEFAULT_SURFACE) -> str | None:
    """The single fail-loud gate shared by every native orchestration surface
    (`surface` picks which command's assets are checked; default `sdr` keeps
    the pre-parameterization behavior byte-identical). Returns None when the
    assets are present, else one recipe string (printed to stderr by the
    caller, which then exits 2). NEVER a silent fall-back to the subprocess
    form — a version-skewed install must be visible."""
    missing = missing_native_assets(mgh_core_root, surface)
    if not missing:
        return None
    return (
        "error: native dispatch is active on the opencode face but the install "
        "tree is missing: " + "; ".join(missing) + "\n"
        "recipe: re-run `install.sh --opencode <target>` to restore the native "
        "agent and the wave-discipline fragment for this surface; or set "
        '{"dispatch_mode":"runner"} in <target>/.mgh/env-profile.json to use the '
        "subprocess fallback explicitly. NEVER silently falls back — a partial "
        "install would otherwise look like a normal run.")


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
        description="read + validate + resolve the project environment profile "
                    "<project>/.mgh/env-profile.json (dispatch form / native "
                    "concurrency / quota; missing config = host/consumer "
                    "defaults, malformed config = fail-closed exit 2). Default "
                    "form resolution: consumer=sdr or init on the opencode "
                    "install face => native; every other consumer/face => "
                    "runner.")
    ap.add_argument("--target", metavar="<abs>",
                    help="absolute project root holding .mgh/env-profile.json")
    ap.add_argument("--consumer", choices=CONSUMERS, default=DEFAULT_CONSUMER,
                    help="calling command surface: sdr (/mgh-sdr) or init "
                         "(/mgh-init) may resolve native on the opencode face; "
                         "generic (default; everything else, stays runner)")
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

    host_face = detect_host_face()
    payload = {"target": str(target), "config_path": str(path),
               "exists": path.is_file(),
               "profile": Profile().as_dict(),
               "host_face": host_face, "consumer": args.consumer,
               "form": resolve_form(Profile(), host_face, args.consumer),
               "source": SOURCE_HOST_DEFAULT}
    code = 0
    if not path.is_file():
        _eprint(f"[env-profile] no config at {path} — defaults apply "
                f"(dispatch_mode auto; native_concurrency "
                f"{DEFAULT_NATIVE_CONCURRENCY}; no quota); resolved form="
                f"{payload['form']} for consumer={args.consumer} on the "
                f"{host_face} face")
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
            payload["form"] = None
            payload["source"] = None
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
            payload["form"] = resolve_form(profile, host_face, args.consumer)
            payload["source"] = (SOURCE_PROFILE
                                 if profile.dispatch_mode in ("native", "runner")
                                 else SOURCE_HOST_DEFAULT)
            if args.check:
                payload["check"] = "ok"
                payload["violations"] = []
            _eprint(f"[env-profile] ok ({path}): dispatch_mode="
                    f"{profile.dispatch_mode} native_concurrency="
                    f"{profile.native_concurrency} "
                    f"quota={profile.quota if profile.quota else 'none'}; "
                    f"resolved form={payload['form']} "
                    f"(consumer={args.consumer}, host_face={host_face}, "
                    f"source={payload['source']})")
    if args.check and code == 0:
        payload["check"] = "ok"
        payload["violations"] = []
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
