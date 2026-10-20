#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""native_watchdog unit tests: service discovery (default path / --service-json
override / credential re-read after rotation / unreachable), loopback-only
enforcement (non-loopback url rejected with zero connections), scope ownership
(root from flag > env, recursive tree enumeration, out-of-tree sessions never
touched, ancestor-chain re-verification before every action, missing root
fail-loud), the action ladder (permission reject with never-approve anchor,
form cancel, silence + unit-deadline abort, abort-settle-unresolved ladder,
root exemption and --interrupt-root opt-in), --dry-run zero-write, threshold
boundaries (grace -1 tick idle / +1 tick action), resident self-exit (settled
after one confirmation cycle / --deadline-s budget), --once, the three exit
codes, events.jsonl + state.json artifacts (atomic write, secret-free, summary
consistency) and the zero-marker discipline.

The HTTP-level tests run against an in-process stdlib fake service
(ThreadingHTTPServer) that mirrors the pinned opencode 2.x API surface; the
timing-boundary tests drive Watchdog directly with an injected clock.

Run: py tests/test_native_watchdog.py
"""
import base64
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


import importlib.util  # noqa: E402  (kept next to _load for the red phase)

WD = _load("native_watchdog")


# --- in-process runner (captures stdout/stderr, restores select env keys) ------

_ENV_KEYS = ("OPENCODE_SESSION_ID", "XDG_STATE_HOME")


@contextlib.contextmanager
def _capture_env(env=None):
    saved = {k: os.environ.get(k) for k in _ENV_KEYS}
    try:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in (env or {}).items():
            if v is not None:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def run_main(argv, env=None):
    """Run WD.main in-process; returns (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with _capture_env(env):
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            code = WD.main(list(argv))
        finally:
            sys.stdout, sys.stderr = old
    return code, out.getvalue(), err.getvalue()


def summary_of(stdout):
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    assert len(lines) == 1, f"stdout must be exactly one line, got: {stdout!r}"
    return json.loads(lines[0])


# --- fake opencode service ------------------------------------------------------

FAKE_URL_HOST = "127.0.0.1"


class FakeState:
    def __init__(self):
        self.lock = threading.RLock()   # reentrant: routing holds it and calls
        self.password = "pw-one"        # helpers that take it again
        self.password = "pw-one"
        self.sessions = {}       # sid -> session dict
        self.active = set()      # sids currently running
        self.perms = {}          # sid -> [permission request dicts]
        self.forms = {}          # sid -> [form dicts]
        self.writes = []         # every non-GET: (method, path, body-dict|None)
        self.requests = []       # every authenticated request: (method, path)
        self.on_first_request = None   # callable(state) fired once, before auth

    def add_session(self, sid, parent=None, created_ms=None, updated_ms=None,
                    outcome=None, active=False, directory="C:\\fake\\proj"):
        now = int(time.time() * 1000)   # real epoch: fresh by default
        s = {"id": sid, "projectID": "p", "cost": 0, "tokens": {},
             "title": sid, "location": {"directory": directory},
             "time": {"created": created_ms if created_ms is not None else now,
                      "updated": updated_ms if updated_ms is not None else now}}
        if parent is not None:
            s["parentID"] = parent
        if outcome is not None:
            s["outcome"] = outcome
        with self.lock:
            self.sessions[sid] = s
            if active:
                self.active.add(sid)
        return s

    def add_perm(self, sid, rid, action="external_directory"):
        with self.lock:
            self.perms.setdefault(sid, []).append(
                {"id": rid, "sessionID": sid, "action": action,
                 "resources": ["C:/elsewhere/*"]})

    def add_form(self, sid, fid, title="confirm?"):
        with self.lock:
            self.forms.setdefault(sid, []).append(
                {"id": fid, "sessionID": sid, "title": title, "fields": []})

    def auth_header(self):
        token = base64.b64encode(f"opencode:{self.password}".encode()).decode()
        return f"Basic {token}"


def _children(state, parent):
    with state.lock:
        kids = [s for s in state.sessions.values() if s.get("parentID") == parent]
    kids.sort(key=lambda s: s["id"])
    return {"data": kids, "cursor": {"previous": None, "next": None}}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):   # silence the default stderr chatter
        pass

    # -- plumbing ------------------------------------------------------------
    def _send(self, code, payload=None):
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _authorized(self):
        state = self.server.state
        with state.lock:
            if state.on_first_request is not None and len(state.requests) <= 1:
                hook, state.on_first_request = state.on_first_request, None
                hook(state)
            expected = state.auth_header()
        supplied = self.headers.get("Authorization", "")
        return supplied == expected

    def _route(self, method):
        state = self.server.state
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        with state.lock:
            state.requests.append((method, path))
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        parts = [p for p in path.split("/") if p]   # ['api', ...]
        with state.lock:
            if method == "GET" and parts == ["api", "info"]:
                self._send(200, {"data": {"version": "2.1.0", "pid": 1}})
            elif method == "GET" and parts == ["api", "session", "active"]:
                self._send(200, {"data": {sid: {"type": "running"}
                                          for sid in state.active}})
            elif method == "GET" and parts == ["api", "session"]:
                parent = (query.get("parentID") or [None])[0]
                self._send(200, _children(state, parent))
            elif len(parts) == 3 and parts[:2] == ["api", "session"] \
                    and method == "GET":
                sid = parts[2]
                s = state.sessions.get(sid)
                self._send(200, {"data": s} if s is not None else None) \
                    if s is not None else self._send(404, {"error": "no session"})
            elif len(parts) == 4 and parts[:2] == ["api", "session"] \
                    and parts[3] == "message" and method == "GET":
                s = state.sessions.get(parts[2])
                if s is None:
                    self._send(404, {"error": "no session"})
                else:
                    msg = {"id": "msg_x", "time": {"created": s["time"]["updated"]},
                           "type": "idle"}
                    self._send(200, {"data": [msg],
                                     "cursor": {"previous": None, "next": None}})
            elif len(parts) == 4 and parts[:2] == ["api", "session"] \
                    and parts[3] == "permission" and method == "GET":
                self._send(200, {"data": list(state.perms.get(parts[2], []))})
            elif len(parts) == 6 and parts[:2] == ["api", "session"] \
                    and parts[3] == "permission" and parts[5] == "reply" \
                    and parts[4] and method == "POST":
                self._do_perm_reply(state, parts)
            elif len(parts) == 4 and parts[:2] == ["api", "session"] \
                    and parts[3] == "form" and method == "GET":
                self._send(200, {"data": list(state.forms.get(parts[2], []))})
            elif len(parts) == 5 and parts[:2] == ["api", "session"] \
                    and parts[4] and parts[3] == "form" and method == "DELETE":
                self._do_form_cancel(state, parts)
            elif len(parts) == 4 and parts[:2] == ["api", "session"] \
                    and parts[3] == "interrupt" and method == "POST":
                self._do_interrupt(state, parts)
            else:
                self._send(404, {"error": "no route"})

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            return None

    def _do_perm_reply(self, state, parts):
        sid, rid = parts[2], parts[4]   # /api/session/{sid}/permission/{rid}/reply
        body = self._read_body() or {}
        state.writes.append(("POST", self.path, body))
        lst = state.perms.get(sid, [])
        state.perms[sid] = [p for p in lst if p["id"] != rid]
        self._send(200, {})

    def _do_form_cancel(self, state, parts):
        sid, fid = parts[2], parts[4]
        state.writes.append(("DELETE", self.path, None))
        lst = state.forms.get(sid, [])
        state.forms[sid] = [f for f in lst if f["id"] != fid]
        self._send(200, {})

    def _do_interrupt(self, state, parts):
        sid = parts[2]
        state.writes.append(("POST", self.path, None))
        was = sid in state.active
        state.active.discard(sid)
        s = state.sessions.get(sid)
        if s is not None:
            s["outcome"] = "interrupted"
        # the real host returns SessionInterruptResponse BARE (no data envelope)
        self._send(200, {"interrupted": was})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_DELETE(self):
        self._route("DELETE")


