#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""emit_native_plan.py unit tests.

Covers: byte-identical re-materialization (plan + task files, no timestamps,
stable canonical-id sort); short-id stability across subsets + anti-miscopy
(conflict sets constructed by search resolve via deterministic salting, pairwise
edit distance >= 2 always); anchor-tree rejection of out-of-tree units with
zero partial writes; wave-size arithmetic incl. the source field (concurrency
vs quota, CLI override); zero dispatch side effects (only the enumerator
subprocess, no markers / cred / childcfg / host spawn); --check red/green
(clean pass, tampered plan, tampered/missing task file, stale plan after a unit
completes, distance-1 id tampering); sdr + scout tier smokes; a REAL end-to-end
sdr run against a scratch git repo (true enumerator subprocess, byte-stable,
--check green).

Run: py tests/test_emit_native_plan.py
"""
import contextlib
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "emit_native_plan.py"

SDR_UIDS = [
    "iface::com.example.AlphaController#getUser",
    "iface::com.example.BetaController#postOrder",
    "standalone::docs/readme.txt",
]


def _load():
    spec = importlib.util.spec_from_file_location("emit_native_plan", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_conflict_pair(m):
    """Search synthetic unit ids until two salt-0 short bodies collide outright
    or sit at edit distance 1 (position-masked birthday search, O(n))."""
    bodies, masked = {}, {}
    i = 0
    while True:
        uid = f"conf-unit-{i:06d}"
        body = m._short_body(uid, 0)
        if body in bodies:
            return bodies[body], uid
        for pos in range(len(body)):
            key = (pos, body[:pos] + body[pos + 1:])
            if key in masked:
                return masked[key], uid
            masked[key] = uid
        bodies[body] = uid
        i += 1


class EmitNativePlanTest(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.fr = self.m.fr
        self._orig_list_pending = self.fr._list_pending
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_enp_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run = self.repo / "run"
        self.ck = self.run / "checkpoints"
        self.inputs = self.run / "inputs"
        self.run.mkdir(parents=True)
        (self.run / "grouping.json").write_text('{"v": 1}\n', encoding="utf-8")

    def tearDown(self):
        self.fr._list_pending = self._orig_list_pending
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- fixture helpers -------------------------------------------------
    def _sdr_unit(self, uid):
        s = self.fr._safe_name(uid)
        return {"unit_id": uid, "kind": "interface", "route": "GET /x",
                "input_path": str(self.inputs / f"{s}.json"),
                "draft_path": str(self.run / "drafts" / f"{s}.json"),
                "done_marker": str(self.ck / f"{s}.done"),
                "failed_marker": str(self.ck / f"{s}.failed"),
                "baseline_path": str(self.run / "baseline.json"),
                "external_dir": ""}

    def _sdr_listing(self, uids):
        pend = [self._sdr_unit(u) for u in uids]
        return {"repo": str(self.repo), "base": "master", "branch": "feat",
                "empty": False, "total": len(pend), "done": 0, "failed": 0,
                "counts": {"interface": len(pend)}, "pending": pend,
                "offset": 0, "limit": 100}

    def _install_listing(self, listing_or_fn):
        fn = listing_or_fn if callable(listing_or_fn) \
            else (lambda tier, args: listing_or_fn)
        self.fr._list_pending = fn

    def _template(self):
        t = self.tmp / "mini-sdr-task.md"
        t.write_text(
            "unit {{unit_id}} kind {{kind}} route {{route}}\n"
            "repo {{repo}} codegraph {{codegraph}}\n"
            "input {{input_path}} draft {{draft_path}}\n"
            "done {{done_marker}} failed {{failed_marker}}\n"
            "baseline {{baseline_path}} external {{external_dir}}\n",
            encoding="utf-8")
        return t

    def _emit(self, *extra, uids=SDR_UIDS, tier="sdr"):
        """Default sdr emit with the mini template and a patched listing.
        Pass uids=None when the test installed its own listing."""
        if uids is not None and tier == "sdr":
            self._install_listing(self._sdr_listing(uids))
        argv = ["emit_native_plan.py", "--tier", tier,
                "--repo", str(self.repo), "--base", "master", "--branch",
                "feat", "--checkpoints", str(self.ck), "--inputs-dir",
                str(self.inputs), "--template", str(self._template())]
        return self._run_argv(argv + list(extra))

    def _run_argv(self, argv):
        sys.argv = list(argv)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def _plan_path(self):
        return self.run / "native_plan.json"

    def _plan(self):
        return json.loads(self._plan_path().read_text(encoding="utf-8"))

    def _task_files(self):
        return sorted(self.inputs.glob("*.task.md"))

    # --- 1. determinism / byte round-trip --------------------------------
    def test_two_emits_byte_identical(self):
        c1, o1, e1 = self._emit()
        self.assertEqual(c1, 0, e1)
        plan1 = self._plan_path().read_bytes()
        tasks1 = {f.name: f.read_bytes() for f in self._task_files()}
        c2, _, e2 = self._emit()
        self.assertEqual(c2, 0, e2)
        self.assertEqual(self._plan_path().read_bytes(), plan1)
        self.assertEqual({f.name: f.read_bytes() for f in self._task_files()},
                         tasks1)

    def test_plan_shape_and_fixed_serialization(self):
        code, out, err = self._emit()
        self.assertEqual(code, 0, err)
        raw = self._plan_path().read_text(encoding="utf-8")
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(raw, json.dumps(self._plan(), ensure_ascii=False,
                                         indent=2, sort_keys=True) + "\n")
        body = self._plan()
        self.assertEqual(set(body.keys()),
                         {"v", "tier", "agent", "repo", "wave_size",
                          "wave_size_source", "units_total", "waves"})
        self.assertEqual(body["tier"], "sdr")
        self.assertEqual(body["agent"], "sdr-review-fanout")
        self.assertEqual(body["units_total"], len(SDR_UIDS))
        self.assertNotIn("time", raw.lower())
        self.assertNotIn("date", raw.lower())

    def test_units_sorted_by_canonical_id(self):
        shuffled = list(reversed(SDR_UIDS)) + ["aaa::first"]
        code, out, err = self._emit(uids=shuffled)
        self.assertEqual(code, 0, err)
        plan_ids = [u["unit_id"] for w in self._plan()["waves"]
                    for u in w["units"]]
        self.assertEqual(plan_ids, sorted(shuffled))
        # a second emit fed a DIFFERENT pending order yields identical bytes
        first = self._plan_path().read_bytes()
        code, _, err = self._emit(uids=list(reversed(shuffled)))
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan_path().read_bytes(), first)

    def test_task_files_match_audit_copy_layout(self):
        code, out, err = self._emit()
        self.assertEqual(code, 0, err)
        for unit in [u for w in self._plan()["waves"] for u in w["units"]]:
            tf = Path(unit["task_file"])
            self.assertTrue(tf.is_absolute())
            self.assertEqual(tf, self.inputs / tf.name)
            self.assertEqual(tf.name,
                             f"{self.fr._safe_name(unit['unit_id'])}.task.md")
            text = tf.read_text(encoding="utf-8")
            self.assertNotIn("{{", text)
            self.assertIn(unit["unit_id"], text)

    def test_unit_entries_carry_enumerator_fields_verbatim(self):
        code, _, err = self._emit()
        self.assertEqual(code, 0, err)
        units = {u["unit_id"]: u for w in self._plan()["waves"]
                 for u in w["units"]}
        src = {u["unit_id"]: u for u in self._sdr_listing(SDR_UIDS)["pending"]}
        for uid, entry in units.items():
            for k, v in src[uid].items():
                self.assertEqual(entry[k], v, f"{uid}.{k} not verbatim")

    def test_stdout_summary_single_line(self):
        code, out, err = self._emit()
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("\n"), 1)
        d = json.loads(out)
        for key in ("tool", "tier", "agent", "units_total", "waves",
                    "wave_size", "wave_size_source", "plan_path", "inputs_dir"):
            self.assertIn(key, d)
        self.assertEqual(d["units_total"], len(SDR_UIDS))
        self.assertEqual(Path(d["plan_path"]), self._plan_path())
        self.assertTrue(Path(d["inputs_dir"]).is_absolute())

    # --- 2. short ids -----------------------------------------------------
    def test_short_id_shape_and_charset(self):
        code, _, err = self._emit()
        self.assertEqual(code, 0, err)
        rx = re.compile(r"^sdr-[a-hj-kmnp-z2-7]{4}$")
        ids = [u["id"] for w in self._plan()["waves"] for u in w["units"]]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, rx)

    def test_short_ids_stable_across_subsets(self):
        code, _, err = self._emit()
        self.assertEqual(code, 0, err)
        full = {u["unit_id"]: u["id"] for w in self._plan()["waves"]
                for u in w["units"]}
        # one unit completes -> pending shrinks -> remaining ids unchanged
        code, _, err = self._emit(uids=SDR_UIDS[1:])
        self.assertEqual(code, 0, err)
        shrunk = {u["unit_id"]: u["id"] for w in self._plan()["waves"]
                  for u in w["units"]}
        for uid, sid in shrunk.items():
            self.assertEqual(full[uid], sid, f"short id drifted for {uid}")

    def test_conflicting_set_resolves_with_distance_two(self):
        a, b = _find_conflict_pair(self.m)
        self.assertNotEqual(a, b)
        code, _, err = self._emit(uids=[a, b])
        self.assertEqual(code, 0, err)
        ids = {u["unit_id"]: u["id"] for w in self._plan()["waves"]
               for u in w["units"]}
        bodies = [v.split("-", 1)[1] for v in ids.values()]
        for x in bodies:
            for y in bodies:
                if x != y:
                    self.assertGreaterEqual(self.m._edit_distance(x, y), 2)
        # deterministic: re-materialize in reverse order, same assignment
        plan1 = self._plan_path().read_bytes()
        code, _, err = self._emit(uids=[b, a])
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan_path().read_bytes(), plan1)

    def test_assign_function_direct(self):
        one = self.m._assign_short_ids("sdr", ["single-unit"])
        self.assertEqual(one["single-unit"],
                         "sdr-" + self.m._short_body("single-unit", 0))
        a, b = _find_conflict_pair(self.m)
        two = self.m._assign_short_ids("sdr", sorted([a, b]))
        self.assertGreaterEqual(
            self.m._edit_distance(two[a].split("-", 1)[1],
                                  two[b].split("-", 1)[1]), 2)

    # --- 3. anchor tree / fail-loud ---------------------------------------
    def test_out_of_tree_unit_rejected_with_zero_writes(self):
        self._template()                       # create BEFORE the snapshot
        before = sorted(str(p) for p in self.tmp.rglob("*"))
        bad = self._sdr_listing(SDR_UIDS)
        bad["pending"][0]["input_path"] = str(self.tmp / "outside" / "x.json")
        self._install_listing(bad)
        code, _, err = self._emit(uids=None)
        self.assertEqual(code, 2)
        self.assertIn("path-drift", err)
        after = sorted(str(p) for p in self.tmp.rglob("*"))
        self.assertEqual(before, after, "partial write leaked on failure")

    def test_missing_tier_flag_exit2(self):
        self._install_listing(self._sdr_listing(SDR_UIDS))
        code, _, err = self._run_argv(
            ["emit_native_plan.py", "--tier", "sdr",
             "--checkpoints", str(self.ck), "--inputs-dir", str(self.inputs)])
        self.assertEqual(code, 2)
        self.assertIn("--repo", err)

    def test_plan_artifact_missing_exit1(self):
        (self.run / "grouping.json").unlink()
        self._install_listing(self._sdr_listing(SDR_UIDS))
        code, _, err = self._emit(uids=None)
        self.assertEqual(code, 1)
        self.assertIn("grouping.json", err)

    def test_template_residual_placeholder_exit1(self):
        t = self.tmp / "bad-template.md"
        t.write_text("unit {{unit_id}} mystery {{nope}}\n", encoding="utf-8")
        self._install_listing(self._sdr_listing(SDR_UIDS))
        code, _, err = self._run_argv(
            ["emit_native_plan.py", "--tier", "sdr", "--repo",
             str(self.repo), "--base", "master", "--branch", "feat",
             "--checkpoints", str(self.ck), "--inputs-dir", str(self.inputs),
             "--template", str(t)])
        self.assertEqual(code, 1)
        self.assertIn("placeholder", err)

    # --- 4. wave arithmetic ------------------------------------------------
    def _emit_with_profile(self, profile_body, *extra):
        proj = self.tmp / "proj"
        if profile_body is not None:
            (proj / ".mgh").mkdir(parents=True, exist_ok=True)
            (proj / ".mgh" / "env-profile.json").write_text(
                json.dumps(profile_body), encoding="utf-8")
        return self._emit("--profile", str(proj), *extra)

    def test_wave_default_concurrency_three(self):
        code, _, err = self._emit()
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 3)
        self.assertEqual(self._plan()["wave_size_source"], "concurrency")

    def test_wave_cli_override(self):
        code, _, err = self._emit("--wave-size", "5")
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 5)
        self.assertEqual(self._plan()["wave_size_source"], "concurrency")

    def test_wave_profile_concurrency(self):
        code, _, err = self._emit_with_profile({"native_concurrency": 4})
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 4)

    def test_wave_quota_100_over_10_concurrency3(self):
        code, _, err = self._emit_with_profile(
            {"native_concurrency": 3,
             "quota": {"calls": 100, "window_s": 600, "calls_per_unit": 10}})
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 3)
        self.assertEqual(self._plan()["wave_size_source"], "concurrency")

    def test_wave_quota_caps_concurrency5(self):
        code, _, err = self._emit_with_profile(
            {"native_concurrency": 5,
             "quota": {"calls": 30, "window_s": 600, "calls_per_unit": 10}})
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 3)
        self.assertEqual(self._plan()["wave_size_source"], "quota")

    def test_wave_cli_override_still_capped_by_quota(self):
        code, _, err = self._emit_with_profile(
            {"quota": {"calls": 30, "window_s": 600, "calls_per_unit": 10}},
            "--wave-size", "5")
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["wave_size"], 3)
        self.assertEqual(self._plan()["wave_size_source"], "quota")

    def test_wave_splitting_sizes(self):
        uids = [f"standalone::f{i}.txt" for i in range(7)]
        code, _, err = self._emit(uids=uids)
        self.assertEqual(code, 0, err)
        sizes = [len(w["units"]) for w in self._plan()["waves"]]
        self.assertEqual(sizes, [3, 3, 1])
        self.assertEqual([w["wave"] for w in self._plan()["waves"]],
                         [1, 2, 3])

    def test_bad_profile_fail_closed(self):
        proj = self.tmp / "proj2"
        (proj / ".mgh").mkdir(parents=True)
        (proj / ".mgh" / "env-profile.json").write_text("{bad", encoding="utf-8")
        code, _, err = self._emit("--profile", str(proj))
        self.assertEqual(code, 2)
        self.assertIn("env-profile", err)

    def test_zero_wave_size_rejected(self):
        code, _, err = self._emit("--wave-size", "0")
        self.assertEqual(code, 2)

    # --- 5. zero dispatch side effects -------------------------------------
    def test_no_dispatch_side_effects(self):
        self._template()                       # create BEFORE the snapshot
        before = {str(p) for p in self.tmp.rglob("*")}
        calls = []
        orig_run = subprocess.run

        def spy_run(*a, **kw):
            calls.append(a[0] if a else kw.get("args"))
            return orig_run(*a, **kw)

        subprocess.run = spy_run
        try:
            code, _, err = self._emit()
        finally:
            subprocess.run = orig_run
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, [], "host/other subprocess spawned")
        expected_new = {str(self._plan_path()), str(self.inputs)} | {
            str(p) for p in self._task_files()}
        after = {str(p) for p in self.tmp.rglob("*")}
        self.assertEqual(after - before, expected_new,
                         "unexpected files created (markers/childcfg/cred)")
        for p in after:
            name = Path(p).name
            self.assertFalse(name.endswith((".done", ".failed")),
                             f"marker written: {p}")
            self.assertFalse(name.startswith("fanout_progress"),
                             f"sidecar written: {p}")
            self.assertNotEqual(name, "cred.json", "credential write")

    def test_zero_unit_listing_produces_empty_plan(self):
        self._install_listing({"repo": str(self.repo), "base": "master",
                               "branch": "feat", "empty": True, "total": 0,
                               "done": 0, "failed": 0, "pending": []})
        code, out, err = self._emit(uids=None)
        self.assertEqual(code, 0, err)
        self.assertEqual(self._plan()["units_total"], 0)
        self.assertEqual(self._plan()["waves"], [])
        self.assertEqual(json.loads(out)["units_total"], 0)

    def test_needs_reduce_false_zero_unit_plan(self):
        init_dir = self.repo / "initdir"
        init_dir.mkdir()
        (init_dir / "run_config.json").write_text("{}", encoding="utf-8")
        self._install_listing({"node": "t2", "needs_reduce": False,
                               "shards": 0, "pending": []})
        code, out, err = self._run_argv(
            ["emit_native_plan.py", "--tier", "t2", "--init-dir",
             str(init_dir), "--checkpoints", str(self.ck), "--inputs-dir",
             str(self.inputs), "--template", str(self._template())])
        self.assertEqual(code, 0, err)
        plan = json.loads((init_dir / "native_plan.json").read_text(
            encoding="utf-8"))
        self.assertEqual(plan["units_total"], 0)

    # --- 6. --check red/green ----------------------------------------------
    def test_check_clean_plan_green(self):
        code, _, err = self._emit()
        self.assertEqual(code, 0, err)
        code, out, err = self._emit("--check")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["check"], "ok")
        self.assertEqual(d["units_total"], len(SDR_UIDS))

    def test_check_tampered_plan_red(self):
        self._emit()
        raw = self._plan_path().read_text(encoding="utf-8")
        self._plan_path().write_text(
            raw.replace('"wave_size": 3', '"wave_size": 4'), encoding="utf-8")
        code, out, err = self._emit("--check")
        self.assertEqual(code, 2)
        self.assertIn("native_plan.json", err)
        self.assertIn("recipe", err)

    def test_check_missing_task_file_red(self):
        self._emit()
        self._task_files()[0].unlink()
        code, _, err = self._emit("--check")
        self.assertEqual(code, 2)
        self.assertIn("task file missing", err)

    def test_check_drifted_task_file_red(self):
        self._emit()
        tf = self._task_files()[0]
        tf.write_text(tf.read_text(encoding="utf-8") + "\n# tampered\n",
                      encoding="utf-8")
        code, _, err = self._emit("--check")
        self.assertEqual(code, 2)
        self.assertIn("task file drifted", err)

    def test_check_stale_plan_after_completion_red(self):
        state = {"listing": self._sdr_listing(SDR_UIDS)}
        self._install_listing(state["listing"])
        code, _, err = self._emit(uids=None)
        self.assertEqual(code, 0, err)
        done = self.ck / f"{self.fr._safe_name(SDR_UIDS[0])}.done"
        done.parent.mkdir(parents=True, exist_ok=True)
        done.write_text("{}", encoding="utf-8")
        # the enumerator is marker-aware: the completed unit drops out of pending
        state["listing"] = self._sdr_listing(SDR_UIDS[1:])
        self._install_listing(state["listing"])
        code, _, err = self._emit("--check", uids=None)
        self.assertEqual(code, 2)
        self.assertIn("no longer pending", err)
        self.assertIn("stale", err.lower())

    def test_check_missing_plan_red(self):
        self._install_listing(self._sdr_listing(SDR_UIDS))
        code, _, err = self._emit("--check", uids=None)
        self.assertEqual(code, 2)
        self.assertIn("plan not found", err)

    def test_check_distance1_ids_flagged(self):
        self._emit()
        body = self._plan()
        units = [u for w in body["waves"] for u in w["units"]]
        u0, u1 = units[0], units[1]
        # tamper u1's id to sit at edit distance exactly 1 from u0's id
        b0 = u0["id"].split("-", 1)[1]
        new_last = "a" if b0[-1] != "a" else "b"
        u1["id"] = "sdr-" + b0[:-1] + new_last
        self.assertEqual(self.m._edit_distance(u0["id"], u1["id"]), 1)
        self._plan_path().write_text(
            json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n", encoding="utf-8")
        code, _, err = self._emit("--check", uids=None)
        self.assertEqual(code, 2)
        self.assertIn("edit distance", err)
        self.assertIn(u0["id"], err)
        self.assertIn(u1["id"], err)

    # --- 7. scout smoke + import robustness --------------------------------
    def _scout_listing(self, bids, total=None, done=0, failed=0):
        pend = []
        for i, bid in enumerate(bids):
            s = self.fr._safe_name(bid)
            pend.append({"batch_id": bid,
                         "input_path": str(self.inputs / f"{s}.json"),
                         "checkpoint_path": str(self.ck / f"{s}.json"),
                         "done_marker": str(self.ck / f"{s}.done"),
                         "failed_marker": str(self.ck / f"{s}.failed"),
                         "slice_dir": str(self.inputs / f"slice{i}")})
        return {"repo": str(self.repo), "total": len(pend) if total is None
                else total, "done": done, "failed": failed, "pending": pend}

    def _scout_argv(self, scout_plan, *extra):
        return (["emit_native_plan.py", "--tier", "scout", "--scout-plan",
                 str(scout_plan), "--checkpoints", str(self.ck),
                 "--inputs-dir", str(self.inputs)] + list(extra))

    def test_scout_tier_smoke(self):
        scout_plan = self.run / "scout_plan.json"
        scout_plan.write_text('{"v": 1}\n', encoding="utf-8")
        pend = []
        for i, bid in enumerate(("batch-001::src/main", "batch-002::src/test")):
            s = self.fr._safe_name(bid)
            pend.append({"batch_id": bid,
                         "input_path": str(self.inputs / f"{s}.json"),
                         "checkpoint_path": str(self.ck / f"{s}.json"),
                         "done_marker": str(self.ck / f"{s}.done"),
                         "failed_marker": str(self.ck / f"{s}.failed"),
                         "slice_dir": str(self.inputs / f"slice{i}")})
        self._install_listing({"repo": str(self.repo), "total": 2, "done": 0,
                               "failed": 0, "pending": pend})
        code, out, err = self._run_argv(
            ["emit_native_plan.py", "--tier", "scout", "--scout-plan",
             str(scout_plan), "--checkpoints", str(self.ck), "--inputs-dir",
             str(self.inputs)])
        self.assertEqual(code, 0, err)
        plan = self._plan()
        self.assertEqual(plan["agent"], "init-scout-fanout")
        self.assertEqual(plan["tier"], "scout")
        ids = [u["id"] for w in plan["waves"] for u in w["units"]]
        self.assertTrue(all(i.startswith("scout-") for i in ids))
        for unit in [u for w in plan["waves"] for u in w["units"]]:
            self.assertIn("checkpoint_path", unit)
            self.assertEqual(unit["unit_id"], unit["batch_id"])

    def test_scout_materialize_then_check_round_trip(self):
        # fix-mgh-init-native-scout-dispatch: the scout plan materializes and
        # the SAME-ARGS --check passes while nothing has moved (the wave loop's
        # "materialize → check" opening step).
        scout_plan = self.run / "scout_plan.json"
        scout_plan.write_text('{"v": 1}\n', encoding="utf-8")
        self._install_listing(self._scout_listing(
            ["batch-a", "batch-b", "batch-c"], total=7))
        code, out, err = self._run_argv(self._scout_argv(scout_plan))
        self.assertEqual(code, 0, err)
        code2, out2, err2 = self._run_argv(self._scout_argv(scout_plan,
                                                            "--check"))
        self.assertEqual(code2, 0, err2)
        summary = json.loads(out2)
        self.assertEqual(summary["check"], "ok")
        self.assertEqual(summary["units_total"], 3)

    def test_scout_page_units_total_is_page_size_not_total(self):
        # page semantics: the listing IS the current pending page (the
        # enumerator's budget already shrank it, here 81 of 400) — units_total
        # is the PAGE size, never the tier total.
        scout_plan = self.run / "scout_plan.json"
        scout_plan.write_text('{"v": 1}\n', encoding="utf-8")
        bids = [f"batch-{i:03d}" for i in range(81)]
        self._install_listing(self._scout_listing(bids, total=400))
        code, out, err = self._run_argv(self._scout_argv(scout_plan))
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["units_total"], 81)
        plan = self._plan()
        self.assertEqual(plan["units_total"], 81)
        self.assertEqual(len(plan["waves"]), 27)   # 81 / wave_size 3

    def test_scout_zero_pending_units_total_zero(self):
        # the page-loop termination shape: pending exhausted → units_total == 0,
        # zero task files, exit 0 (a clean empty page, never an error).
        scout_plan = self.run / "scout_plan.json"
        scout_plan.write_text('{"v": 1}\n', encoding="utf-8")
        self._install_listing(self._scout_listing([], total=400, done=400))
        code, out, err = self._run_argv(self._scout_argv(scout_plan))
        self.assertEqual(code, 0, err)
        summary = json.loads(out)
        self.assertEqual(summary["units_total"], 0)
        self.assertEqual(summary["waves"], 0)
        self.assertEqual(self._task_files(), [])

    def test_scout_check_flags_stale_plan_after_completion(self):
        # a completed unit makes the plan stale BY DESIGN (exit 2 + stale
        # report) — the wave loop repairs it by re-materializing, NEVER by
        # consuming the stale plan.
        scout_plan = self.run / "scout_plan.json"
        scout_plan.write_text('{"v": 1}\n', encoding="utf-8")
        bid = "batch-a"
        self._install_listing(self._scout_listing([bid, "batch-b"]))
        code, out, err = self._run_argv(self._scout_argv(scout_plan))
        self.assertEqual(code, 0, err)
        done_marker = self.ck / f"{self.fr._safe_name(bid)}.done"
        done_marker.parent.mkdir(parents=True, exist_ok=True)
        done_marker.write_text("", encoding="utf-8")
        # the enumerator now reports the completed unit as no longer pending
        self._install_listing(self._scout_listing(["batch-b"], total=2,
                                                  done=1))
        code2, out2, err2 = self._run_argv(self._scout_argv(scout_plan,
                                                            "--check"))
        self.assertEqual(code2, 2)
        self.assertIn("stale", err2)

    def test_help_surface(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0)
        for token in ("--tier", "scout", "scout-merge", "t1", "t2", "t3",
                      "sdr", "--scout-plan", "--clusters", "--candidates",
                      "--init-dir", "--inventory", "--rules-dir", "--target",
                      "--repo", "--base", "--branch", "--checkpoints",
                      "--inputs-dir", "--retry-failed", "--template",
                      "--wave-size", "--profile", "--check"):
            self.assertIn(token, r.stdout, f"--help missing {token!r}")

    def test_module_loads_from_foreign_cwd(self):
        r = subprocess.run(
            [sys.executable, "-c",
             f"import importlib.util as u; s=u.spec_from_file_location("
             f"'emit_native_plan', r'''{SCRIPT}'''); m=u.module_from_spec(s); "
             f"s.loader.exec_module(m); print(m.PLAN_NAME)"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(self.tmp))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("native_plan.json", r.stdout)


class EmitNativePlanRealGitTest(unittest.TestCase):
    """End-to-end sdr run: REAL diff_group enumerator subprocess on a scratch
    git repo. Anchors the 'enumerator is the only subprocess' claim and byte
    stability on the true production path (no _list_pending patching)."""

    @classmethod
    def setUpClass(cls):
        cls.m = _load()
        cls.fr = cls.m.fr
        cls.tmp = Path(tempfile.mkdtemp(prefix="mgh_enp_real_"))
        cls.repo = cls.tmp / "repo"
        (cls.repo / "src").mkdir(parents=True)
        cls._git("init", "-b", "master")
        (cls.repo / "src" / "a.txt").write_text("base\n", encoding="utf-8")
        cls._git("add", "-A")
        cls._git("commit", "-m", "base")
        cls._git("checkout", "-b", "feat")
        (cls.repo / "src" / "a.txt").write_text("base\nchanged\n",
                                                encoding="utf-8")
        (cls.repo / "src" / "b.txt").write_text("new file\n", encoding="utf-8")
        cls._git("add", "-A")
        cls._git("commit", "-m", "branch changes")
        cls.run_dir = cls.repo / "run"
        cls.ck = cls.run_dir / "checkpoints"
        cls.inputs = cls.run_dir / "inputs"
        cls.run_dir.mkdir(parents=True)
        (cls.run_dir / "grouping.json").write_text('{"v": 1}\n',
                                                   encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def _git(cls, *a):
        r = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-c", "user.email=t@t.io",
             "-c", "user.name=t", "-C", str(cls.repo), *a],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"git {a} failed: {r.stderr}"
        return r

    def _argv(self, *extra):
        return ["emit_native_plan.py", "--tier", "sdr", "--repo",
                str(self.repo), "--base", "master", "--branch", "",
                "--checkpoints", str(self.ck), "--inputs-dir",
                str(self.inputs)] + list(extra)

    def _run(self, argv):
        sys.argv = list(argv)
        out, err = io.StringIO(), io.StringIO()
        code = None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = self.m.main()
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_real_enumerator_end_to_end(self):
        enumerator_calls = []
        orig_run = subprocess.run
        real_python = sys.executable

        def spy_run(cmd, *a, **kw):
            if isinstance(cmd, list) and cmd and cmd[0] == real_python:
                enumerator_calls.append(cmd)
            return orig_run(cmd, *a, **kw)

        subprocess.run = spy_run
        try:
            code, out, err = self._run(self._argv())
        finally:
            subprocess.run = orig_run
        self.assertEqual(code, 0, err)
        self.assertTrue(enumerator_calls, "enumerator subprocess not observed")
        for cmd in enumerator_calls:
            self.assertEqual(Path(cmd[1]).name, "diff_group.py",
                             f"non-enumerator subprocess spawned: {cmd}")
        plan_path = self.run_dir / "native_plan.json"
        body = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(body["units_total"], 1)
        tasks = sorted(self.inputs.glob("*.task.md"))
        self.assertEqual(len(tasks), body["units_total"])
        first_bytes = plan_path.read_bytes()
        task_bytes = {f.name: f.read_bytes() for f in tasks}
        # second emit: byte-identical (idempotent, no timestamps)
        code, out2, err2 = self._run(self._argv())
        self.assertEqual(code, 0, err2)
        self.assertEqual(plan_path.read_bytes(), first_bytes)
        self.assertEqual({f.name: f.read_bytes()
                          for f in sorted(self.inputs.glob("*.task.md"))},
                         task_bytes)
        # --check green on the true path
        code, out3, err3 = self._run(self._argv("--check"))
        self.assertEqual(code, 0, err3)
        self.assertEqual(json.loads(out3)["check"], "ok")
        # tamper -> red
        plan_path.write_text(
            first_bytes.decode("utf-8").replace('"units_total"', '"units_tot"'),
            encoding="utf-8")
        code, _, err4 = self._run(self._argv("--check"))
        self.assertEqual(code, 2)
        self.assertIn("native_plan.json", err4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
