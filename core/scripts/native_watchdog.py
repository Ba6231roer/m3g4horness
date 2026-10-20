#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
native_watchdog — out-of-process safety net for a native-dispatch session tree.

When an orchestrator session dispatches subagent sessions through the local
opencode host service, a stuck child (a permission dialog nobody will answer,
a form nobody will fill, a live-but-non-converging turn) has no external
control plane: the runner-era "byte-silence + process-tree kill" surfaces are
gone. This script is the independent observer: it reads the service registry,
connects to the LOCAL host service, scopes itself to one root session plus all
its descendants, polls their activity/waiting/progress state, and acts on
stalls — reply-reject overdue permission asks, cancel overdue forms, interrupt
silent or over-deadline descendants. Every action is recorded; destructive
action can be previewed with --dry-run. It writes NO unit markers anywhere
(the on-disk .done/.failed truth stays owned by the units' own discipline) and
it NEVER restarts the host service (a shared service restart is a human
decision).

Scope safety: the target set is "root session + descendants" only. Root id
comes from --root, else from the OPENCODE_SESSION_ID environment variable
(set automatically by host shell tools). Before EVERY action the target's
ancestor chain is re-walked against the live service; a session that left the
tree is skipped and the skip is recorded. Out-of-tree sessions are only ever
seen through list enumeration (read-only). A root id that does not exist on
the service is a fail-loud exit, not an empty watch.

Service discovery (first match wins): --service-json <path>, else
<XDG_STATE_HOME or ~/.local/state>/opencode/service.json. The registry holds
{url, password, ...}; auth is HTTP Basic (fixed user name). The registry url
must point at the loopback (127.0.0.1 / localhost / ::1) — anything else is
refused BEFORE any connection is made (this tool holds a local credential and
must never be aimable at a remote host). On auth failure or connection loss
the registry is re-read (the service rotates its password on restart) and the
request retried once; a persistently unreachable service is reflected in the
exit status. The password lives in memory only.

Action ladder (all gated by --dry-run, which reports without issuing any
write request):
  1. permission pending longer than --ask-grace-s (measured from first sight;
     the request object carries no timestamp) -> reply "reject" with a
     short continue-without-it message;
  2. form/question pending longer than --form-grace-s -> cancel with a
     message;
  3. descendant active but with no persistent progress (session update /
     newest message time) for longer than --silence-s, or older than
     --unit-deadline-s since creation -> interrupt the session (the host's
     interrupt also reaps its pending tools and shells; the unit, having no
     marker, returns to the pending set on the next enumeration);
  4. still busy after --interrupt-settle-s -> interrupt once more; still busy
     after that -> recorded as unresolved (needs a human), no infinite retry;
  5. the root session itself: silence/deadline are only RECORDED by default;
     --interrupt-root opts in to actually interrupting it (interrupting the
     root cancels the whole in-flight wave — last resort).

Terminal sessions (outcome succeeded/failed/interrupted) are never abort
candidates. Thresholds are convergence upper bounds, not health diagnostics:
they are deliberately wider than the host's own response/stream timeouts and
retries, so the watchdog only steps in when the host has had its chance.

Artifacts and exit: with --run-dir, every action/key observation is appended
to <run>/watchdog/events.jsonl (one JSON object per line; the password never
enters any artifact) and a tree snapshot is atomically written to
<run>/watchdog/state.json at most once per poll cycle; without --run-dir
nothing is written to disk (summary only; an artifact write failure warns on
stderr and never stops enforcement). stdout carries exactly one JSON summary
line; stderr carries heartbeats and recipes.

Exit codes: 0 = single scan done / tree settled / --deadline-s budget
exhausted with no unresolved hang · 2 = needs a human (unresolved hang after
two interrupts, service unreachable, service registry missing or non-loopback,
root session missing) · 1 = misuse (bad or missing arguments). Resident mode
self-exits when the tree has been idle with nothing pending for one
confirmation cycle, or when the --deadline-s budget is spent; --once performs
exactly one scan and exits (wave-boundary reconciliation / testing shape).

Zero runtime deps (Python >=3.10 stdlib: argparse/base64/json/os/pathlib/
sys/time/urllib — urllib is a loopback-only HTTP client).
"""
from __future__ import annotations
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOOL = "native_watchdog"

DEFAULT_POLL_S = 15.0
DEFAULT_ASK_GRACE_S = 90.0
DEFAULT_FORM_GRACE_S = 90.0
DEFAULT_SILENCE_S = 1200.0
DEFAULT_UNIT_DEADLINE_S = 3600.0
DEFAULT_INTERRUPT_SETTLE_S = 45.0

HTTP_TIMEOUT_S = 10.0
UNREACHABLE_CYCLES = 3      # consecutive failed cycles before resident exit 2
PAGE_LIMIT = 200            # session-list page size
MAX_PAGES = 10              # safety cap while following list cursors
MAX_TREE = 500              # safety cap on tree size
MAX_TREE_DEPTH = 32         # ancestor-chain walk cap
ROOT_ENV = "OPENCODE_SESSION_ID"
REGISTRY_REL = ("opencode", "service.json")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")

REJECT_DECISION = "reject"
REJECT_MESSAGE = ("Unattended mgh run (watchdog): interactive approval is "
                  "unavailable; this request is rejected. Continue without it "
                  "- use an allowed alternative and finish the turn.")
FORM_MESSAGE = ("Unattended mgh run (watchdog): nobody can answer this form; "
                "it was cancelled. Finish the turn with what you have.")


def _eprint(*a):
    print(*a, file=sys.stderr)


# --- errors ----------------------------------------------------------------------

class RegistryError(ValueError):
    """Service registry missing/unparsable/non-loopback (fail-closed)."""


class LoopbackError(RegistryError):
    """Registry url host is not a loopback address."""


class WDUnreachable(RuntimeError):
    """Service unreachable after the registry re-read + one retry."""


class WDRootMissing(RuntimeError):
    """The root session id does not exist on the service."""


# --- discovery --------------------------------------------------------------------

def loopback_host(url):
    """Loopback host of url (lowercased, brackets stripped) or None."""
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    return host if host in LOOPBACK_HOSTS else None


class ServiceRegistry:
    """Reader for the host service registration file (re-readable: the service
    rotates its password on restart, so consumers re-read on auth loss)."""

    def __init__(self, explicit_path=None):
        self.explicit = explicit_path
        self.url = ""
        self.password = ""

    def path(self) -> Path:
        if self.explicit:
            return Path(self.explicit)
        base = os.environ.get("XDG_STATE_HOME") or str(
            Path.home() / ".local" / "state")
        return Path(base).joinpath(*REGISTRY_REL)

    def load(self):
        """(Re)load url+password; raises RegistryError/LoopbackError, never
        touches the network. The url is normalized to its origin and the host
        is loopback-checked BEFORE any caller can connect to it."""
        p = self.path()
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except OSError as e:
            raise RegistryError(f"service registry unreadable: {p}: {e}") from e
        except ValueError as e:
            raise RegistryError(f"service registry unparsable: {p}: {e}") from e
        if not isinstance(body, dict):
            raise RegistryError(f"service registry not a JSON object: {p}")
        url = body.get("url")
        password = body.get("password")
        if not isinstance(url, str) or not url.strip():
            raise RegistryError(f"service registry has no url: {p}")
        if not isinstance(password, str) or not password:
            raise RegistryError(f"service registry has no password: {p}")
        if loopback_host(url) is None:
            raise LoopbackError(
                f"service registry url is not loopback: {p} — this tool only "
                f"talks to a local service ({', '.join(LOOPBACK_HOSTS)})")
        parts = urllib.parse.urlsplit(url.strip())
        origin = f"{parts.scheme}://{parts.netloc}"
        self.url, self.password = origin, password


# --- HTTP client (loopback-only; Basic auth; registry re-read on auth loss) -------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: a 3xx must never carry the credential to another
    host. Redirects are not part of the pinned service surface anyway."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code,
                                     "redirect refused", headers, fp)


class Client:
    """Thin API face over the pinned service endpoints (envelope {"data": …}).
    Every request retries once after re-reading the registry (service restart
    rotates the password); a second failure raises WDUnreachable. 404 maps to
    None (gone/missing) for the readers."""

    def __init__(self, registry, timeout=HTTP_TIMEOUT_S):
        self.registry = registry
        self.timeout = timeout
        self.url = ""
        self.password = ""
        self._opener = None

    def load(self):
        """Bind to the registry's current url+password (loopback enforced
        there). Called once up-front and again on auth loss / connection loss."""
        self.registry.load()
        self.url = self.registry.url
        self.password = self.registry.password
        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.ProxyHandler({}))

    def _auth_header(self):
        token = base64.b64encode(
            f"opencode:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def request(self, method, path, query=None, body=None):
        """One API call; returns the parsed JSON body (or None on 404)."""
        attempt = 0
        while True:
            url = self.url + path
            if query:
                url += "?" + urllib.parse.urlencode(query)
            headers = {"Authorization": self._auth_header(),
                       "Accept": "application/json"}
            data = None
            if body is not None:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json; charset=utf-8"
            req = urllib.request.Request(url, data=data, method=method,
                                         headers=headers)
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                return json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except urllib.error.HTTPError as e:
                e.close()
                if e.code == 404:
                    return None
                retriable = e.code in (401, 403) or e.code >= 500
                if not retriable or attempt:
                    raise WDUnreachable(f"http_{e.code}: {method} {path}") from e
            except (urllib.error.URLError, OSError, ValueError) as e:
                if attempt:
                    raise WDUnreachable(
                        f"connection lost: {method} {path}: {e}") from e
            attempt += 1
            try:
                self.load()   # registry re-read: the service may have rotated
            except RegistryError as e:
                raise WDUnreachable(f"registry re-read failed: {e}") from e

    @staticmethod
    def _data(payload):
        return payload.get("data") if isinstance(payload, dict) else None

    # -- read face -------------------------------------------------------------

    def get_session(self, sid):
        return self._data(self.request("GET", f"/api/session/{_q(sid)}"))

    def list_children(self, parent_id):
        sids, cursor = [], None
        for _ in range(MAX_PAGES):
            q = {"parentID": parent_id, "limit": str(PAGE_LIMIT),
                 "order": "asc"}
            if cursor:
                q["cursor"] = cursor
            payload = self.request("GET", "/api/session", query=q)
            rows = self._data(payload) or []
            for row in rows:
                if isinstance(row, dict) and row.get("id"):
                    sids.append(row["id"])
            cursor = (payload or {}).get("cursor", {}).get("next") \
                if isinstance(payload, dict) else None
            if not cursor:
                break
        return sids

    def get_active(self):
        data = self._data(self.request("GET", "/api/session/active"))
        return data if isinstance(data, dict) else {}

    def latest_message_ts(self, sid):
        """Newest persistent message boundary in epoch milliseconds (or None):
        the newest message's created time, or its stream-completion time when
        newer (pinned on 2.1.0: time.streamed)."""
        data = self._data(self.request(
            "GET", f"/api/session/{_q(sid)}/message", query={"limit": "1"}))
        if isinstance(data, list) and data:
            t = (data[0].get("time") or {}) if isinstance(data[0], dict) else {}
            cands = [float(v) for v in (t.get("created"), t.get("streamed"))
                     if isinstance(v, (int, float))
                     and not isinstance(v, bool)]
            if cands:
                return max(cands)
        return None

    def pending_permissions(self, sid):
        data = self._data(self.request(
            "GET", f"/api/session/{_q(sid)}/permission"))
        return [r for r in (data or []) if isinstance(r, dict) and r.get("id")]

    def pending_forms(self, sid):
        data = self._data(self.request(
            "GET", f"/api/session/{_q(sid)}/form"))
        return [f for f in (data or []) if isinstance(f, dict) and f.get("id")]

    # -- write face (the whole of it; every caller verifies tree membership) ----
    # Writers return whether the write actually landed: a 404 (request/form
    # gone between listing and acting — resolved by someone else) is NOT an
    # action and must not be counted as one.

    def reply_permission(self, sid, rid):
        return self.request(
            "POST", f"/api/session/{_q(sid)}/permission/{_q(rid)}/reply",
            body={"decision": REJECT_DECISION,
                  "message": REJECT_MESSAGE}) is not None

    def cancel_form(self, sid, fid):
        return self.request(
            "DELETE", f"/api/session/{_q(sid)}/form/{_q(fid)}",
            query={"message": FORM_MESSAGE}) is not None

    def interrupt(self, sid):
        # the interrupt endpoint returns SessionInterruptResponse BARE (no
        # {"data": …} envelope — pinned on live 2.1.0 during this change's
        # real-machine gate); any dict response = the write landed
        payload = self.request("POST", f"/api/session/{_q(sid)}/interrupt",
                               query={"resume": "false"})
        return isinstance(payload, dict)   # 404 -> None -> nothing landed


def _q(value):
    return urllib.parse.quote(str(value), safe="")


# --- config -----------------------------------------------------------------------

class Config:
    __slots__ = ("root", "run_dir", "service_json", "poll_s", "ask_grace_s",
                 "form_grace_s", "silence_s", "unit_deadline_s",
                 "interrupt_settle_s", "deadline_s", "once", "dry_run",
                 "interrupt_root")

    def __init__(self, root, poll_s=DEFAULT_POLL_S,
                 ask_grace_s=DEFAULT_ASK_GRACE_S,
                 form_grace_s=DEFAULT_FORM_GRACE_S,
                 silence_s=DEFAULT_SILENCE_S,
                 unit_deadline_s=DEFAULT_UNIT_DEADLINE_S,
                 interrupt_settle_s=DEFAULT_INTERRUPT_SETTLE_S,
                 deadline_s=None, once=False, dry_run=False,
                 interrupt_root=False, run_dir=None, service_json=None):
        self.root = root
        self.run_dir = run_dir
        self.service_json = service_json
        self.poll_s = poll_s
        self.ask_grace_s = ask_grace_s
        self.form_grace_s = form_grace_s
        self.silence_s = silence_s
        self.unit_deadline_s = unit_deadline_s
        self.interrupt_settle_s = interrupt_settle_s
        self.deadline_s = deadline_s
        self.once = once
        self.dry_run = dry_run
        self.interrupt_root = interrupt_root

    def thresholds(self) -> dict:
        return {"poll_s": self.poll_s, "ask_grace_s": self.ask_grace_s,
                "form_grace_s": self.form_grace_s, "silence_s": self.silence_s,
                "unit_deadline_s": self.unit_deadline_s,
                "interrupt_settle_s": self.interrupt_settle_s,
                "deadline_s": self.deadline_s}


# --- watchdog core ------------------------------------------------------------------

class Watchdog:
    """One scan per poll cycle; the entire judgment state lives in memory.

    first_seen   ("perm"|"form", sid, item_id) -> monotonic time of first sight
                 (permission/form objects carry no timestamp of their own).
    aborts       sid -> {"count", "at"} for the interrupt/settle/re-interrupt
                 ladder (two strikes, then unresolved — no infinite retry).
    planned      dry-run dedup set so repeated cycles do not multiply the
                 "would do" counters for the same stall.
    """

    def __init__(self, cfg, client, now_fn=time.monotonic, wall_fn=time.time):
        self.cfg = cfg
        self.client = client
        self.now_fn = now_fn
        self.wall_fn = wall_fn
        self.first_seen = {}
        self.aborts = {}
        self._abort_reasons = {}
        self.planned = set()
        self.unresolved = set()
        self.settled_prev = False
        self.root_stall_recorded = False
        self.cycles = 0
        self.unreachable_streak = 0
        self.last_tree_size = 0
        self.last_rows = []
        self.counters = {"permissions_rejected": 0, "forms_cancelled": 0,
                         "aborts": 0, "aborts_repeat": 0,
                         "unreachable_cycles": 0, "events_written": 0}
        self.exit_reason = None
        self.exit_code = None
        self.state_writer = None      # optional; called once per cycle end

    # -- events -----------------------------------------------------------------

    def _emit(self, sink, kind, **fields):
        event = {"ts": int(self.wall_fn() * 1000), "kind": kind, **fields}
        self.counters["events_written"] += 1
        if sink is not None:
            sink(event)
        return event

    # -- one scan cycle -----------------------------------------------------------

    def scan_once(self, eventsink=None):
        """Enumerate the tree, judge, act. Raises WDUnreachable (a request
        failed even after the registry re-read) or WDRootMissing."""
        self.cycles += 1
        ev = lambda kind, **f: self._emit(eventsink, kind, **f)
        now = self.now_fn()
        wall = self.wall_fn()

        root_info = self.client.get_session(self.cfg.root)
        if not isinstance(root_info, dict):
            raise WDRootMissing(
                f"root session {self.cfg.root} not found on the service")
        tree = {self.cfg.root: root_info}
        frontier = [self.cfg.root]
        while frontier:
            parent = frontier.pop(0)
            for sid in self.client.list_children(parent):
                if sid in tree or len(tree) >= MAX_TREE:
                    continue
                info = self.client.get_session(sid)
                if isinstance(info, dict):
                    tree[sid] = info
                    frontier.append(sid)

        active = self.client.get_active()
        pending_perm, pending_form, progress_s = {}, {}, {}
        busy = set()
        for sid, info in tree.items():
            perms = self.client.pending_permissions(sid)
            forms = self.client.pending_forms(sid)
            pending_perm[sid] = perms
            pending_form[sid] = forms
            progress_s[sid] = self._progress_ts(info, sid)
            for req in perms:
                self._mark_seen(ev, ("perm", sid, req["id"]), now,
                                session=sid, request=req["id"],
                                action=req.get("action"))
            for form in forms:
                self._mark_seen(ev, ("form", sid, form["id"]), now,
                                session=sid, form=form["id"],
                                title=form.get("title"))
            if perms or forms or sid in active:
                busy.add(sid)

        self._prune_state(tree, pending_perm, pending_form, busy, wall,
                          progress_s)

        # 1) overdue permission asks -> reject with a message (no verify, no act)
        for sid in sorted(tree):
            for req in pending_perm[sid]:
                key = ("perm", sid, req["id"])
                if now - self.first_seen[key] >= self.cfg.ask_grace_s:
                    self._act(ev, tree, sid, "permission", key,
                              self.client.reply_permission, sid, req["id"])
        # 2) overdue forms -> cancel with a message
        for sid in sorted(tree):
            for form in pending_form[sid]:
                key = ("form", sid, form["id"])
                if now - self.first_seen[key] >= self.cfg.form_grace_s:
                    self._act(ev, tree, sid, "form", key,
                              self.client.cancel_form, sid, form["id"])
        # 3)+4)+5) silence / unit-deadline interrupts with the settle ladder
        for sid in sorted(tree):
            info = tree[sid]
            if sid in self.aborts:
                self._advance_abort_ladder(ev, sid, now, sid in busy)
                continue
            self._judge_stall(ev, tree, sid, info, sid == self.cfg.root,
                              active, progress_s, wall)

        self.last_tree_size = len(tree)
        settled_now = not busy
        return {"settled": settled_now, "tree": tree, "busy": busy,
                "pending_perm": pending_perm, "pending_form": pending_form}

    # -- pieces ------------------------------------------------------------------

    def _mark_seen(self, ev, key, now, **fields):
        if key not in self.first_seen:
            self.first_seen[key] = now
            ev("pending_seen", target=key[0], **fields)

    def _prune_state(self, tree, pending_perm, pending_form, busy, wall,
                     progress_s):
        live = set()
        for sid in tree:
            for req in pending_perm[sid]:
                live.add(("perm", sid, req["id"]))
            for form in pending_form[sid]:
                live.add(("form", sid, form["id"]))
        for key in list(self.first_seen):
            if key not in live:
                del self.first_seen[key]
        for key in list(self.planned):
            if (key[0] in ("perm", "form") and key not in live) or \
                    (key[0] == "abort" and key[1] not in tree):
                self.planned.discard(key)
        for sid in list(self.aborts):
            if sid not in tree:
                del self.aborts[sid]
                self._abort_reasons.pop(sid, None)
        for sid in list(self.unresolved):
            if sid not in tree:
                self.unresolved.discard(sid)

        # per-session snapshot rows for the state file + heartbeat
        rows = []
        for sid in sorted(tree):
            info = tree[sid]
            t = info.get("time") or {}
            created = t.get("created")
            rows.append({
                "id": sid, "parentID": info.get("parentID"),
                "outcome": info.get("outcome"), "active": sid in busy,
                "pending_perm": len(pending_perm[sid]),
                "pending_form": len(pending_form[sid]),
                "progress_age_s": (round(wall - progress_s[sid], 1)
                                   if progress_s[sid] is not None else None),
                "unit_age_s": (round(wall - self._to_seconds(created), 1)
                               if isinstance(created, (int, float)) else None),
                "abort_count": self.aborts.get(sid, {}).get("count", 0),
                "unresolved": sid in self.unresolved})
        self.last_rows = rows

    def _progress_ts(self, info, sid):
        """Newest persistent progress in epoch seconds: max(session updated,
        newest message time). Tool boundaries are folded into the session
        update time by the host. None = no usable field (never guessed)."""
        t = info.get("time") or {}
        cands = []
        for k in ("updated", "idle"):
            v = t.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cands.append(self._to_seconds(v))
        try:
            msg = self.client.latest_message_ts(sid)
        except WDUnreachable:
            raise
        except Exception:
            msg = None
        if isinstance(msg, (int, float)):
            cands.append(self._to_seconds(msg))
        return max(cands) if cands else None

    @staticmethod
    def _to_seconds(v):
        return v / 1000.0 if v > 1e11 else float(v)   # ms vs s heuristic

    def _verify_in_tree(self, sid):
        """Fresh ancestor-chain walk (never trust the enumeration snapshot)."""
        cur, seen = sid, set()
        for _ in range(MAX_TREE_DEPTH):
            if cur == self.cfg.root:
                return True
            if cur in seen or not cur:
                return False
            seen.add(cur)
            info = self.client.get_session(cur)
            if not isinstance(info, dict):
                return False
            cur = info.get("parentID")
        return False

    def _act(self, ev, tree, sid, what, key, fn, *args):
        """Shared action path: fresh tree verification, dry-run gating,
        counter, event. Returns True when the write went through (or was
        planned in dry-run)."""
        if not self._verify_in_tree(sid):
            ev("abandoned_out_of_tree", session=sid, target=what)
            return False
        if self.cfg.dry_run:
            if key not in self.planned:
                self.planned.add(key)
                self._count_and_log(ev, what, sid, planned=True)
            return True
        ok = fn(*args)
        if key in self.planned:
            self.planned.discard(key)
        if ok:
            self._count_and_log(ev, what, sid, planned=False)
        else:
            # the target vanished between listing and acting: someone else
            # resolved it — record the skip, never count it as our action
            ev("action_skipped_gone", session=sid, target=what)
        return ok

    def _count_and_log(self, ev, what, sid, planned, repeat=None):
        if what == "permission":
            self.counters["permissions_rejected"] += 1
            ev("action_reject_permission", session=sid, dry_run=planned,
               message=REJECT_MESSAGE)
        elif what == "form":
            self.counters["forms_cancelled"] += 1
            ev("action_cancel_form", session=sid, dry_run=planned,
               message=FORM_MESSAGE)
        else:
            if repeat is None:               # dry-run path: state never mutated
                repeat = self.aborts.get(sid, {}).get("count", 0) >= 1
            self.counters["aborts_repeat" if repeat else "aborts"] += 1
            ev("action_abort", session=sid, dry_run=planned, repeat=repeat,
               reason=self._abort_reasons.get(sid, "stall"))

    def _judge_stall(self, ev, tree, sid, info, is_root, active, progress_s,
                     wall):
        """Fresh interrupt decision for a session with no abort history."""
        outcome = info.get("outcome")
        if outcome in ("succeeded", "failed", "interrupted"):
            return                      # terminal: nothing to converge
        t = info.get("time") or {}
        created = t.get("created")
        silent = sid in active and (
            progress_s[sid] is None or
            wall - progress_s[sid] > self.cfg.silence_s)
        over = (isinstance(created, (int, float)) and
                wall - self._to_seconds(created) > self.cfg.unit_deadline_s)
        if not (silent or over):
            if is_root and self.root_stall_recorded:
                self.root_stall_recorded = False   # recovered
            self.planned.discard(("abort", sid))
            return
        if is_root and not self.cfg.interrupt_root:
            if not self.root_stall_recorded:
                self.root_stall_recorded = True
                ev("root_stall", session=sid,
                   reason="deadline" if over else "silence",
                   note="recorded only; pass --interrupt-root to act")
            return
        self._do_abort(ev, sid, "deadline" if over else "silence")

    def _do_abort(self, ev, sid, reason):
        if not self._verify_in_tree(sid):
            ev("abandoned_out_of_tree", session=sid, target="abort")
            self.aborts.pop(sid, None)
            self._abort_reasons.pop(sid, None)
            self.unresolved.discard(sid)
            return False
        self._abort_reasons[sid] = reason
        count = self.aborts.get(sid, {}).get("count", 0)
        key = ("abort", sid)
        if self.cfg.dry_run:
            if key not in self.planned:
                self.planned.add(key)
                self._count_and_log(ev, "abort", sid, planned=True)
            return True
        if not self.client.interrupt(sid):
            ev("action_skipped_gone", session=sid, target="abort")
            self.aborts.pop(sid, None)
            self._abort_reasons.pop(sid, None)
            self.unresolved.discard(sid)
            return False
        was_repeat = count >= 1          # judged BEFORE the state update
        self.aborts[sid] = {"count": count + 1,
                            "at": self.now_fn()}
        self._count_and_log(ev, "abort", sid, planned=False,
                            repeat=was_repeat)
        return True

    def _advance_abort_ladder(self, ev, sid, now, is_busy):
        state = self.aborts[sid]
        if now - state["at"] < self.cfg.interrupt_settle_s:
            return                                  # inside the settle window
        if is_busy:
            if state["count"] < 2:
                self._do_abort(ev, sid, self._abort_reasons.get(sid, "stall"))
            elif sid not in self.unresolved:
                self.unresolved.add(sid)
                ev("unresolved", session=sid,
                   note="still busy after two interrupts; needs a human")
        else:
            del self.aborts[sid]
            self._abort_reasons.pop(sid, None)
            self.unresolved.discard(sid)
            ev("settled_after_abort", session=sid)

    # -- resident loop ---------------------------------------------------------------

    def run(self, eventsink=None):
        """Returns (exit_reason, exit_code). Exactly one state write per cycle
        via self.state_writer (when set), the last one carrying the outcome."""
        start = self.now_fn()
        while True:
            reason = code = None
            try:
                result = self.scan_once(eventsink)
                self.unreachable_streak = 0
            except WDRootMissing as e:
                _eprint(f"error: {e}")
                _eprint("recipe: check the --root value / "
                        f"{ROOT_ENV} against the service session list; the "
                        "service may have been restarted or the id mistyped.")
                reason, code = "root_missing", 2
            except WDUnreachable as e:
                self.unreachable_streak += 1
                self.counters["unreachable_cycles"] += 1
                self._emit(eventsink, "cycle_unreachable",
                           failures=self.unreachable_streak, detail=str(e))
                _eprint(f"[{TOOL}] service unreachable "
                        f"(failure {self.unreachable_streak}): {e}")
                if self.cfg.once or \
                        self.unreachable_streak >= UNREACHABLE_CYCLES:
                    _eprint("recipe: check `opencode service status` and the "
                            "registry file; NEVER restart the shared service "
                            "from automation — that is a human decision.")
                    reason, code = "unreachable", 2
            else:
                if self.cfg.once:
                    reason, code = "once", 0
                elif result["settled"] and self.settled_prev:
                    reason, code = "settled", 0
                else:
                    self.settled_prev = result["settled"]
                if reason is None and self.cfg.deadline_s is not None and \
                        self.now_fn() - start >= self.cfg.deadline_s:
                    code = 2 if self.unresolved else 0
                    reason = "deadline"
            self._cycle_end(eventsink, reason, code)
            if reason is not None:
                return reason, code
            self._sleep(self.cfg.poll_s)

    def _cycle_end(self, eventsink, reason, code):
        busy_n = sum(1 for r in self.last_rows if r["active"])
        _eprint(f"[{TOOL}] cycle={self.cycles} sessions={self.last_tree_size} "
                f"busy={busy_n} unresolved={len(self.unresolved)} "
                f"rejected={self.counters['permissions_rejected']} "
                f"cancelled={self.counters['forms_cancelled']} "
                f"aborts={self.counters['aborts']}")
        if reason is not None:
            self.exit_reason, self.exit_code = reason, code
            self._emit(eventsink, "exit", reason=reason, code=code)
        if self.state_writer is not None:
            try:
                self.state_writer(self.snapshot())
            except OSError as e:
                _eprint(f"[{TOOL}] warn: state write failed: {e}")

    def _sleep(self, seconds):
        time.sleep(seconds)

    # -- faces for main / tests ---------------------------------------------------

    def summary_counters(self):
        out = dict(self.counters)
        out["unresolved"] = sorted(self.unresolved)
        return out

    def snapshot(self):
        """State-file face: tree snapshot + judgment state (secret-free)."""
        return {"v": 1, "ts": int(self.wall_fn() * 1000), "tool": TOOL,
                "root": self.cfg.root, "mode": "once" if self.cfg.once
                else "resident",
                "dry_run": self.cfg.dry_run,
                "thresholds": self.cfg.thresholds(),
                "cycles": self.cycles,
                "sessions": self.last_tree_size,
                "tree": self.last_rows,
                "counters": dict(self.counters),
                "unresolved": sorted(self.unresolved),
                "exit_reason": self.exit_reason}


# --- CLI ------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """Family contract override: misuse exits 1 (not argparse's 2), so exit
    2 stays unambiguous as 'needs a human'."""

    def error(self, message):
        self.print_usage(sys.stderr)
        _eprint(f"error: {message}")
        raise SystemExit(1)


def _build_parser():
    ap = _Parser(
        prog=TOOL,
        description="out-of-process safety net for a native-dispatch session "
                    "tree: polls the local opencode host service, rejects "
                    "overdue permission asks, cancels overdue forms, "
                    "interrupts silent or over-deadline descendant sessions; "
                    "scoped to one root session + descendants, zero unit "
                    "marker writes, zero service restarts")
    ap.add_argument("--root", metavar="<ses_id>",
                    help=f"root session id (default: {ROOT_ENV} env, set "
                         "automatically inside host shell tools)")
    ap.add_argument("--run-dir", metavar="<dir>",
                    help="run dir: artifacts land in <dir>/watchdog/ "
                         "(events.jsonl appended, state.json atomic per "
                         "cycle); omit = summary only, nothing written")
    ap.add_argument("--service-json", metavar="<path>",
                    help="service registry override (default: "
                         "<XDG_STATE_HOME or ~/.local/state>/opencode/"
                         "service.json); loopback urls only")
    ap.add_argument("--poll-s", type=float, default=DEFAULT_POLL_S,
                    help=f"poll cycle in seconds (default {DEFAULT_POLL_S:g})")
    ap.add_argument("--ask-grace-s", type=float, default=DEFAULT_ASK_GRACE_S,
                    help=f"grace for a pending permission, first sight based "
                         f"(default {DEFAULT_ASK_GRACE_S:g}); 0 = immediate "
                         "reject (pure unattended)")
    ap.add_argument("--form-grace-s", type=float, default=DEFAULT_FORM_GRACE_S,
                    help=f"grace for a pending form/question, first sight "
                         f"based (default {DEFAULT_FORM_GRACE_S:g})")
    ap.add_argument("--silence-s", type=float, default=DEFAULT_SILENCE_S,
                    help=f"descendant silence window: active but no "
                         f"persistent progress for this long -> interrupt "
                         f"(default {DEFAULT_SILENCE_S:g}; convergence upper "
                         "bound, wider than host timeouts by design)")
    ap.add_argument("--unit-deadline-s", type=float,
                    default=DEFAULT_UNIT_DEADLINE_S,
                    help=f"descendant total-age cap since creation -> "
                         f"interrupt (default {DEFAULT_UNIT_DEADLINE_S:g})")
    ap.add_argument("--interrupt-settle-s", type=float,
                    default=DEFAULT_INTERRUPT_SETTLE_S,
                    help=f"wait after an interrupt before judging settled; "
                         f"still busy then -> interrupt again, still busy "
                         f"after the second -> unresolved (default "
                         f"{DEFAULT_INTERRUPT_SETTLE_S:g})")
    ap.add_argument("--deadline-s", type=float, default=None,
                    help="watchdog budget in seconds; when spent, exit 0 "
                         "(2 if unresolved hangs exist); omit = settle-based "
                         "self-exit only")
    ap.add_argument("--once", action="store_true",
                    help="single scan then exit (wave-boundary "
                         "reconciliation / testing shape)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report would-be actions (events + counters) and "
                         "send zero write requests")
    ap.add_argument("--interrupt-root", action="store_true",
                    help="allow interrupting the ROOT session on "
                         "silence/deadline (default: record only; interrupting "
                         "the root cancels the whole in-flight wave)")
    return ap


def _summary(wd, mode):
    counters = wd.summary_counters()
    return {"tool": TOOL, "v": 1, "mode": mode, "root": wd.cfg.root,
            "dry_run": wd.cfg.dry_run, "cycles": wd.cycles,
            "sessions": wd.last_tree_size,
            "permissions_rejected": counters["permissions_rejected"],
            "forms_cancelled": counters["forms_cancelled"],
            "aborts": counters["aborts"],
            "aborts_repeat": counters["aborts_repeat"],
            "unresolved": counters["unresolved"],
            "events_written": counters["events_written"],
            "unreachable_cycles": counters["unreachable_cycles"],
            "exit_reason": wd.exit_reason or "not_run",
            "ok": wd.exit_code == 0}


def _atomic_write_json(path: Path, payload):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = _build_parser().parse_args(argv)

    problems = []
    if args.poll_s <= 0:
        problems.append("--poll-s must be > 0")
    for flag, value in (("--ask-grace-s", args.ask_grace_s),
                        ("--form-grace-s", args.form_grace_s),
                        ("--silence-s", args.silence_s),
                        ("--unit-deadline-s", args.unit_deadline_s),
                        ("--interrupt-settle-s", args.interrupt_settle_s)):
        if value < 0:
            problems.append(f"{flag} must be >= 0")
    if args.deadline_s is not None and args.deadline_s <= 0:
        problems.append("--deadline-s must be > 0 when given")
    root = (args.root or os.environ.get(ROOT_ENV) or "").strip()
    if not root:
        problems.append(f"no root session id: pass --root <ses_id> or run "
                        f"inside the host shell so {ROOT_ENV} is set")
    if problems:
        for p in problems:
            _eprint(f"error: {p}")
        _eprint("recipe: run with --help for the flag table; the watchdog "
                "needs exactly one scope root and sane positive thresholds.")
        return 1

    cfg = Config(root, poll_s=args.poll_s, ask_grace_s=args.ask_grace_s,
                 form_grace_s=args.form_grace_s, silence_s=args.silence_s,
                 unit_deadline_s=args.unit_deadline_s,
                 interrupt_settle_s=args.interrupt_settle_s,
                 deadline_s=args.deadline_s, once=args.once,
                 dry_run=args.dry_run, interrupt_root=args.interrupt_root,
                 run_dir=args.run_dir, service_json=args.service_json)
    registry = ServiceRegistry(cfg.service_json)
    client = Client(registry)
    wd = Watchdog(cfg, client)

    # artifact wiring (best-effort: a broken artifact dir warns, never blocks)
    if cfg.run_dir:
        try:
            wdir = Path(cfg.run_dir) / "watchdog"
            wdir.mkdir(parents=True, exist_ok=True)
            events_path = wdir / "events.jsonl"
            state_path = wdir / "state.json"

            def sink(event, _p=events_path):
                with open(_p, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")

            def writer(snapshot, _p=state_path):
                _atomic_write_json(_p, snapshot)

            wd.state_writer = writer

            def announce(event):
                try:
                    sink(event)
                except OSError as e:
                    _eprint(f"[{TOOL}] warn: events write failed: {e}")
                if event["kind"].startswith("action_") or \
                        event["kind"] in ("unresolved", "exit",
                                          "abandoned_out_of_tree",
                                          "root_stall"):
                    _eprint(f"[{TOOL}] event: {event['kind']} "
                            + " ".join(f"{k}={v}" for k, v in event.items()
                                       if k not in ("ts", "kind")))
            eventsink = announce
        except OSError as e:
            _eprint(f"[{TOOL}] warn: artifact dir unavailable "
                    f"({cfg.run_dir}/watchdog): {e} — continuing without "
                    "artifacts")
            eventsink = None
    else:
        eventsink = None

    mode = "once" if cfg.once else "resident"
    try:
        client.load()
    except LoopbackError as e:
        _eprint(f"error: {e}")
        _eprint("recipe: point the service registry back at the local "
                "service; this tool never talks to a remote host.")
        wd.exit_reason, wd.exit_code = "non_loopback", 2
    except RegistryError as e:
        _eprint(f"error: {e}")
        _eprint("recipe: check the registry path (--service-json or "
                "<state-dir>/opencode/service.json); start the host service "
                "once so it registers itself.")
        wd.exit_reason, wd.exit_code = "unreachable", 2
    else:
        if cfg.dry_run:
            _eprint(f"[{TOOL}] dry-run: thresholds "
                    f"{json.dumps(cfg.thresholds())}")
        try:
            wd.run(eventsink)
        except KeyboardInterrupt:
            wd.exit_reason, wd.exit_code = "interrupted", 0
    print(json.dumps(_summary(wd, mode), ensure_ascii=False))
    return wd.exit_code if wd.exit_code is not None else 2


if __name__ == "__main__":
    sys.exit(main())
