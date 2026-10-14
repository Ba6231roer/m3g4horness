#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""mgh_telemetry unit tests: closed-set content anchors, collection-chain
degradation, payload contract, endpoint resolution priority, cooldown window,
failure isolation, CLI misuse exit, and the mount-site existence anchors (each
launch-path script keeps its fire line; the 17 orchestration shells carry zero
telemetry tokens).

The content anchors (OPERATIONS below, MOUNTS in MountAnchors) ARE the drift
enforcement: editing the operation map or removing a mount line without the
matching edit here fails this file.

Run: py tests/test_mgh_telemetry.py
"""
import contextlib, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
import unittest.mock as mock
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


TELEM = _load("mgh_telemetry")

# --- the anchored closed operation map (edit together with mgh_telemetry) --------
OPERATIONS = {
    "mgh-init": "项目安全设计初始化",
    "mgh-sdr": "安全设计复核",
    "mgh-sra": "需求安全增强",
    "mgh-srr": "需求安全评审",
    "mgh-sast": "静态安全扫描",
    "mgh-ut-init": "测试约定初始化",
}

# --- the anchored mount set (edit together with the launch-path scripts) ---------
MOUNTS = {
    "write_runconfig.py": "mgh-init",
    "resume_state.py": "mgh-init",
    "write_ut_runconfig.py": "mgh-ut-init",
    "resume_ut_init_state.py": "mgh-ut-init",
    "sdr_context.py": "mgh-sdr",
    "resume_sdr_state.py": "mgh-sdr",
    "prepare_augment.py": "mgh-sra",
    "ingest_requirements.py": "mgh-srr",
}

UNREACHABLE = "http://127.0.0.1:59999/telemetry"   # closed port on localhost


def _pop_url():
    """Context-managed env without MGH_TELEMETRY_URL (the shipped lazy default)."""
    return mock.patch.dict(os.environ)


class OperationClosedSetAnchor(unittest.TestCase):
    """改映射不改测试 = 红:exact-set anchor over the six Chinese names."""

    def test_exact_six_mapping(self):
        self.assertEqual(TELEM.OPERATIONS, OPERATIONS)

    def test_unknown_method_falls_back_to_itself(self):
        self.assertEqual(TELEM.OPERATIONS.get("mgh-other", "mgh-other"), "mgh-other")


class _no_env_ctx:
    """Context manager running its body with MGH_TELEMETRY_URL absent AND the three
    username env sources removed (restored on exit)."""

    def __enter__(self):
        self._ctx = mock.patch.dict(os.environ)
        self._ctx.__enter__()
        os.environ.pop("MGH_TELEMETRY_URL", None)
        for var in ("USERNAME", "USER", "LOGNAME"):
            os.environ.pop(var, None)
        return self

    def __exit__(self, *a):
        return self._ctx.__exit__(*a)


class UsernameChainTests(unittest.TestCase):
    def test_domain_stripped(self):
        self.assertEqual(TELEM._strip_domain("DOMAIN\\zhangsan"), "zhangsan")
        self.assertEqual(TELEM._strip_domain("a\\b\\c"), "c")
        self.assertEqual(TELEM._strip_domain("zhangsan"), "zhangsan")

    def test_env_username_wins(self):
        with mock.patch.dict(os.environ, {"USERNAME": "CORP\\zhangsan"}):
            self.assertEqual(TELEM._collect_username(), "zhangsan")

    def test_env_user_fallback(self):
        with _no_env_ctx():
            os.environ["USER"] = "lisi"
            self.assertEqual(TELEM._collect_username(), "lisi")
            os.environ.pop("USER")
            os.environ["LOGNAME"] = "wangwu"
            self.assertEqual(TELEM._collect_username(), "wangwu")

    def test_falls_to_getpass(self):
        with _no_env_ctx():
            with mock.patch.object(TELEM.getpass, "getuser",
                                   return_value="CORP\\lisi"):
                self.assertEqual(TELEM._collect_username(), "lisi")

    def test_falls_to_whoami(self):
        with _no_env_ctx():
            with mock.patch.object(TELEM.getpass, "getuser",
                                   side_effect=OSError("nope")), \
                 mock.patch.object(TELEM.subprocess, "run",
                                   return_value=mock.Mock(stdout="CORP\\wang\n")):
                self.assertEqual(TELEM._collect_username(), "wang")

    def test_all_fail_unknown(self):
        with _no_env_ctx():
            with mock.patch.object(TELEM.getpass, "getuser",
                                   side_effect=OSError("nope")), \
                 mock.patch.object(TELEM.subprocess, "run",
                                   side_effect=OSError("nope")):
                self.assertEqual(TELEM._collect_username(), "unknown")


class IpChainTests(unittest.TestCase):
    def test_endpoint_host_probe_first(self):
        calls = []

        def fake(host, port):
            calls.append((host, port))
            return None if len(calls) == 1 else "10.0.0.1"

        with mock.patch.object(TELEM, "_udp_local_ip", side_effect=fake):
            self.assertEqual(TELEM._collect_ip("http://10.1.2.3:8080/api"), "10.0.0.1")
        self.assertEqual(calls[0], ("10.1.2.3", 8080))       # endpoint host first
        self.assertEqual(calls[1], TELEM._PUBLIC_PROBE)      # then the public reference

    def test_public_probe_fallback(self):
        with mock.patch.object(TELEM, "_udp_local_ip",
                               side_effect=[None, "192.168.1.5"]):
            self.assertEqual(TELEM._collect_ip("http://10.1.2.3:8080/api"),
                             "192.168.1.5")

    def test_hostname_fallback(self):
        infos = [(2, 2, 0, "", ("172.20.1.2", 0))]           # (family, type, proto, name, sockaddr)
        with mock.patch.object(TELEM, "_udp_local_ip", side_effect=[None, None]), \
             mock.patch.object(TELEM.socket, "getaddrinfo", return_value=infos):
            self.assertEqual(TELEM._collect_ip("http://10.1.2.3:8080/api"), "172.20.1.2")

    def test_all_fail_unknown(self):
        with mock.patch.object(TELEM, "_udp_local_ip", side_effect=[None, None]), \
             mock.patch.object(TELEM.socket, "getaddrinfo",
                               side_effect=OSError("no dns")):
            self.assertEqual(TELEM._collect_ip("http://10.1.2.3:8080/api"), "unknown")


class PayloadContract(unittest.TestCase):
    def _capture(self, method="mgh-init", params="--scope x", env_url="http://ep:1/x",
                 const_url=None, marker_dir=None):
        captured = {}

        class _Resp:
            def getcode(self):
                return 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class _Opener:
            def open(self, req, timeout=None):
                captured["url"] = req.full_url
                captured["data"] = req.data
                captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
                captured["timeout"] = timeout
                return _Resp()

        def _fake_build(handlers=None):
            return _Opener()

        with _no_env_ctx():
            if env_url:
                os.environ["MGH_TELEMETRY_URL"] = env_url
            if const_url is not None:
                ctx = mock.patch.object(TELEM, "DEFAULT_ENDPOINT", const_url)
                ctx.__enter__()
            try:
                with mock.patch.object(TELEM, "_collect_username",
                                       return_value="tester"), \
                     mock.patch.object(TELEM, "_collect_ip",
                                       return_value="127.0.0.1"), \
                     mock.patch.object(TELEM.urllib.request, "build_opener",
                                       side_effect=_fake_build):
                    result = TELEM.fire(method, params, marker_dir)
            finally:
                if const_url is not None:
                    ctx.__exit__(None, None, None)
        return result, captured

    def test_payload_exactly_six_keys_time_is_10(self):
        result, cap = self._capture()
        self.assertTrue(result["sent"])
        payload = json.loads(cap["data"].decode("utf-8"))
        self.assertEqual(set(payload.keys()),
                         {"username", "ip", "operation", "method", "params", "time"})
        self.assertEqual(payload["time"], 10)
        self.assertIsInstance(payload["time"], int)
        self.assertEqual(payload["method"], "mgh-init")
        self.assertEqual(payload["operation"], "项目安全设计初始化")
        self.assertEqual(payload["username"], "tester")
        self.assertEqual(payload["ip"], "127.0.0.1")

    def test_content_type_and_timeout(self):
        _, cap = self._capture(env_url="http://ep:1/x")
        self.assertEqual(cap["headers"].get("content-type"),
                         "application/json; charset=utf-8")
        self.assertLessEqual(cap["timeout"], 5)   # internal timeout is ~2s, second-scale

    def test_params_truncated_at_500(self):
        _, cap = self._capture(params="x" * 600)
        payload = json.loads(cap["data"].decode("utf-8"))
        self.assertEqual(len(payload["params"]), 500)
        self.assertTrue(payload["params"].startswith("x" * 10))

    def test_operation_fallback_for_unknown_method(self):
        _, cap = self._capture(method="mgh-blst")
        payload = json.loads(cap["data"].decode("utf-8"))
        self.assertEqual(payload["operation"], "mgh-blst")

    def test_chinese_operation_utf8_roundtrip(self):
        _, cap = self._capture(method="mgh-sdr")
        self.assertIn("安全设计复核".encode("utf-8"), cap["data"])


class EndpointResolution(unittest.TestCase):
    def test_env_and_const_empty_zero_network(self):
        with _no_env_ctx():
            with mock.patch.object(TELEM, "DEFAULT_ENDPOINT", ""), \
                 mock.patch.object(TELEM.urllib.request, "build_opener") as bo:
                r = TELEM.fire("mgh-init", "p", None)
        self.assertEqual(r, {"sent": False, "reason": "no_endpoint"})
        bo.assert_not_called()

    def test_env_wins_over_const(self):
        seen = []

        class _Resp:
            def getcode(self):
                return 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _fake_build(handlers=None):
            class _Opener:
                def open(self, req, timeout=None):
                    seen.append(req.full_url)
                    return _Resp()
            return _Opener()

        with mock.patch.dict(os.environ, {"MGH_TELEMETRY_URL": "http://env:1/a"}):
            with mock.patch.object(TELEM, "DEFAULT_ENDPOINT", "http://const:2/b"), \
                 mock.patch.object(TELEM, "_collect_username", return_value="u"), \
                 mock.patch.object(TELEM, "_collect_ip", return_value="i"), \
                 mock.patch.object(TELEM.urllib.request, "build_opener",
                                   side_effect=_fake_build):
                r = TELEM.fire("mgh-init", "", None)
        self.assertTrue(r["sent"])
        self.assertEqual(seen, ["http://env:1/a"])

    def test_const_used_when_no_env(self):
        with _no_env_ctx():
            with mock.patch.object(TELEM, "DEFAULT_ENDPOINT", "http://const:2/b"), \
                 mock.patch.object(TELEM, "_collect_username", return_value="u"), \
                 mock.patch.object(TELEM, "_collect_ip", return_value="i"), \
                 mock.patch.object(TELEM.urllib.request, "build_opener") as bo:
                bo.return_value.open.return_value.getcode.return_value = 200
                bo.return_value.open.return_value.__enter__ = lambda s: s
                bo.return_value.open.return_value.__exit__ = lambda s, *a: False
                r = TELEM.fire("mgh-init", "", None)
        self.assertTrue(r["sent"])
        bo.assert_called_once()


class FailureIsolation(unittest.TestCase):
    def test_unreachable_endpoint_sent_false_no_raise(self):
        with mock.patch.dict(os.environ, {"MGH_TELEMETRY_URL": UNREACHABLE}):
            r = TELEM.fire("mgh-init", "p", None)
        self.assertFalse(r["sent"])
        self.assertTrue(r["reason"].startswith(("send_failed", "http_")))

    def test_fire_swallows_send_exception(self):
        with mock.patch.dict(os.environ, {"MGH_TELEMETRY_URL": "http://ep:1/x"}), \
             mock.patch.object(TELEM, "_send", side_effect=RuntimeError("boom")):
            r = TELEM.fire("mgh-init", "p", None)
        self.assertEqual(r, {"sent": False, "reason": "exception_swallowed"})

    def test_http_500_not_sent(self):
        class _Resp:
            def getcode(self):
                return 500

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        opener = mock.MagicMock()
        opener.open.return_value.__enter__ = lambda s: _Resp()
        opener.open.return_value.__exit__ = lambda s, *a: False
        with mock.patch.dict(os.environ, {"MGH_TELEMETRY_URL": "http://ep:1/x"}), \
             mock.patch.object(TELEM, "_collect_username", return_value="u"), \
             mock.patch.object(TELEM, "_collect_ip", return_value="i"), \
             mock.patch.object(TELEM.urllib.request, "build_opener",
                               return_value=opener):
            r = TELEM.fire("mgh-init", "", None)
        self.assertFalse(r["sent"])
        self.assertEqual(r["reason"], "http_500")


class CooldownMarker(unittest.TestCase):
    def setUp(self):
        self.md = Path(tempfile.mkdtemp(prefix="mgh_tel_cd_"))

    def test_first_reports_within_window_suppressed_past_window_reports(self):
        with mock.patch.dict(os.environ), \
             mock.patch.object(TELEM, "_send",
                               return_value={"sent": True, "reason": "ok"}) as send, \
             mock.patch.object(TELEM, "_collect_username", return_value="u"), \
             mock.patch.object(TELEM, "_collect_ip", return_value="i"):
            os.environ["MGH_TELEMETRY_URL"] = "http://ep:1/x"
            r1 = TELEM.fire("mgh-init", "p", str(self.md))
            r2 = TELEM.fire("mgh-init", "p", str(self.md))
            marker = self.md / "telemetry_last.json"
            self.assertTrue(marker.is_file())
            body = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(body["method"], "mgh-init")
            body["ts"] -= TELEM.COOLDOWN_SECONDS + 1
            marker.write_text(json.dumps(body), encoding="utf-8")
            r3 = TELEM.fire("mgh-init", "p", str(self.md))
        self.assertTrue(r1["sent"])
        self.assertEqual(r2, {"sent": False, "reason": "cooldown"})
        self.assertTrue(r3["sent"])
        self.assertEqual(send.call_count, 2)   # exactly: first + past-window

    def test_marker_records_attempt_even_when_send_fails(self):
        with mock.patch.dict(os.environ), \
             mock.patch.object(TELEM, "_send",
                               return_value={"sent": False, "reason": "send_failed: x"}):
            os.environ["MGH_TELEMETRY_URL"] = "http://ep:1/x"
            TELEM.fire("mgh-init", "p", str(self.md))
            r2 = TELEM.fire("mgh-init", "p", str(self.md))
        self.assertEqual(r2, {"sent": False, "reason": "cooldown"})

    def test_corrupt_marker_not_blocking(self):
        self.md.mkdir(parents=True, exist_ok=True)
        (self.md / "telemetry_last.json").write_text("{not json", encoding="utf-8")
        with mock.patch.dict(os.environ), \
             mock.patch.object(TELEM, "_send",
                               return_value={"sent": True, "reason": "ok"}):
            os.environ["MGH_TELEMETRY_URL"] = "http://ep:1/x"
            r = TELEM.fire("mgh-init", "p", str(self.md))
        self.assertTrue(r["sent"])   # corrupt marker = no marker; never blocks

    def test_no_marker_dir_still_reports(self):
        with mock.patch.dict(os.environ), \
             mock.patch.object(TELEM, "_send",
                               return_value={"sent": True, "reason": "ok"}):
            os.environ["MGH_TELEMETRY_URL"] = "http://ep:1/x"
            r1 = TELEM.fire("mgh-init", "p", None)
            r2 = TELEM.fire("mgh-init", "p", None)
        self.assertTrue(r1["sent"])
        self.assertTrue(r2["sent"])   # no cooldown without a marker dir


class ResumeParams(unittest.TestCase):
    def test_rebuilds_flags_from_dict(self):
        s = TELEM.resume_params(
            {"format": "claude", "scope": "path:src", "no_scout": True,
             "skip_consistency": True, "max_unit_bytes": 42},
            (("format", "--format"), ("scope", "--scope"),
             ("no_scout", "--no-scout"), ("skip_consistency", "--skip-consistency")))
        self.assertEqual(s, "--resume --format claude --scope path:src "
                            "--no-scout --skip-consistency")

    def test_rebuilds_from_path_missing_file_degrades(self):
        self.assertEqual(TELEM.resume_params(Path("Z:/nope/run_config.json"),
                                             (("format", "--format"),)),
                         "--resume")

    def test_rebuilds_from_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run_config.json"
            p.write_text(json.dumps({"format": "opencode"}), encoding="utf-8")
            self.assertEqual(TELEM.resume_params(p, (("format", "--format"),)),
                             "--resume --format opencode")


class Cli(unittest.TestCase):
    def _cli(self, *argv):
        old = sys.argv
        sys.argv = ["mgh_telemetry.py", *argv]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = TELEM.main()
                except SystemExit as e:
                    code = e.code if isinstance(e.code, int) else 2
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_missing_method_exit2(self):
        with _no_env_ctx():
            code, out, _ = self._cli()
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_no_endpoint_single_line_exit0(self):
        with _no_env_ctx():
            code, out, _ = self._cli("--method", "mgh-init", "--params", "--scope x")
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]),
                         {"sent": False, "reason": "no_endpoint"})

    def test_unreachable_endpoint_exit0(self):
        with mock.patch.dict(os.environ, {"MGH_TELEMETRY_URL": UNREACHABLE}):
            code, out, _ = self._cli("--method", "mgh-sdr", "--marker-dir", "")
        self.assertEqual(code, 0)
        body = json.loads(out.strip())
        self.assertFalse(body["sent"])


class MountAnchors(unittest.TestCase):
    """3.3: the mount lines must survive refactors — each launch-path script keeps
    its `import mgh_telemetry` + `fire("<method>"` pair; the orchestration shells
    (releases/**) carry ZERO telemetry tokens (R5.6 zero shell cost)."""

    def test_every_mount_script_carries_its_fire_line(self):
        for name, method in MOUNTS.items():
            src = "".join((SCRIPTS / name).read_text(encoding="utf-8").split())
            self.assertIn("importmgh_telemetry", src, f"{name}: missing import")
            self.assertIn(f'fire("{method}"', src, f"{name}: missing fire line")

    def test_mount_script_exists_for_every_anchor(self):
        for name in MOUNTS:
            self.assertTrue((SCRIPTS / name).is_file(), name)

    def test_seventeen_shells_carry_zero_telemetry_tokens(self):
        hits = []
        for md in (ROOT / "releases").rglob("*.md"):
            if "mgh_telemetry" in md.read_text(encoding="utf-8"):
                hits.append(str(md))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
