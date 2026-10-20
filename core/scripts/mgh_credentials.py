#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
mgh_credentials — credential center: one-shot model-gateway credential
acquisition for every mgh-* fanout flow (command-agnostic).

WHY: in single-sign-on gateway environments (browser login, one-time tickets,
local callback ports) a fan-out of N host-CLI children CANNOT each run its own
login flow — tickets are single-use and the children fight over the callback
port, so all but the first converge to a silent stall. The fix shape: acquire
the token ONCE here, hand it to `fanout_runner.py --cred-file` and let the
dispatcher inject a static provider entry (baseURL + apikey) into each child's
own config — children never authenticate themselves.

Contract split (dev-facing): this script is GENERIC. Every enterprise-specific
value (env var name, env-file path, global host-CLI config path, model id,
provider id, gateway baseURL, expiry signatures) lives in the PARAMETER FILE
(`--source`, written by the orchestrator into the run dir; values come from the
special-auth deployment doc when present) — never hard-coded here. `~` prefixes
are expanded by this script so orchestrator command lines never carry home-dir
literals (the runtime guard's Bash path net would intercept them).

CLI contract (`--help` is the contract surface, R5.1):
  py mgh_credentials.py --source <run>/cred_source.json --out <run>/cred.json
                        [--login-timeout-s <s>]
  py mgh_credentials.py --check <run>/cred.json

  --source           parameter file (JSON, closed schema below)
  --out              output secret payload (closed schema below); written with
                     best-effort restrictive permissions (POSIX 0600)
  --login-timeout-s  login-process mode cap (default 300)
  --check            validate an existing cred file's schema (zero network;
                     token VALIDITY is never judged here — the dispatcher's
                     credential-expired classification is the runtime check)

cred_source.json (closed set; unknown keys ignored for forward compat):
  v                    1
  mode                 "inherit" | "env-file" | "login-process"
  token_env            env var name carrying the token (all modes)
  env_file             KEY=VALUE file path (env-file mode)
  global_config        host-CLI global config path (login-process mode; also
                       the passthrough value recorded in cred.json)
  model                "<provider>/<model>" for the one-shot login child
                       (login-process mode)
  provider_id          provider id in the global config to override
                       (passthrough)
  baseURL              gateway OpenAI-compatible entry (passthrough)
  keep_plugins         keep the config's plugin list on injection (default true)
  expired_signatures   token-expiry substrings for the dispatcher's classifier
                       (default [])
  login_timeout_s      per-attempt login cap (default 300; --login-timeout-s
                       overrides)

Modes (acquisition, most- to least-passive):
  inherit        read token from THIS process's env (a host session that
                 already logged in has it injected; zero login, zero spawn)
  env-file       parse KEY=VALUE lines from the env file (desktop-side plugin
                 written credential file)
  login-process  materialize a GENERIC probe plugin (top-level poll: writes
                 process.env[token_env] to the probe output path once the
                 login plugin populates it), surgically append it to the
                 global config's plugin list, spawn ONE one-shot login child
                 (`opencode run --print-logs --model <model> "Reply OK"`),
                 poll for the token, then RESTORE the global config in a
                 finally block (re-read + remove ONLY the appended entry —
                 never a blind full-file rewrite over a concurrent edit).
                 VERIFY POINT (first enterprise run): the probe's trigger
                 shape (module top-level poll) — adjust the template to the
                 observed plugin-load hook if the poll never fires; the
                 contract (write token file, restore config) does not change.

stdout: structured JSON summary {action, mode, token_env, ok, out, detail} —
NEVER the token value. stderr: progress/diagnostics.
Exit codes (R5.3b): 0 ok · 1 generic failure · 2 misuse / acquire failure
(with an actionable recipe).

