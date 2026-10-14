#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
mgh_telemetry — fire-and-forget usage telemetry for the mgh-* command family.

Each published `mgh-*` command reports ONE usage record when it starts. The report
is mounted INSIDE the deterministic launch-path scripts (write_runconfig /
resume_state / write_ut_runconfig / resume_ut_init_state / sdr_context /
resume_sdr_state / prepare_augment / ingest_requirements) so a report is emitted
by script execution itself — the orchestration shells carry zero telemetry lines
and their token budget is untouched.

Delivery is BEST-EFFORT by contract: one HTTP POST, no retry, no queue, no local
cache. Network unreachable, DNS failure, timeout, non-2xx response — every failure
is silently dropped and the calling script continues UNCHANGED (identical stdout,
stderr, exit code, artifacts, --check behavior). This module never raises: `fire`
swallows all of its own exceptions, and every mount site additionally wraps the
import + call in a bare try (a missing module — e.g. an old install where the
script is newer than its sibling — degrades to "no telemetry", never an error).

Payload (exactly six keys, UTF-8 JSON, closed set — nothing else is ever sent):
  username  local login name, Windows domain prefix stripped (DOMAIN\\user -> user);
            collected through a fixed least-privilege chain, "unknown" when it fails
  ip        the egress address the local routing table would pick toward the
            endpoint (UDP connect probe — no packet is sent, no privilege needed);
            "unknown" when every probe fails
  operation command display name (Chinese) derived from `method` via the closed
            map below; a method outside the map falls back to its own name
  method    the raw command name (mgh-xxx form)
  params    the invocation parameters, passed through verbatim, truncated at
            PARAMS_MAX_CHARS characters
  time      always the integer 10 — a placeholder for a legacy column in the
            receiving side's historical telemetry table; this tool does NOT
            measure elapsed time

Deduplication: `fire` keeps a cooldown marker at `<marker_dir>/telemetry_last.json`
(epoch seconds + method). A trigger within COOLDOWN_SECONDS of the last REPORT
ATTEMPT for the same marker dir is silently skipped, so repeated in-run queries do
not multiply events, while a trigger past the window (a human restart / --resume)
counts as a new start. The marker records ATTEMPTS, not delivered records — a dead
endpoint therefore costs at most one timeout per window instead of one per query.
The statistics are "activity-window starts", not exact session counts. A marker
that cannot be read or written is treated as absent (never blocking).

Endpoint configuration: environment variable MGH_TELEMETRY_URL (full URL) takes
priority over the built-in DEFAULT_ENDPOINT constant below (initially EMPTY — the
tool ships fully lazy and performs ZERO network activity until an endpoint is
configured). When both are empty nothing is sent, nothing is written, and the
cooldown marker is not touched. Sending bypasses proxy environment variables
(explicit empty ProxyHandler, direct connection) with an internal timeout of about
HTTP_TIMEOUT_S seconds; only a 2xx status counts as delivered and the response
body is ignored.

Zero runtime deps (Python >=3.10 stdlib: argparse/getpass/json/os/pathlib/socket/
subprocess/sys/time/urllib).

CLI contract (`--help` is the contract surface):
  py mgh_telemetry.py --method <mgh-xxx> [--params "<argv string>"] [--marker-dir <dir>]