class FakeService:
    """ThreadingHTTPServer wrapper; url() is a loopback address."""

    def __init__(self, state=None):
        self.state = state if state is not None else FakeState()
        self.httpd = ThreadingHTTPServer((FAKE_URL_HOST, 0), _Handler)
        self.httpd.state = self.state
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    def write_registry(self, path, password=None):
        body = {"id": "svc", "version": "2.1.0", "url": self.url,
                "pid": 1, "password": self.state.password}
        Path(path).write_text(json.dumps(body), encoding="utf-8")

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ServiceCase(unittest.TestCase):
    """Base: fake service + tmp registry + tmp run dir, all per-test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.svc = FakeService()
        self.registry = Path(self.tmp.name) / "service.json"
        self.svc.write_registry(self.registry)
        self.run_dir = Path(self.tmp.name) / "run"
        self.run_dir.mkdir()

    def tearDown(self):
        self.svc.stop()
        self.tmp.cleanup()

    def argv(self, root, *extra):
        return ["--root", root, "--service-json", str(self.registry),
                "--once", *extra]


# --- discovery -------------------------------------------------------------------

class TestDiscovery(ServiceCase):
    def test_help_lists_all_flags_and_defaults(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                WD.main(["--help"])
                code = 0
            except SystemExit as e:
                code = e.code
        self.assertEqual(code, 0)
        text = out.getvalue()
        for flag, default in (
                ("--root", None), ("--run-dir", None), ("--service-json", None),
                ("--poll-s", "15"), ("--ask-grace-s", "90"),
                ("--form-grace-s", "90"), ("--silence-s", "1200"),
                ("--unit-deadline-s", "3600"), ("--interrupt-settle-s", "45"),
                ("--deadline-s", None), ("--once", None), ("--dry-run", None),
                ("--interrupt-root", None)):
            self.assertIn(flag, text, flag)
            if default is not None:
                self.assertIn(default, text, f"{flag} default {default}")

    def test_default_path_via_xdg_state_home(self):
        state_dir = Path(self.tmp.name) / "xdg"
        (state_dir / "opencode").mkdir(parents=True)
        self.svc.write_registry(state_dir / "opencode" / "service.json")
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(
            ["--root", "ses_root", "--once"],
            env={"XDG_STATE_HOME": str(state_dir)})
        self.assertEqual(code, 0, err)
        self.assertEqual(summary_of(out)["exit_reason"], "once")

    def test_service_json_override_beats_default(self):
        # a broken default-path registry must not matter when --service-json wins
        state_dir = Path(self.tmp.name) / "xdg2"
        (state_dir / "opencode").mkdir(parents=True)
        (state_dir / "opencode" / "service.json").write_text("{bogus",
                                                             encoding="utf-8")
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(
            self.argv("ses_root"),
            env={"XDG_STATE_HOME": str(state_dir)})
        self.assertEqual(code, 0, err)

    def test_registry_missing_fails_loud(self):
        code, out, err = run_main(
            ["--root", "ses_root", "--service-json",
             str(Path(self.tmp.name) / "absent.json"), "--once"])
        self.assertEqual(code, 2)
        self.assertIn("recipe", err.lower())

    def test_rereads_registry_after_password_rotation(self):
        # the fake service rotates its password AND updates the registry file
        # before answering the first request with 401
        reg_path = self.registry

        def rotate(state):
            state.password = "pw-two"
            body = {"id": "svc", "version": "2.1.0", "url": self.svc.url,
                    "pid": 1, "password": "pw-two"}
            reg_path.write_text(json.dumps(body), encoding="utf-8")

        self.svc.state.on_first_request = rotate
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(self.argv("ses_root"))
        self.assertEqual(code, 0, err)
        self.assertGreaterEqual(len(self.svc.state.requests), 2)

    def test_unreachable_service_exit_2(self):
        dead = {"id": "svc", "version": "2.1.0",
                "url": "http://127.0.0.1:59999", "pid": 1, "password": "x"}
        self.registry.write_text(json.dumps(dead), encoding="utf-8")
        code, out, err = run_main(self.argv("ses_root"))
        self.assertEqual(code, 2)
        self.assertEqual(summary_of(out)["exit_reason"], "unreachable")


class TestLoopback(unittest.TestCase):
    def test_loopback_host_pure_function(self):
        f = WD.loopback_host
        self.assertEqual(f("http://127.0.0.1:45278/api"), "127.0.0.1")
        self.assertEqual(f("http://LOCALHOST:1/x"), "localhost")
        self.assertEqual(f("http://[::1]:80/x"), "::1")
        self.assertIsNone(f("http://10.0.0.5:1234"))
        self.assertIsNone(f("https://example.com/x"))
        self.assertIsNone(f("not a url"))

    def test_non_loopback_registry_rejected_without_connecting(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            svc = FakeService()          # a real listener that must NOT be hit
            reg = Path(tmp.name) / "svc.json"
            body = {"id": "svc", "version": "2.1.0",
                    "url": "http://10.255.255.1:9", "pid": 1, "password": "x"}
            reg.write_text(json.dumps(body), encoding="utf-8")
            code, out, err = run_main(
                ["--root", "ses_root", "--service-json", str(reg), "--once"])
            self.assertEqual(code, 2)
            self.assertEqual(summary_of(out)["exit_reason"], "non_loopback")
            self.assertIn("recipe", err.lower())
            self.assertEqual(svc.state.requests, [])
            svc.stop()
        finally:
            tmp.cleanup()


# --- scope ownership -------------------------------------------------------------

class TestScope(ServiceCase):
    def setUp(self):
        super().setUp()
        st = self.svc.state
        st.add_session("ses_root")
        st.add_session("ses_c1", parent="ses_root")
        st.add_session("ses_c2", parent="ses_root")
        st.add_session("ses_g1", parent="ses_c1")
        st.add_session("ses_out", parent=None)   # someone else's work
        st.add_session("ses_out2", parent="ses_out")

    def test_out_of_tree_sessions_never_touched(self):
        st = self.svc.state
        st.add_perm("ses_out", "per_out")       # waiting auth OUTSIDE the tree
        st.add_perm("ses_c1", "per_in")
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "0"))
        self.assertEqual(code, 0, err)
        writes = [w for w in st.writes if "ses_out" in w[1]]
        self.assertEqual(writes, [], f"out-of-tree writes: {writes}")
        self.assertTrue(any(p["id"] == "per_out"
                            for p in st.perms.get("ses_out", [])))
        self.assertEqual([p["id"] for p in st.perms.get("ses_c1", [])], [])

    def test_root_flag_beats_env(self):
        st = self.svc.state
        st.add_session("ses_envroot")
        st.add_perm("ses_envroot", "per_env")
        st.add_perm("ses_c2", "per_flag")
        code, out, err = run_main(
            ["--root", "ses_root", "--service-json", str(self.registry),
             "--once", "--ask-grace-s", "0"],
            env={"OPENCODE_SESSION_ID": "ses_envroot"})
        self.assertEqual(code, 0, err)
        writes = [w for w in st.writes if "ses_envroot" in w[1]]
        self.assertEqual(writes, [])
        self.assertEqual(len(st.writes), 1)      # exactly the flag-tree perm

    def test_env_root_used_when_flag_absent(self):
        st = self.svc.state
        st.add_perm("ses_envroot2", "per_env2")
        st.add_session("ses_envroot2")
        code, out, err = run_main(
            ["--service-json", str(self.registry), "--once",
             "--ask-grace-s", "0"],
            env={"OPENCODE_SESSION_ID": "ses_envroot2"})
        self.assertEqual(code, 0, err)
        self.assertEqual(len(st.writes), 1)

    def test_missing_root_fails_loud(self):
        code, out, err = run_main(self.argv("ses_absent"))
        self.assertEqual(code, 2)
        self.assertEqual(summary_of(out)["exit_reason"], "root_missing")
        self.assertIn("recipe", err.lower())

    def test_no_root_anywhere_is_misuse(self):
        code, out, err = run_main(
            ["--service-json", str(self.registry), "--once"])
        self.assertEqual(code, 1)
        self.assertIn("recipe", err.lower())


class TestAncestorRecheck(unittest.TestCase):
    """Action-time ancestor-chain re-verification against a stub client."""

    def _wd_with_stale_tree(self):
        class StubClient(WD.Client):
            def __init__(self):
                super().__init__(WD.ServiceRegistry(explicit_path=None))
                self.interrupts = []

            def load(self):          # never touch the network
                self.url = "http://127.0.0.1:1"
                self.password = "x"

            def get_session(self, sid):
                # ses_drift was re-parented OUT of the tree after enumeration
                return {"id": sid, "time": {"created": 1, "updated": 1},
                        "parentID": "ses_elsewhere"
                        if sid == "ses_drift" else None}

            def list_children(self, parent_id):
                return (["ses_drift"] if parent_id == "ses_root" else [])

            def get_active(self):
                return {"ses_drift": {"type": "running"}}

            def latest_message_ts(self, sid):
                return None

            def pending_permissions(self, sid):
                return []

            def pending_forms(self, sid):
                return []

            def interrupt(self, sid):
                self.interrupts.append(sid)
                return True

        cfg = WD.Config(root="ses_root", silence_s=0, poll_s=0.05,
                        interrupt_settle_s=0)
        wd = WD.Watchdog(cfg, StubClient(),
                         now_fn=lambda: 1000.0, wall_fn=lambda: 1_700_000_000.0)
        return wd

    def test_stale_snapshot_action_abandoned(self):
        wd = self._wd_with_stale_tree()
        events = []
        wd.scan_once(eventsink=events.append)
        wd.scan_once(eventsink=events.append)
        self.assertEqual(wd.client.interrupts, [])
        kinds = [e["kind"] for e in events]
        self.assertIn("abandoned_out_of_tree", kinds)


# --- action ladder ----------------------------------------------------------------

class TestActions(ServiceCase):
    def setUp(self):
        super().setUp()
        self.st = self.svc.state
        self.st.add_session("ses_root")
        self.st.add_session("ses_c1", parent="ses_root")

    def _interrupt_writes(self):
        return [w for w in self.st.writes
                if w[1].split("?")[0].endswith("/interrupt")]

    def test_permission_rejected_with_message_never_approved(self):
        self.st.add_perm("ses_c1", "per_1")
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "0"))
        self.assertEqual(code, 0, err)
        replies = [w for w in self.st.writes if w[0] == "POST" and "reply" in w[1]]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][2].get("decision"), "reject")
        self.assertTrue(replies[0][2].get("message"))
        self.assertEqual([p["id"] for p in self.st.perms.get("ses_c1", [])], [])

    def test_never_approve_source_anchor(self):
        # the only decision literal in the source is "reject"; the approve
        # decisions must not appear anywhere (code, comments, help text)
        src = (SCRIPTS / "native_watchdog.py").read_text(encoding="utf-8")
        self.assertNotIn("always", src)
        self.assertIn('REJECT_DECISION = "reject"', src)

    def test_permission_within_grace_not_touched(self):
        self.st.add_perm("ses_c1", "per_2")
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "3600"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.st.writes, [])

    def test_form_cancelled_with_message(self):
        self.st.add_form("ses_c1", "form_1")
        code, out, err = run_main(self.argv("ses_root", "--form-grace-s", "0"))
        self.assertEqual(code, 0, err)
        dels = [w for w in self.st.writes if w[0] == "DELETE"]
        self.assertEqual(len(dels), 1)
        self.assertIn("form_1", dels[0][1])
        self.assertIn("message=", dels[0][1])
        self.assertEqual(self.st.forms.get("ses_c1", []), [])

    def test_silent_active_descendant_aborted(self):
        self.st.active.add("ses_c1")
        old = 1_700_000_000_000 - 10_000_000   # ~3h stale progress
        self.st.sessions["ses_c1"]["time"]["updated"] = old
        code, out, err = run_main(self.argv("ses_root", "--silence-s", "0"))
        self.assertEqual(code, 0, err)
        interrupts = self._interrupt_writes()
        self.assertEqual(len(interrupts), 1)
        self.assertIn("resume=false", interrupts[0][1])
        self.assertEqual(self.st.sessions["ses_c1"]["outcome"], "interrupted")

    def test_unit_deadline_abort_on_active_descendant(self):
        self.st.active.add("ses_c1")
        now = int(time.time() * 1000)
        s = self.st.sessions["ses_c1"]
        s["time"]["created"] = now - 100_000_000   # ~28h old
        s["time"]["updated"] = now                 # fresh progress — not silent
        code, out, err = run_main(self.argv("ses_root", "--unit-deadline-s", "0"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self._interrupt_writes()), 1)

    def test_healthy_descendant_not_aborted(self):
        self.st.active.add("ses_c1")
        now = int(time.time() * 1000)
        s = self.st.sessions["ses_c1"]
        s["time"]["created"] = now - 60_000
        s["time"]["updated"] = now - 5_000
        code, out, err = run_main(self.argv("ses_root"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.st.writes, [])

    def test_root_stall_recorded_not_aborted_by_default(self):
        self.st.active.add("ses_root")
        old = 1_700_000_000_000 - 10_000_000
        self.st.sessions["ses_root"]["time"]["updated"] = old
        code, out, err = run_main(self.argv("ses_root", "--silence-s", "0"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self._interrupt_writes(), [])

    def test_root_abort_with_interrupt_root_opt_in(self):
        self.st.active.add("ses_root")
        old = 1_700_000_000_000 - 10_000_000
        self.st.sessions["ses_root"]["time"]["updated"] = old
        code, out, err = run_main(self.argv("ses_root", "--silence-s", "0",
                                            "--interrupt-root"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self._interrupt_writes()), 1)

    def test_terminal_sessions_never_aborted(self):
        self.st.sessions["ses_c1"]["outcome"] = "succeeded"
        old = 1_700_000_000_000 - 100_000_000
        self.st.sessions["ses_c1"]["time"]["created"] = old
        self.st.sessions["ses_c1"]["time"]["updated"] = old
        code, out, err = run_main(self.argv("ses_root", "--unit-deadline-s", "0",
                                            "--silence-s", "0"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.st.writes, [])


class TestAbortSettleLadder(unittest.TestCase):
    """abort → still active after settle window → abort again → unresolved."""

    def _client(self, ignore_interrupt):
        class StubClient(WD.Client):
            def __init__(self):
                super().__init__(WD.ServiceRegistry(explicit_path=None))
                self.interrupts = []

            def load(self):
                self.url = "http://127.0.0.1:1"
                self.password = "x"

            def get_session(self, sid):
                return {"id": sid, "time": {"created": 1_000, "updated": 1_000},
                        "parentID": None if sid == "ses_root" else "ses_root"}

            def list_children(self, parent_id):
                return ["ses_c1"] if parent_id == "ses_root" else []

            def get_active(self):
                # stays active forever when the stub "ignores" the interrupt
                return {} if (self.interrupts and not ignore_interrupt) \
                    else {"ses_c1": {"type": "running"}}

            def latest_message_ts(self, sid):
                return None

            def pending_permissions(self, sid):
                return []

            def pending_forms(self, sid):
                return []

            def interrupt(self, sid):
                self.interrupts.append(sid)
                return True

        return StubClient()

    def _wd(self, client, now):
        cfg = WD.Config(root="ses_root", silence_s=0, poll_s=1.0,
                        interrupt_settle_s=10.0)
        return WD.Watchdog(cfg, client, now_fn=lambda: now[0],
                           wall_fn=lambda: 1_700_000_000.0 + now[0])

    def test_abort_then_settles_after_interrupt(self):
        now = [1000.0]
        client = self._client(ignore_interrupt=False)
        wd = self._wd(client, now)
        events = []
        wd.scan_once(eventsink=events.append)      # abort #1
        self.assertEqual(len(client.interrupts), 1)
        now[0] += 1
        wd.scan_once(eventsink=events.append)      # inside settle window: wait
        self.assertEqual(len(client.interrupts), 1)
        now[0] += 20
        wd.scan_once(eventsink=events.append)      # settled: clear state
        self.assertEqual(len(client.interrupts), 1)
        kinds = [e["kind"] for e in events]
        self.assertIn("settled_after_abort", kinds)
        self.assertEqual(wd.unresolved, set())

    def test_two_strikes_then_unresolved(self):
        now = [1000.0]
        client = self._client(ignore_interrupt=True)
        wd = self._wd(client, now)
        events = []
        wd.scan_once(eventsink=events.append)      # abort #1
        now[0] += 20
        wd.scan_once(eventsink=events.append)      # still busy -> abort #2
        self.assertEqual(len(client.interrupts), 2)
        now[0] += 20
        wd.scan_once(eventsink=events.append)      # still busy -> unresolved
        self.assertIn("ses_c1", wd.unresolved)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds.count("action_abort"), 2)
        # the FIRST strike counts as a plain abort, only the second repeats
        first, second = [e for e in events if e["kind"] == "action_abort"]
        self.assertFalse(first["repeat"])
        self.assertTrue(second["repeat"])
        c = wd.summary_counters()
        self.assertEqual(c["aborts"], 1)
        self.assertEqual(c["aborts_repeat"], 1)
        self.assertIn("unresolved", kinds)
        self.assertEqual(c["unresolved"], ["ses_c1"])


class TestDryRun(ServiceCase):
    def test_dry_run_zero_write_requests(self):
        st = self.svc.state
        st.add_session("ses_root")
        st.add_session("ses_c1", parent="ses_root")
        st.add_perm("ses_c1", "per_dry")
        st.add_form("ses_c1", "form_dry")
        st.active.add("ses_c1")
        st.sessions["ses_c1"]["time"]["updated"] = 1_700_000_000_000 - 10_000_000
        code, out, err = run_main(self.argv("ses_root", "--dry-run",
                                            "--ask-grace-s", "0",
                                            "--form-grace-s", "0",
                                            "--silence-s", "0"))
        self.assertEqual(code, 0, err)
        self.assertEqual(st.writes, [], "dry-run must send zero write requests")
        s = summary_of(out)
        self.assertTrue(s["dry_run"])
        self.assertEqual(s["permissions_rejected"], 1)
        self.assertEqual(s["forms_cancelled"], 1)
        self.assertEqual(s["aborts"], 1)
        # the pending items survive (nothing was really done)
        self.assertTrue(st.perms.get("ses_c1"))
        self.assertTrue(st.forms.get("ses_c1"))
        self.assertIn("ses_c1", st.active)


# --- threshold boundaries (injected clock, no sleeps) -----------------------------

class _ClockClient(WD.Client):
    """Minimal stub over a configurable session snapshot."""

    def __init__(self, tree, active, perms=None, forms=None):
        super().__init__(WD.ServiceRegistry(explicit_path=None))
        self.tree = tree                  # sid -> session dict (parentID in it)
        self.active = active
        self.perms = perms or {}
        self.forms = forms or {}
        self.replies = []
        self.cancels = []
        self.interrupts = []

    def load(self):
        self.url = "http://127.0.0.1:1"
        self.password = "x"

    def get_session(self, sid):
        s = self.tree.get(sid)
        return dict(s) if s else None

    def list_children(self, parent_id):
        return sorted(sid for sid, s in self.tree.items()
                      if s.get("parentID") == parent_id)

    def get_active(self):
        return {sid: {"type": "running"} for sid in self.active}

    def latest_message_ts(self, sid):
        return None

    def pending_permissions(self, sid):
        return list(self.perms.get(sid, []))

    def pending_forms(self, sid):
        return list(self.forms.get(sid, []))

    def reply_permission(self, sid, rid):
        self.replies.append((sid, rid))
        return True

    def cancel_form(self, sid, fid):
        self.cancels.append((sid, fid))
        return True

    def interrupt(self, sid):
        self.interrupts.append(sid)
        self.active.discard(sid)
        return True


def _tree(root="ses_root", child="ses_c1", created=1_000, updated=1_000):
    return {
        root: {"id": root, "time": {"created": created, "updated": updated}},
        child: {"id": child, "parentID": root,
                "time": {"created": created, "updated": updated}},
    }


class TestThresholds(unittest.TestCase):
    def _wd(self, client, grace, now_holder):
        cfg = WD.Config(root="ses_root", ask_grace_s=grace, poll_s=5.0,
                        silence_s=10_000.0, unit_deadline_s=10_000.0,
                        interrupt_settle_s=1.0)
        return WD.Watchdog(cfg, client, now_fn=lambda: now_holder[0],
                           wall_fn=lambda: 1_700_000_000.0 + now_holder[0])

    def test_grace_minus_one_tick_idle_plus_one_tick_action(self):
        now = [100.0]
        client = _ClockClient(_tree(), active=set(),
                              perms={"ses_c1": [{"id": "per_b", "sessionID":
                                                 "ses_c1", "action": "read",
                                                 "resources": []}]})
        wd = self._wd(client, grace=30.0, now_holder=now)
        wd.scan_once()                # first sight at t=100
        self.assertEqual(client.replies, [])
        now[0] += 29.0                # 29s since first sight < grace
        wd.scan_once()
        self.assertEqual(client.replies, [])
        now[0] += 2.1                 # 31.1s since first sight > grace
        wd.scan_once()
        self.assertEqual(client.replies, [("ses_c1", "per_b")])

    def test_first_seen_restarts_for_new_request_id(self):
        now = [100.0]
        client = _ClockClient(_tree(), active=set(),
                              perms={"ses_c1": [{"id": "per_a", "sessionID":
                                                 "ses_c1", "action": "read",
                                                 "resources": []}]})
        wd = self._wd(client, grace=30.0, now_holder=now)
        wd.scan_once()                # first sight at t=100
        now[0] += 100                 # t=200, far past grace
        wd.scan_once()
        self.assertEqual(client.replies, [("ses_c1", "per_a")])
        # a NEW request id starts its own grace window
        client.perms["ses_c1"] = [{"id": "per_b", "sessionID": "ses_c1",
                                   "action": "read", "resources": []}]
        now[0] += 1                   # t=201, first sight of per_b
        wd.scan_once()
        self.assertEqual(len(client.replies), 1)
        now[0] += 31.1                # 32.1s since per_b first seen
        wd.scan_once()
        self.assertEqual(client.replies[-1], ("ses_c1", "per_b"))


# --- resident lifecycle -------------------------------------------------------------

class TestResident(ServiceCase):
    def test_settled_tree_exits_after_confirmation_cycle(self):
        self.svc.state.add_session("ses_root", outcome="succeeded")
        t0 = time.monotonic()
        code, out, err = run_main(["--root", "ses_root", "--service-json",
                                   str(self.registry), "--poll-s", "0.05"])
        elapsed = time.monotonic() - t0
        self.assertEqual(code, 0, err)
        s = summary_of(out)
        self.assertEqual(s["exit_reason"], "settled")
        self.assertGreaterEqual(s["cycles"], 2)
        self.assertLess(elapsed, 10)

    def test_deadline_budget_self_exit(self):
        st = self.svc.state
        st.add_session("ses_root")
        st.add_session("ses_c1", parent="ses_root")
        st.active.add("ses_c1")   # busy forever -> never settles
        code, out, err = run_main(["--root", "ses_root", "--service-json",
                                   str(self.registry), "--poll-s", "0.05",
                                   "--deadline-s", "0.3"])
        self.assertEqual(code, 0, err)
        s = summary_of(out)
        self.assertEqual(s["exit_reason"], "deadline")
        self.assertEqual(s["unresolved"], [])

    def test_once_mode_single_cycle(self):
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(self.argv("ses_root"))
        s = summary_of(out)
        self.assertEqual(code, 0)
        self.assertEqual(s["mode"], "once")
        self.assertEqual(s["cycles"], 1)

    def test_busy_then_idle_settles(self):
        st = self.svc.state
        st.add_session("ses_root", outcome="succeeded")
        st.add_session("ses_c1", parent="ses_root")
        st.active.add("ses_c1")
        threading.Timer(0.12, lambda: st.active.discard("ses_c1")).start()
        code, out, err = run_main(["--root", "ses_root", "--service-json",
                                   str(self.registry), "--poll-s", "0.05"])
        self.assertEqual(code, 0, err)
        self.assertEqual(summary_of(out)["exit_reason"], "settled")


class TestExitCodes(ServiceCase):
    def test_exit_zero_plain_once(self):
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(self.argv("ses_root"))
        self.assertEqual(code, 0)

    def test_exit_two_unresolved_on_deadline(self):
        # session ignores interrupts (stays active): two strikes -> unresolved,
        # and the deadline exhaustion must surface it as exit 2
        st = self.svc.state
        st.add_session("ses_root", outcome="succeeded")
        st.add_session("ses_c1", parent="ses_root")
        st.active.add("ses_c1")
        st.sessions["ses_c1"]["time"]["updated"] = int(time.time() * 1000) - 10_000_000

        real_route = _Handler._do_interrupt

        def stubborn(handler, state, parts):
            sid = parts[2]
            state.writes.append(("POST", handler.path, None))
            state.active.add(sid)           # refuses to die
            handler._send(200, {"interrupted": True})

        _Handler._do_interrupt = stubborn
        try:
            code, out, err = run_main(["--root", "ses_root", "--service-json",
                                       str(self.registry), "--poll-s", "0.05",
                                       "--silence-s", "0",
                                       "--interrupt-settle-s", "0.05",
                                       "--deadline-s", "0.4"])
        finally:
            _Handler._do_interrupt = real_route
        self.assertEqual(code, 2, err)
        s = summary_of(out)
        self.assertEqual(s["unresolved"], ["ses_c1"])

    def test_exit_one_misuse_bad_poll(self):
        self.svc.state.add_session("ses_root", outcome="succeeded")
        code, out, err = run_main(self.argv("ses_root", "--poll-s", "0"))
        self.assertEqual(code, 1)


# --- artifacts & discipline -----------------------------------------------------------

class TestArtifacts(ServiceCase):
    def setUp(self):
        super().setUp()
        st = self.svc.state
        st.add_session("ses_root")
        st.add_session("ses_c1", parent="ses_root")
        st.add_perm("ses_c1", "per_art")

    def test_events_and_state_written_and_secret_free(self):
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "0",
                                            "--run-dir", str(self.run_dir)))
        self.assertEqual(code, 0, err)
        wdir = self.run_dir / "watchdog"
        events_path = wdir / "events.jsonl"
        state_path = wdir / "state.json"
        self.assertTrue(events_path.is_file())
        self.assertTrue(state_path.is_file())
        events = [json.loads(ln) for ln in
                  events_path.read_text(encoding="utf-8").splitlines() if ln]
        kinds = {e["kind"] for e in events}
        self.assertIn("action_reject_permission", kinds)
        self.assertIn("exit", kinds)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["root"], "ses_root")
        # the registry password must never appear in any artifact or stream
        for blob in (events_path.read_text(encoding="utf-8"),
                     state_path.read_text(encoding="utf-8"), out, err):
            self.assertNotIn("pw-one", blob)

    def test_atomic_state_write_uses_tmp_then_replace(self):
        observed = []
        real_replace = os.replace

        def spy(src, dst):
            observed.append((str(src), str(dst)))
            return real_replace(src, dst)

        old_replace = os.replace
        os.replace = spy
        try:
            code, out, err = run_main(self.argv("ses_root", "--once",
                                                "--run-dir", str(self.run_dir)))
        finally:
            os.replace = old_replace
        self.assertEqual(code, 0, err)
        self.assertGreaterEqual(len(observed), 1)
        for src, dst in observed:
            self.assertTrue(src.endswith(".tmp"), src)
            self.assertTrue(dst.endswith("state.json"), dst)
        leftovers = [p.name for p in (self.run_dir / "watchdog").iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_no_run_dir_writes_nothing(self):
        before = set(p.name for p in self.run_dir.iterdir())
        code, out, err = run_main(self.argv("ses_root"))   # no --run-dir
        self.assertEqual(code, 0, err)
        after = set(p.name for p in self.run_dir.iterdir())
        self.assertEqual(before, after)

    def test_summary_counters_match_events(self):
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "0",
                                            "--run-dir", str(self.run_dir)))
        s = summary_of(out)
        events = [json.loads(ln) for ln in
                  (self.run_dir / "watchdog" / "events.jsonl")
                  .read_text(encoding="utf-8").splitlines() if ln]
        rejects = [e for e in events if e["kind"] == "action_reject_permission"]
        self.assertEqual(s["permissions_rejected"], len(rejects))
        self.assertEqual(s["events_written"], len(events))


class TestZeroMarkers(ServiceCase):
    def test_watchdog_never_touches_unit_markers(self):
        st = self.svc.state
        st.add_session("ses_root")
        st.add_session("ses_c1", parent="ses_root")
        st.add_perm("ses_c1", "per_m")
        st.active.add("ses_c1")
        st.sessions["ses_c1"]["time"]["updated"] = 1_700_000_000_000 - 10_000_000
        # pre-seed the run dir with the unit-marker truth the orchestration owns
        (self.run_dir / "unit-a.done").write_text("{}", encoding="utf-8")
        (self.run_dir / "unit-b.failed").write_text("{}", encoding="utf-8")
        (self.run_dir / "checkpoints").mkdir()
        (self.run_dir / "checkpoints" / "unit-a.json").write_text(
            "{}", encoding="utf-8")
        before = sorted((p, p.stat().st_mtime) for p in self.run_dir.rglob("*"))
        code, out, err = run_main(self.argv("ses_root", "--ask-grace-s", "0",
                                            "--silence-s", "0",
                                            "--run-dir", str(self.run_dir)))
        self.assertEqual(code, 0, err)
        after = sorted((p, p.stat().st_mtime) for p in self.run_dir.rglob("*")
                       if "watchdog" not in p.parts)
        self.assertEqual([p for p, _ in before], [p for p, _ in after])
        self.assertEqual([m for _, m in before], [m for _, m in after])


if __name__ == "__main__":
    unittest.main()