Zero runtime deps (Python >=3.10 stdlib).
"""
from __future__ import annotations
import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_LOGIN_TIMEOUT_S = 300
_LOGIN_POLL_INTERVAL_S = 0.5

# The cred payload's closed schema — SINGLE SOURCE shared with the dispatcher
# (fanout_runner.py imports validate_cred_payload from here; one validator so
# the producer and the consumer can never drift apart on what "valid" means).
CRED_REQUIRED_KEYS = ("v", "baseURL", "apikey", "provider_id",
                      "global_config", "keep_plugins", "expired_signatures")

# Generic probe plugin template (no enterprise vocabulary): materialized by
# the login-process mode with {token_env} and {out_path} substituted. The
# poll runs at module top level so it survives whatever hook surface the
# host's plugin loader exposes; it exits the login child the moment the token
# lands (the child has no other purpose once the token is captured).
_PROBE_TEMPLATE = """\
// mgh credential probe plugin (generic, materialized by mgh_credentials.py).
// Polls process.env[<token_env>] and writes the token to <out_path> once the
// login plugin populates it, then exits the process. No enterprise vocabulary.
import("node:fs/promises").then((fs) => {
  const timer = setInterval(() => {
    const t = process.env[<token_env_js>];
    if (t) {
      fs.writeFile(<out_path_js>, String(t)).then(() => {
        clearInterval(timer);
        process.exit(0);
      }).catch(() => {});
    }
  }, 500);
});
export {};
"""


def _eprint(*a):
    print(*a, file=sys.stderr)


def validate_cred_payload(body) -> list:
    """Return a list of schema problems (empty = valid). Closed-set shape
    shared by the producer (this script) and the consumer (fanout_runner)."""
    if not isinstance(body, dict):
        return ["cred payload is not a JSON object"]
    problems = []
    for k in CRED_REQUIRED_KEYS:
        if k not in body:
            problems.append(f"missing required key: {k}")
    if problems:
        return problems
    if body["v"] != 1:
        problems.append(f"v must be 1 (got {body['v']!r})")
    for k in ("baseURL", "apikey", "provider_id", "global_config"):
        v = body[k]
        if not isinstance(v, str) or not v.strip():
            problems.append(f"{k} must be a non-empty string")
    if not isinstance(body["keep_plugins"], bool):
        problems.append("keep_plugins must be a boolean")
    es = body["expired_signatures"]
    if not isinstance(es, list) or not all(isinstance(s, str) for s in es):
        problems.append("expired_signatures must be a list of strings")
    return problems


def _write_cred(out_path: Path, payload: dict) -> None:
    """Write the secret payload with best-effort restrictive permissions.
    POSIX: 0600 via open()+fchmod; Windows: best-effort user-only via
    os.chmod (NTFS ACL refinement is out of scope for a stdlib script)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        try:
            os.chmod(str(out_path), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        raise


def _read_source(path: Path) -> dict:
    """Parse + validate the parameter file (closed-set core fields)."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"cred source unreadable: {path} ({e})")
    if not isinstance(body, dict):
        raise ValueError("cred source is not a JSON object")
    if body.get("v") != 1:
        raise ValueError(f"cred source v must be 1 (got {body.get('v')!r})")
    mode = body.get("mode")
    if mode not in ("inherit", "env-file", "login-process"):
        raise ValueError(f"mode must be inherit|env-file|login-process "
                         f"(got {mode!r})")
    if not isinstance(body.get("token_env"), str) or not body["token_env"]:
        raise ValueError("token_env must be a non-empty string")
    return body


def _expand(raw) -> str:
    return os.path.expanduser(str(raw))


def _parse_env_file(path: Path, var: str) -> str:
    """Minimal KEY=VALUE parser (utf-8; `export KEY=VALUE` tolerated; double
    or single quotes stripped; `#` comments skipped)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError(f"env file unreadable: {path} ({e})")
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        if s.startswith("export "):
            s = s[len("export "):]
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if k == var:
            return v
    raise ValueError(f"env file has no {var!r} entry: {path}")


_PROBE_NAME = "mgh_cred_probe.js"


def _surgical_restore(gp: Path, entry: str, original_bytes: bytes) -> None:
    """Remove ONLY the plugin entry this script appended, from the CURRENT
    file state (a concurrent edit between append and restore must survive).
    Fallback chain: re-read+edit → write original bytes → stderr warning."""
    try:
        cur = json.loads(gp.read_text(encoding="utf-8"))
        plugins = cur.get("plugin")
        if isinstance(plugins, list) and entry in plugins:
            plugins.remove(entry)
            if not plugins:
                cur["plugin"] = []
            gp.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
            return
        # entry already gone (login child cleaned up?) → nothing to do
        if isinstance(plugins, list):
            return
    except (OSError, ValueError) as e:
        _eprint(f"warn: surgical restore re-read failed ({e}); restoring the "
                f"pre-run bytes")
    try:
        gp.write_bytes(original_bytes)
    except OSError as e:
        _eprint(f"warn: could not restore {gp}: {e} — remove the probe entry "
                f"({_PROBE_NAME}) from its plugin list manually")


def _acquire_login_process(src: dict, out_path: Path,
                           login_timeout_s: int) -> str:
    """One-shot login child + probe plugin capture; returns the token.
    Raises ValueError with an actionable message on any failure. The global
    config restoration happens in a finally block — timeout and failure
    restore exactly like success."""
    gp = Path(_expand(src.get("global_config") or ""))
    if not str(src.get("global_config") or "").strip():
        raise ValueError("mode login-process requires global_config in the "
                         "cred source")
    if not gp.is_file():
        raise ValueError(f"global config not found: {gp}")
    model = src.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("mode login-process requires model in the cred source "
                         "(the login child needs a valid <provider>/<model>)")
    run_dir = out_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)
    probe_path = run_dir / _PROBE_NAME
    token_out = run_dir / "cred_probe_token.txt"
    token_out.unlink(missing_ok=True)
    probe_body = (_PROBE_TEMPLATE
                  .replace("<token_env>", src["token_env"])
                  .replace("<token_env_js>", json.dumps(src["token_env"]))
                  .replace("<out_path>", str(token_out))
                  .replace("<out_path_js>", json.dumps(str(token_out))))
    probe_path.write_text(probe_body, encoding="utf-8")
    original_bytes = gp.read_bytes()
    entry = str(probe_path.resolve())
    child = None
    try:
        # Surgical append: re-read at append time too (never blind).
        try:
            cfg = json.loads(gp.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(f"global config unparsable: {gp} ({e})")
        plugins = cfg.setdefault("plugin", [])
        if not isinstance(plugins, list):
            raise ValueError(f"global config plugin field is not a list: {gp}")
        if entry not in plugins:
            plugins.append(entry)
        gp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")

        _eprint(f"[mgh_credentials] login child starting — a browser window "
                f"is EXPECTED (complete the SSO login / captcha there); "
                f"timeout {login_timeout_s}s")
        log_path = run_dir / "login_process.log"
        cmd = [_host_exe(), "run", "--print-logs", "--model", model, "Reply OK"]
        with open(log_path, "w", encoding="utf-8") as logf:
            child = subprocess.Popen(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                cwd=str(run_dir),
                stdin=subprocess.DEVNULL)
            t0 = time.monotonic()
            while time.monotonic() - t0 < login_timeout_s:
                if child.poll() is not None and token_out.is_file():
                    break
                if token_out.is_file():
                    break
                time.sleep(_LOGIN_POLL_INTERVAL_S)
            if not token_out.is_file():
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                raise ValueError(
                    f"login child produced no token within {login_timeout_s}s "
                    f"(evidence: {log_path}) — recipe: complete the browser "
                    f"SSO login (captcha included), check the login automation "
                    f"plugin is installed and no other process holds the "
                    f"local callback port; retry, or use a more passive mode "
                    f"from a session that is already logged in")
        token = token_out.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError(f"probe wrote an empty token ({token_out}) — "
                             f"check the probe trigger against the observed "
                             f"plugin-load hook (verify point)")
        return token
    finally:
        _surgical_restore(gp, entry, original_bytes)
        try:
            token_out.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            probe_path.unlink(missing_ok=True)
        except OSError:
            pass
        if child is not None and child.poll() is None:
            try:
                child.kill()
            except OSError:
                pass


def _host_exe() -> str:
    """Resolve the host CLI executable (npm `.cmd` shims on Windows need the
    resolved absolute path for Popen without shell)."""
    import shutil
    return shutil.which("opencode") or "opencode"


def _acquire(src_path: Path, out_path: Path, login_timeout_s: int) -> dict:
    """Run the source-declared mode; write the cred payload; return the
    stdout summary (never the token)."""
    src = _read_source(src_path)
    mode = src["mode"]
    var = src["token_env"]
    detail = ""
    if mode == "inherit":
        token = os.environ.get(var)
        detail = "read from this process's environment"
        if not token:
            raise ValueError(
                f"env var {var!r} not set in this process — recipe: run from "
                f"a host session that has completed the login, or use the "
                f"env-file / login-process mode per the special-auth doc")
    elif mode == "env-file":
        ef = src.get("env_file")
        if not isinstance(ef, str) or not ef.strip():
            raise ValueError("mode env-file requires env_file in the cred "
                             "source")
        token = _parse_env_file(Path(_expand(ef)), var)
        detail = f"parsed from {ef}"
    else:
        token = _acquire_login_process(src, out_path, login_timeout_s)
        detail = f"captured via one-shot login child (timeout {login_timeout_s}s)"
    payload = {
        "v": 1,
        "baseURL": src.get("baseURL"),
        "apikey": token,
        "provider_id": src.get("provider_id"),
        "global_config": _expand(src.get("global_config")
                                 or "~/nonexistent"),
        "keep_plugins": bool(src.get("keep_plugins", True)),
        "expired_signatures": list(src.get("expired_signatures") or []),
    }
    problems = validate_cred_payload(payload)
    if problems:
        raise ValueError("acquired payload invalid: " + "; ".join(problems) +
                         " — check provider_id/baseURL in the cred source")
    _write_cred(out_path, payload)
    return {"action": "acquire", "mode": mode, "token_env": var, "ok": True,
            "out": str(out_path), "detail": detail}


def _check(path: Path) -> dict:
    """Schema-only validation (zero network, no token validity judgement)."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"action": "check", "ok": False, "file": str(path),
                "problems": [f"unreadable or unparsable: {e}"]}
    problems = validate_cred_payload(body)
    return {"action": "check", "ok": not problems, "file": str(path),
            "problems": problems,
            "detail": ("schema complete; token validity is judged at "
                       "dispatch time by the credential-expired classifier"
                       if not problems else "")}


def main():
    ap = argparse.ArgumentParser(
        description="credential center: one-shot gateway credential "
                    "acquisition for mgh-* fanout flows (generic; enterprise "
                    "values live in the --source parameter file)")
    ap.add_argument("--source", metavar="<run>/cred_source.json",
                    help="parameter file (JSON) written by the orchestrator; "
                         "carries mode + every enterprise-specific value")
    ap.add_argument("--out", metavar="<run>/cred.json",
                    help="output secret payload for fanout_runner --cred-file")
    ap.add_argument("--login-timeout-s", type=int,
                    default=DEFAULT_LOGIN_TIMEOUT_S,
                    help=f"login-process mode cap in seconds "
                         f"(default {DEFAULT_LOGIN_TIMEOUT_S})")
    ap.add_argument("--check", metavar="<run>/cred.json",
                    help="validate an existing cred file's schema and exit "
                         "(zero network)")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.check:
        if args.source or args.out:
            _eprint("error: --check takes only the cred file path — never "
                    "combine it with --source/--out")
            return 2
        summary = _check(Path(args.check).expanduser())
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["ok"] else 1

    if not args.source or not args.out:
        _eprint("error: acquire requires --source <cred_source.json> and "
                "--out <cred.json> (or use --check <cred.json>)")
        _eprint("recipe: py mgh_credentials.py --source <run>/cred_source.json "
                "--out <run>/cred.json")
        return 2
    if args.login_timeout_s < 1:
        _eprint("error: --login-timeout-s must be >= 1")
        return 2
    try:
        summary = _acquire(Path(args.source).expanduser(),
                           Path(args.out).expanduser(),
                           args.login_timeout_s)
    except ValueError as e:
        _eprint(f"error: {e}")
        _eprint(f"[mgh_credentials] no cred file written: {args.out}")
        print(json.dumps({"action": "acquire", "ok": False,
                          "out": str(args.out),
                          "detail": str(e)[:200]}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