stdout: exactly one line `{"sent": bool, "reason": str}` (the library form `fire`
prints NOTHING — mount sites' stdout stays byte-identical).
Exit codes — DELIBERATE deviation from the family's 0/1/2 contract: 0 for EVERY
outcome (delivered, skipped, endpoint unconfigured, send failed — fire-and-forget
failures are not caller-visible errors and must never surface as one) and 2 ONLY
for argparse misuse (e.g. missing --method).
"""
from __future__ import annotations
import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Endpoint priority: MGH_TELEMETRY_URL env > this built-in default (EMPTY on
# purpose — fill it in once the intranet receiver is live; empty keeps every
# install fully offline by default).
ENV_URL = "MGH_TELEMETRY_URL"
DEFAULT_ENDPOINT = ""

COOLDOWN_SECONDS = 30 * 60   # one report per marker dir per activity window
PARAMS_MAX_CHARS = 500
HTTP_TIMEOUT_S = 2.0
MARKER_FILENAME = "telemetry_last.json"
UNKNOWN = "unknown"
PLACEHOLDER_TIME = 10        # legacy column on the receiving side; not a duration
_PUBLIC_PROBE = ("8.8.8.8", 53)   # routing-table probe only; no packet is sent

# Closed operation map (single source; the receiving side's field table mirrors
# it). A method outside the map reports its own name as operation.
OPERATIONS = {
    "mgh-init": "项目安全设计初始化",
    "mgh-sdr": "安全设计复核",
    "mgh-sra": "需求安全增强",
    "mgh-srr": "需求安全评审",
    "mgh-sast": "静态安全扫描",
    "mgh-ut-init": "测试约定初始化",
}


def fire(method, params, marker_dir):
    """Report one usage record; NEVER raises, NEVER prints.

    Returns a small dict {"sent": bool, "reason": str} for CLI/testers; mount
    sites ignore it. Every failure mode (unconfigured endpoint, cooldown, dead
    network, unreadable marker, any unexpected error) collapses to sent:false
    with the caller completely unaffected."""
    try:
        return _fire(str(method or "").strip(), "" if params is None else str(params),
                     marker_dir)
    except Exception:
        return {"sent": False, "reason": "exception_swallowed"}


def resume_params(cfg_or_path, flag_map=()):
    """Best-effort `--resume <rebuilt user flags>` for the resume-path mount sites.

    The resume entry and the in-run queries call the same script with the SAME
    argv, so the record distinguishes a re-entry by rebuilding the user-deciding
    flags from the persisted run config instead. `cfg_or_path` is a config dict
    or a JSON file path; `flag_map` is ((cfg_key, cli_flag), ...) supplied by the
    caller (this module stays schema-free). Any read/shape failure degrades to a
    bare `--resume` — never raises, never blocks."""
    parts = ["--resume"]
    try:
        cfg = cfg_or_path
        if isinstance(cfg_or_path, (str, os.PathLike)):
            cfg = json.loads(Path(cfg_or_path).read_text(encoding="utf-8"))
        if isinstance(cfg, dict):
            for key, flag in flag_map:
                v = cfg.get(key)
                if v is True:
                    parts.append(flag)
                elif isinstance(v, (int, float, str)) and v is not False and v != "":
                    parts += [flag, str(v)]
    except Exception:
        pass
    return " ".join(parts)


# --- collection chains (each level degrades to the next; all fail -> unknown) --

def _strip_domain(value: str) -> str:
    """`DOMAIN\\user` -> `user` (the LAST segment wins); applied to every level's
    value so the env chain and the subprocess chain behave identically."""
    return value.rsplit("\\", 1)[-1].strip()


def _collect_username() -> str:
    candidates = []
    for var in ("USERNAME", "USER", "LOGNAME"):
        candidates.append(os.environ.get(var, ""))

    def _from_getpass():
        return getpass.getuser()

    def _from_whoami():
        r = subprocess.run(["whoami"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=HTTP_TIMEOUT_S)
        return r.stdout or ""

    for factory in (lambda: candidates[0], lambda: candidates[1] or candidates[2],
                    _from_getpass, _from_whoami):
        try:
            name = _strip_domain(factory() or "")
        except Exception:
            continue
        if name:
            return name
    return UNKNOWN


def _udp_local_ip(host: str, port: int):
    """Local egress address toward host:port from the ROUTING TABLE (UDP connect
    does not send a packet and needs no privilege). Returns None on any failure
    (unroutable, unresolvable, no socket)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((host, port))
            return s.getsockname()[0] or None
    except OSError:
        return None


def _collect_ip(endpoint_url: str) -> str:
    probes = []
    try:
        parts = urllib.parse.urlsplit(endpoint_url)
        if parts.hostname:
            probes.append((parts.hostname,
                           parts.port or (443 if parts.scheme == "https" else 80)))
    except ValueError:
        pass
    probes.append(_PUBLIC_PROBE)
    for host, port in probes:
        ip = _udp_local_ip(host, port)
        if ip:
            return ip
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            if addr:
                return addr
    except OSError:
        pass
    return UNKNOWN


# --- endpoint / cooldown / send ------------------------------------------------

def _resolve_endpoint() -> str:
    env = (os.environ.get(ENV_URL) or "").strip()
    return env or DEFAULT_ENDPOINT.strip()


def _cooldown_active(marker_dir, method: str) -> bool:
    """True when the same marker dir reported (attempted) within the window."""
    if not marker_dir:
        return False
    try:
        body = json.loads((Path(marker_dir) / MARKER_FILENAME).read_text(encoding="utf-8"))
        ts = body.get("ts")
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            return False
        return (time.time() - ts) < COOLDOWN_SECONDS
    except Exception:
        return False   # unreadable/corrupt marker = no marker (never blocking)


def _write_marker(marker_dir, method: str) -> None:
    if not marker_dir:
        return
    p = Path(marker_dir) / MARKER_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts": time.time(), "method": method}, ensure_ascii=False),
                 encoding="utf-8")


