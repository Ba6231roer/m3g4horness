#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for fanout_runner.py liveness + --kill-stale + stderr heartbeat
(improve-mgh-init-fanout-lifecycle).

Covers: liveness write/delete (clean exit removes, hard-kill residual detectable,
children[] wave refresh), --kill-stale both forms (runner-alive tree kill /
runner-dead recorded-children kill), idempotence (second call killed:[]),
PID-reuse misfire guard (cmdline mismatch -> remove file only, never kill),
dry-run guard (bare real kill with targets -> exit 2 + recipe), heartbeat line
format (stderr line parse), stdout contract (exactly one JSON line, last).

All subprocess interactions are faked at the module-function boundary
(_pid_alive / _pid_cmdline / _kill_tree monkeypatched) — no real process kills
in tests. The liveness write path and CLI dispatch run for real.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
SCRIPT = SCRIPTS / "fanout_runner.py"


def _load():
    spec = importlib.util.spec_from_file_location("fanout_runner_stale_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FR = _load()


class _Env:
    """Synthetic <repo>/.mgh-init layout + in-process main() runner."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_stale_"))
        self.repo = self.tmp / "repo"
        self.init = self.repo / ".mgh-init"
        (self.init / "checkpoints" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "inputs" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "scout_plan.json").write_text("{}", encoding="utf-8")

    def liveness_path(self, tier="scout") -> Path:
        return self.init / f"fanout_runner.{tier}.pid"

    def liveness(self, tier="scout", pid=None, children=None, host="opencode"):
        body = {
            "pid": pid if pid is not None else os.getpid(),
            "started_ts": "2026-09-01T00:00:00+08:00",
            "tier": tier,
            "host": host,
            "cmdline": ["py", f"fanout_runner.py", "--tier", tier],
            "children": children or [],
        }
        p = self.liveness_path(tier)
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def main(self, *extra, argv_extra=None):
        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout")] \
            + list(extra)
        if argv_extra:
            argv += argv_extra
        if "--cooldown-s" not in argv:
            # Same harness default as _FakeDispatchBase in test_fanout_runner.py:
            # this file's subjects are liveness/--kill-stale, never the storm
            # cooldown, so the layer stays OFF (a wall-clock cooldown here would
            # be a real wait the assertions do not measure).
            argv += ["--cooldown-s", "0"]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = FR.main()
        except SystemExit as e:  # subprocess-level exits surface as SystemExit in-process
            code = e.code if isinstance(e.code, int) else 1
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def cleanup(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestLivenessFile(unittest.TestCase):
    """Liveness write on dispatch start, delete on ANY exit path, children[]
    refresh — the spec's form-1/2 prerequisite."""

    def setUp(self):
        self.env = _Env()

    def tearDown(self):
        self.env.cleanup()

    def test_liveness_written_then_removed_on_clean_exit(self):
        # dispatch via the --pending-file test hook (empty pending; no list-CLI
        # invocation) — exercises the full main() try/finally liveness cycle.
        lp = self.env.tmp / "pending.json"
        lp.write_text(json.dumps({"repo": str(self.env.repo), "total": 0,
                                  "done": 0, "failed": 0, "pending": []}),
                      encoding="utf-8")
        code, out, err = self.env.main("--pending-file", str(lp))
        self.assertEqual(code, 0, err)
        # the file is removed by try/finally on the clean path
        residuals = FR._stale_liveness_files(self.env.init)
        self.assertEqual(residuals, [], f"clean exit must remove liveness; got {residuals}")

    def test_liveness_present_during_dispatch_and_carries_pid(self):
        # A crash-exit path (sys.exit from the list invocation inside the
        # try block) must STILL remove the file via finally — assert removal,
        # then separately assert the write shape by calling _write_liveness.
        lp = FR._write_liveness(self.env.init, "scout", "opencode")
        self.assertTrue(lp.is_file())
        body = json.loads(lp.read_text(encoding="utf-8"))
        self.assertEqual(body["pid"], os.getpid())
        self.assertEqual(body["tier"], "scout")
        self.assertEqual(body["host"], "opencode")
        self.assertIsInstance(body["cmdline"], list)
        self.assertEqual(body["children"], [])
        # hard-kill simulation: the process dies without finally -> file stays
        # (residual = legal state; --kill-stale disambiguates)

    def test_children_refresh_wave_cycle(self):
        lp = FR._write_liveness(self.env.init, "scout", "test")
        body = json.loads(lp.read_text(encoding="utf-8"))
        FR._update_liveness_children(lp, body,
                                     [{"pid": 111, "unit": "scout-001", "tier": "scout"}])
        after = json.loads(lp.read_text(encoding="utf-8"))
        self.assertEqual(after["children"],
                         [{"pid": 111, "unit": "scout-001", "tier": "scout"}])
        # started_ts/cmdline stable across the refresh (single body reused)
        self.assertEqual(after["started_ts"], body["started_ts"])
        # wave end clears children
        FR._update_liveness_children(lp, after, [])
        self.assertEqual(json.loads(lp.read_text(encoding="utf-8"))["children"], [])

    def test_children_registered_at_spawn_removed_at_terminal(self):
        # slot-backfill refresh timing: children[] registers a child AT SPAWN
        # (on_spawn fires with the Popen pid inside _run_unit) and removes it at
        # that unit's terminal event — the registry reflects the true in-flight
        # set at any instant. _run_unit is faked; it calls on_spawn and probes
        # the liveness file at each spawn.
        units = []
        for i in (1, 2):
            cp = self.env.init / "checkpoints" / "scout" / f"scout-{i:03d}.json"
            units.append({
                "batch_id": f"scout-{i:03d}",
                "input_path": str(self.env.init / "inputs" / "scout" / f"u{i}.md"),
                "checkpoint_path": str(cp),
                "done_marker": str(Path(str(cp) + ".done")),
                "failed_marker": str(Path(str(cp) + ".failed")),
                "slice_dir": str(self.env.init / "slices"),
            })
            Path(units[-1]["input_path"]).write_text("{}", encoding="utf-8")
            # NO markers ever written: the fake _run_unit returns ok without
            # touching disk (a real subagent would write the marker), so the
            # disk-derived stub keeps listing both units pending — the drain
            # re-list (breaker observation point b) counts two zero-growth
            # re-lists and trips: exit 2, stalled. Assertions below cover the
            # children[] timing on BOTH dispatch rounds plus liveness cleanup
            # on the stalled exit path (finally runs regardless).
        stub = self.env.tmp / "stub_disk_enum.py"
        body = f"""
import json, sys
from pathlib import Path
UNITS = json.loads({json.dumps(units)!r})
pending = [u for u in UNITS if not Path(u['done_marker']).is_file()]
print(json.dumps({{'repo': {str(self.env.repo)!r}, 'total': len(UNITS),
                   'done': len(UNITS) - len(pending), 'failed': 0,
                   'pending': pending}}))
"""
        stub.write_text(body, encoding="utf-8")
        lp = self.env.liveness_path()
        snapshots = []

        def fake_run(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                     run_log_path=None, uid="", on_spawn=None):
            pid = 700000 + len(snapshots) + 1
            if on_spawn is not None:
                on_spawn(pid)
                # AT SPAWN: this unit's pid is registered...
                children = json.loads(lp.read_text(encoding="utf-8"))["children"]
                # ...and (wave=1) the PREVIOUS unit's entry is already gone
                # (removed at its terminal event).
                snapshots.append([dict(c) for c in children])
            return ("spawn-ok", "ok", "ok", pid, False)

        saved = FR._run_unit
        FR._run_unit = fake_run
        saved_list = dict(FR.TIERS["scout"])
        FR.TIERS["scout"]["list_script"] = str(stub)
        try:
            code, out, err = self.env.main("--host", "claude", "--wave", "1")
        finally:
            FR._run_unit = saved
            FR.TIERS["scout"].update(saved_list)
        self.assertEqual(code, 2, err)
        self.assertIn("stalled", out)
        self.assertIn("STALLED", err)
        # breaker trip = 2 dispatch rounds x 2 units (drain re-list counted
        # two zero-growth re-derivations; --stall-waves default 2)
        self.assertEqual(len(snapshots), 4, "two rounds, both units re-dispatched")
        self.assertEqual([c[0]["pid"] for c in snapshots],
                         [700000 + i for i in range(1, 5)],
                         "at each spawn the registry holds exactly the new child")
        self.assertTrue(all(len(c) == 1 for c in snapshots),
                        "previous unit's entry removed at its terminal")
        # stalled exit still removes the liveness file (try/finally)
        self.assertFalse(lp.exists())

    def test_liveness_not_a_lock_two_writes_coexist(self):
        # liveness semantics, not mutex: two tiers' files coexist without error
        FR._write_liveness(self.env.init, "scout", "opencode")
        FR._write_liveness(self.env.init, "t1", "opencode")
        self.assertEqual(len(FR._stale_liveness_files(self.env.init)), 2)


def _patch_probe(case, alive_map, cmdline_map, killed):
    """Monkeypatch the OS boundary: alive_map/cmdline_map pid->bool/str;
    killed collects killed pids."""

    def fake_alive(pid):
        return bool(alive_map.get(pid, False))

    def fake_cmdline(pid):
        return cmdline_map.get(pid, "")

    def fake_kill(pid):
        killed.append(pid)
        return True

    for name, fn in (("_pid_alive", fake_alive), ("_pid_cmdline", fake_cmdline),
                     ("_kill_tree", fake_kill)):
        case.subTest(name=name)
        setattr(FR, name, fn)
    return killed


class TestKillStale(unittest.TestCase):
    """--kill-stale both forms, PID-reuse guard, dry-run guard, idempotence."""

    def setUp(self):
        self.env = _Env()
        self._saved = {n: getattr(FR, n)
                       for n in ("_pid_alive", "_pid_cmdline", "_kill_tree")}

    def tearDown(self):
        for n, fn in self._saved.items():
            setattr(FR, n, fn)
        self.env.cleanup()

    def _run_kill_stale(self, *extra):
        return self.env.main("--kill-stale", *extra)

    def test_form1_runner_alive_and_matching_killed(self):
        self.env.liveness(pid=4242)
        killed = _patch_probe(self, {4242: True}, {4242: "py fanout_runner.py --tier t1"}, [])
        code, out, err = self._run_kill_stale("--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["kill_stale"]["killed"],
                         [{"pid": 4242, "tier": "scout", "kind": "runner"}])
        self.assertEqual(killed, [], "dry-run must not kill")
        # review marker written by dry-run; real kill now succeeds
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        body = json.loads(out)["kill_stale"]
        self.assertEqual(body["killed"], [{"pid": 4242, "tier": "scout", "kind": "runner"}])
        self.assertEqual(killed, [4242])
        self.assertFalse(self.env.liveness_path().exists(), "liveness removed after kill")

    def test_form2_runner_dead_children_alive_killed(self):
        # runner PID dead; children[] records two PIDs, one is the host CLI
        self.env.liveness(pid=999, children=[
            {"pid": 5001, "unit": "scout-001", "tier": "scout"},
            {"pid": 5002, "unit": "scout-002", "tier": "scout"}])
        killed = _patch_probe(
            self, {999: False, 5001: True, 5002: True},
            {5001: r"C:\Program Files\nodejs\opencode.cmd run --agent x",
             5002: "notepad.exe"}, [])
        code, out, _ = self._run_kill_stale("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kill_stale"]["killed"],
                         [{"pid": 5001, "tier": "scout", "kind": "child"}])
        self._run_kill_stale()
        self.assertEqual(killed, [5001], "only the host-CLI child is killed")
        self.assertFalse(self.env.liveness_path().exists())

    def test_pid_reuse_guard_no_kill_on_mismatch(self):
        # runner PID reused by an unrelated process -> never killed, file still
        # removed (stale-record cleanup is not destructive)
        self.env.liveness(pid=4242, children=[
            {"pid": 5001, "unit": "u", "tier": "scout"}])
        killed = _patch_probe(self, {4242: True, 5001: True},
                              {4242: "chrome.exe --flag", 5001: "chrome.exe"}, [])
        code, out, _ = self._run_kill_stale("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kill_stale"]["killed"], [])
        self._run_kill_stale()
        self.assertEqual(killed, [], "cmdline-mismatch PIDs are NEVER killed")
        self.assertFalse(self.env.liveness_path().exists())

    def test_dry_run_guard_bare_real_kill_with_targets_exit_2(self):
        self.env.liveness(pid=4242)
        _patch_probe(self, {4242: True}, {4242: "py fanout_runner.py --tier t1"}, [])
        code, out, err = self._run_kill_stale()  # no prior dry-run
        self.assertEqual(code, 2, "real kill without review must fail loud")
        self.assertIn("dry-run", err)
        self.assertIn("recipe", err.lower())
        self.assertEqual(json.loads(out)["kill_stale"]["killed"], [])
        # a dead-PID residual (no kill targets) needs NO prior review
        self.env.cleanup()
        self.env = _Env()
        self.env.liveness(pid=999)
        _patch_probe(self, {999: False}, {}, [])
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kill_stale"]["removed"],
                         [str(self.env.liveness_path())])

    def test_idempotent_no_stale_empty_then_second_call_killed_empty(self):
        # no residual files at all -> none:true, exit 0
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        body = json.loads(out)["kill_stale"]
        self.assertEqual(body, {"killed": [], "removed": [], "none": True})
        # second call identical (idempotent)
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kill_stale"]["none"], True)

    def test_idempotent_second_call_after_kill_empty(self):
        self.env.liveness(pid=4242)
        _patch_probe(self, {4242: True}, {4242: "py fanout_runner.py"}, [])
        self._run_kill_stale("--dry-run")
        code, out, _ = self._run_kill_stale()
        self.assertEqual(json.loads(out)["kill_stale"]["killed"][0]["pid"], 4242)
        # second call: file gone -> killed:[] (never re-kills)
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kill_stale"]["killed"], [])

    def test_tier_agnostic_glob_covers_all_tiers(self):
        # mechanism depends only on the file-name convention
        self.env.liveness(tier="t3", pid=111)
        self.env.liveness(tier="future-tier", pid=222)
        _patch_probe(self, {111: True, 222: True},
                     {111: "fanout_runner.py", 222: "fanout_runner.py"}, [])
        code, out, _ = self._run_kill_stale("--dry-run")
        self.assertEqual(code, 0)
        kinds = {(k["pid"], k["tier"], k["kind"])
                 for k in json.loads(out)["kill_stale"]["killed"]}
        self.assertEqual(kinds, {(111, "t3", "runner"), (222, "future-tier", "runner")})

    def test_unparsable_residual_never_a_target(self):
        p = self.env.init / "fanout_runner.scout.pid"
        p.write_text("not json", encoding="utf-8")
        killed = _patch_probe(self, {}, {}, [])
        code, out, _ = self._run_kill_stale()
        self.assertEqual(code, 0)
        body = json.loads(out)["kill_stale"]
        self.assertEqual(body["killed"], [])
        self.assertEqual(killed, [])
        self.assertEqual(body["removed"], [str(p)])


class TestHeartbeatAndStdoutContract(unittest.TestCase):
    """stderr heartbeat line format + stdout single-JSON-line contract."""

    def setUp(self):
        self.env = _Env()

    def tearDown(self):
        self.env.cleanup()

    def test_heartbeat_lines_parse_and_carry_fields(self):
        # empty pending -> wave loop never runs; use a listing with one unit
        # (test hook = no spawn, but heartbeat helper is directly asserted too)
        hb = FR._hb
        buf = io.StringIO()
        t0 = FR.time.monotonic() - 3723.5  # ~+01:02:03
        with contextlib.redirect_stderr(buf):
            hb(t0, "t1", 3, "clst-aa", "ok", 45, 830)
        line = buf.getvalue().strip()
        self.assertRegex(
            line,
            r"^\[fanout_runner t1\] \+\d{2}:\d{2}:\d{2} wave=3 unit=clst-aa ok "
            r"done=45/830$")
        self.assertIn("+01:02:03", line)

    def test_heartbeat_on_dispatch_path(self):
        # path-drift unit -> failed heartbeat line reaches stderr via the loop
        units = [{
            "batch_id": "drift-1",
            "input_path": "D:/out-of-tree/input.json",
            "checkpoint_path": "D:/out-of-tree/cp.json",
            "done_marker": "D:/out-of-tree/cp.json.done",
            "failed_marker": str(self.env.init / "checkpoints" / "scout" / "drift-1.json.failed"),
            "slice_dir": "D:/out-of-tree/slice",
        }]
        lp = self.env.tmp / "pending.json"
        lp.write_text(json.dumps({"repo": str(self.env.repo), "total": 1,
                                  "done": 0, "failed": 0, "pending": units}),
                      encoding="utf-8")
        code, out, err = self.env.main("--pending-file", str(lp))
        self.assertEqual(code, 0)
        hb_lines = [ln for ln in err.splitlines()
                    if ln.startswith("[fanout_runner scout] +")]
        self.assertTrue(hb_lines, "heartbeat lines must reach stderr")
        for ln in hb_lines:
            # slot-backfill loop: wave= = the unit's dispatch ordinal; events
            # are per-unit spawn/terminal only (no wave-end — no wave barrier)
            self.assertRegex(
                ln,
                r"^\[fanout_runner scout\] \+\d{2}:\d{2}:\d{2} wave=\d+ "
                r"unit=\S+ (spawn|ok|failed|timeout|crash|stall) done=\d+/\d+$")
        self.assertTrue(any(" failed " in ln for ln in hb_lines))
        self.assertFalse(any(" wave-end " in ln for ln in hb_lines),
                         "wave barrier removed -> no wave-end lines")

    def test_inflight_heartbeat_line_format(self):
        # periodic in-flight disclosure (--hb-interval-s): unit id + idle
        # seconds since its child's last output — the "slow vs hung" signal —
        # plus the silence window THIS unit is judged against. The window is
        # part of the line because it is adaptive: the same `idle=300s` means
        # "kill is imminent" under a 900s window and "nothing to see" under
        # 1800s, so idle alone would be unreadable.
        buf = io.StringIO()
        t0 = FR.time.monotonic() - 125.0
        with contextlib.redirect_stderr(buf):
            FR._hb_inflight(t0, "t1", 2, "clst-aa", 300, 45, 830, 1800)
        line = buf.getvalue().strip()
        self.assertRegex(
            line,
            r"^\[fanout_runner t1\] \+\d{2}:\d{2}:\d{2} inflight=2 unit=clst-aa "
            r"idle=300s stall_window=1800s done=45/830$")

    def test_inflight_heartbeat_discloses_disabled_window_as_off(self):
        # --stall-timeout-s 0: there is no window at all, so the line must NOT
        # print `stall_window=0s` (which reads as "kills at zero seconds").
        buf = io.StringIO()
        t0 = FR.time.monotonic() - 125.0
        with contextlib.redirect_stderr(buf):
            FR._hb_inflight(t0, "t1", 1, "clst-bb", 4000, 1, 2, 0)
        self.assertIn("stall_window=off", buf.getvalue())

    def test_stdout_exactly_one_json_line_last(self):
        lp = self.env.tmp / "pending.json"
        lp.write_text(json.dumps({"repo": str(self.env.repo), "total": 0,
                                  "done": 0, "failed": 0, "pending": []}),
                      encoding="utf-8")
        code, out, err = self.env.main("--pending-file", str(lp))
        self.assertEqual(code, 0)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, "stdout = exactly one line (JSON summary)")
        summary = json.loads(lines[0])  # last line IS the whole stdout
        self.assertEqual(summary["runner"], "fanout_runner")
        for k in ("tier", "repo", "host", "total", "done", "failed", "pending",
                  "wave", "waves_run", "partial"):
            self.assertIn(k, summary)


if __name__ == "__main__":
    unittest.main(verbosity=2)