def _send(endpoint: str, payload: dict) -> dict:
    """One direct-connection POST (proxy env vars bypassed); only 2xx counts."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=HTTP_TIMEOUT_S) as resp:
            code = resp.getcode() or 0
    except urllib.error.HTTPError as e:
        return {"sent": False, "reason": f"http_{e.code}"}
    except Exception as e:
        return {"sent": False, "reason": f"send_failed: {type(e).__name__}"}
    if 200 <= code < 300:
        return {"sent": True, "reason": "ok"}
    return {"sent": False, "reason": f"http_{code}"}


def _fire(method: str, params: str, marker_dir) -> dict:
    if not method:
        return {"sent": False, "reason": "no_method"}
    endpoint = _resolve_endpoint()
    if not endpoint:
        # fully lazy: no endpoint -> zero network, zero disk, zero cooldown churn
        return {"sent": False, "reason": "no_endpoint"}
    if _cooldown_active(marker_dir, method):
        return {"sent": False, "reason": "cooldown"}
    payload = {
        "username": _collect_username(),
        "ip": _collect_ip(endpoint),
        "operation": OPERATIONS.get(method, method),
        "method": method,
        "params": params[:PARAMS_MAX_CHARS],
        "time": PLACEHOLDER_TIME,
    }
    # the marker records the ATTEMPT (not the delivery): a dead endpoint costs at
    # most one timeout per window instead of one per repeated query
    try:
        _write_marker(marker_dir, method)
    except Exception:
        pass
    return _send(endpoint, payload)


def main():
    # Emit JSON cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        description="fire-and-forget usage telemetry for the mgh-* command family "
                    "(one POST, never raises; imports as a module at the mount sites)")
    ap.add_argument("--method", required=True,
                    help="raw command name (mgh-xxx form); drives the closed "
                         "operation map")
    ap.add_argument("--params", default="",
                    help="invocation parameters, passed through verbatim "
                         f"(truncated at {PARAMS_MAX_CHARS} characters)")
    ap.add_argument("--marker-dir",
                    help="dir for the cooldown marker telemetry_last.json "
                         "(the command's product dir); omit = no cooldown")
    args = ap.parse_args()
    result = fire(args.method, args.params, args.marker_dir)
    print(json.dumps({"sent": bool(result.get("sent")),
                      "reason": str(result.get("reason", ""))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
