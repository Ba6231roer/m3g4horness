#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_steps.py (D4 cross-script consistency + D2 prefix derivation).

Asserts:
  - Host prefix derivation: script_abs = Path(core/scripts).resolve() / <name>.py
  - Step id set consistency with resume_state.py
  - Pre-run queryable (no .mgh-init/ required)
  - --step single-step filtering + closed-set validation
  - stdout/stderr separation + JSON parseability
  - Zero dependency AST scan (stdlib only)
"""
import ast, contextlib, importlib.util, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Step enum from resume_state.py (D4 consistency guard)
# not-started|discover|survey|scout|resolve|t1|t2|t3|assemble|t4|merge|done
_RESUME_STATE_STEPS = {
    "not-started", "discover", "survey", "scout", "resolve",
    "t1", "t2", "t3", "assemble", "t4", "done"
}


class TestListSteps(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_steps")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_ls_"))

    def _run(self, *args):
        argv = ["list_steps.py"] + list(args) + ["--target", str(self.d)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _json(self, out):
        """Parse stdout as JSON; assert parseability."""
        try:
            return json.loads(out)
        except ValueError as e:
            self.fail(f"stdout not valid JSON: {e}")

    # ---- 4.1 前缀派生 ----

    def test_prefix_derivation_dev_location(self):
        """At dev location (core/scripts/list_steps.py), script_abs points to
        core/scripts/<name>.py (absolute, same-family)."""
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        data = self._json(out)
        scripts_dir = SCRIPTS.resolve()
        for step in data["steps"]:
            if step["script_abs"] is None:  # subagent steps
                continue
            # Verify script_abs is absolute
            self.assertTrue(Path(step["script_abs"]).is_absolute(),
                           f"step {step['step']}: script_abs not absolute")
            # Verify script_abs points into core/scripts/
            self.assertIn("core/scripts", step["script_abs"].replace("\\", "/"),
                         f"step {step['step']}: script_abs not in core/scripts")
            # Verify the sibling script actually exists (防幽灵脚本)
            script_name = step["script"]
            if script_name:
                self.assertTrue((scripts_dir / script_name).is_file(),
                               f"step {step['step']}: {script_name} not found in core/scripts")

    # ---- 4.2 step id 一致性 (D4) ----

    def test_step_id_set_matches_resume_state(self):
        """list_steps step id set == resume_state.py step enum (or documented superset)."""
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        data = self._json(out)
        list_steps_ids = {s["step"] for s in data["steps"]}
        # All resume_state steps must be present
        self.assertTrue(_RESUME_STATE_STEPS.issubset(list_steps_ids),
                       f"list_steps missing steps from resume_state: "
                       f"{_RESUME_STATE_STEPS - list_steps_ids}")

    # ---- 4.3 pre-run 可查 (D3) ----

    def test_pre_run_queryable_empty_dir(self):
        """In empty temp dir (no .mgh-init/), script exits 0 with full manifest."""
        # self.d is already an empty temp dir
        code, out, err = self._run()
        self.assertEqual(code, 0, "should exit 0 in empty dir")
        data = self._json(out)
        self.assertGreater(len(data["steps"]), 0, "should emit steps")
        self.assertIn("[list_steps]", err, "stderr should carry progress")

    # ---- 4.4 --step 单步 + 闭集 ----

    def test_step_single_step(self):
        """--step t1 returns only t1."""
        code, out, err = self._run("--step", "t1")
        self.assertEqual(code, 0)
        data = self._json(out)
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["step"], "t1")
        self.assertIn("[list_steps] emitting single step: t1", err)

    def test_step_unknown_step_exit_2(self):
        """--step bogus → exit 2 + stderr with known list."""
        code, out, err = self._run("--step", "bogus")
        self.assertEqual(code, 2, "should exit 2 for unknown step")
        self.assertIn("unknown step id", err)
        self.assertIn("bogus", err)
        # stderr should list known steps
        self.assertIn("known:", err)

    def test_step_numeric_exit_2_with_hint(self):
        """--step 0 (numeric index) → exit 2 + stderr with known list AND
        actionable hint (named enums; numeric indices NOT accepted); stdout has
        no partial manifest (exit-2 path must not emit JSON)."""
        code, out, err = self._run("--step", "0")
        self.assertEqual(code, 2, "should exit 2 for numeric --step id")
        self.assertIn("unknown step id", err)
        self.assertIn("known:", err)
        # Actionable hint: named enums + how to get them + numeric rejection
        self.assertIn("NAMED enums", err)
        self.assertIn("numeric indices are NOT accepted", err)
        # stdout must carry no partial manifest (not mixed into JSON surface)
        self.assertEqual(out.strip(), "", "exit-2 numeric id must not emit manifest on stdout")

    def test_default_emits_all_steps(self):
        """Default (no --step) emits all steps."""
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        data = self._json(out)
        self.assertGreater(len(data["steps"]), 10)  # 12 steps in our table
        # Verify we have the expected steps
        steps = {s["step"] for s in data["steps"]}
        self.assertIn("discover", steps)
        self.assertIn("t1", steps)
        self.assertIn("done", steps)

    # ---- 4.5 stdout/stderr 分流 + JSON 合法 ----

    def test_stdout_parseable_json(self):
        """stdout can be json.loads; stderr does not mix into stdout."""
        code, out, err = self._run()
        self.assertEqual(code, 0)
        # stdout should be parseable JSON
        data = self._json(out)
        self.assertIn("steps", data)
        # stderr should carry diagnostic messages (not JSON)
        self.assertIn("[list_steps]", err)
        # stdout should NOT contain stderr lines (no [list_steps] in JSON)
        self.assertNotIn("[list_steps]", out)

    def test_all_steps_json_structure(self):
        """Each step has required fields: step, kind, script, script_abs, invocation,
        input{}, output{}, discipline{}."""
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        data = self._json(out)
        for step in data["steps"]:
            self.assertIn("step", step)
            self.assertIn("kind", step)
            self.assertIn("script", step)
            self.assertIn("script_abs", step)
            self.assertIn("invocation", step)
            self.assertIn("input", step)
            self.assertIn("output", step)
            # kind is either bash or subagent
            self.assertIn(step["kind"], ("bash", "subagent"))
            # per-step discipline subset {gates, path_recipes, nevers} always present
            self.assertIn("discipline", step)
            self.assertIn("gates", step["discipline"])
            self.assertIn("path_recipes", step["discipline"])
            self.assertIn("nevers", step["discipline"])

    def test_step_discipline_matches_resume_state(self):
        """list_steps --step <id> discipline == resume_state.py discipline_reminders[]
        for the same step (single source of truth, D1; D5 consistency guard)."""
        rs = _load("resume_state")
        for step_id in ("t1", "scout", "t3", "discover", "done", "not-started"):
            code, out, _ = self._run("--step", step_id)
            self.assertEqual(code, 0, f"step {step_id}: exit != 0")
            data = self._json(out)
            self.assertEqual(len(data["steps"]), 1)
            got = data["steps"][0]["discipline"]
            self.assertEqual(got, rs.get_discipline(step_id),
                             f"step {step_id}: discipline differs from resume_state")

    def test_get_discipline_returns_defensive_deep_copy(self):
        """get_discipline returns a defensive DEEP copy: a consumer mutating the returned
        subset (append to gates/path_recipes/nevers) must NOT pollute the module-level
        shared table — before the fix one append permanently changed every later call's
        output (known steps returned the table entry itself; unknown steps returned
        dict(_EMPTY), whose nested lists are shared references too)."""
        d = _load("discipline_core")
        steps = ("t1", "t2", "scout", "t3", "done")
        pristine = {s: d.get_discipline(s) for s in steps}
        sdr_pristine = d.get_discipline("t1", domain="sdr")
        polluted = d.get_discipline("t1")
        polluted["gates"].append("POLLUTED")
        polluted["path_recipes"].append("POLLUTED")
        polluted["nevers"].append("POLLUTED")
        for s, want in pristine.items():
            self.assertEqual(d.get_discipline(s), want,
                             f"shared discipline table polluted at step {s}")
        self.assertEqual(d.get_discipline("t1", domain="sdr"), sdr_pristine)
        # the unknown-step / unknown-domain dict(_EMPTY) shallow-copy form is closed too
        empty = d.get_discipline("done")
        empty["nevers"].append("POLLUTED")
        self.assertEqual(d.get_discipline("done")["nevers"], [])
        self.assertEqual(d.get_discipline("no-such-step")["nevers"], [])
        self.assertEqual(d.get_discipline("t1", domain="no-such-domain")["nevers"], [])
        # the module-level table constants are untouched
        self.assertNotIn("POLLUTED", d._DISCIPLINE["t1"]["gates"])
        self.assertNotIn("POLLUTED", d._DISCIPLINE["done"]["nevers"])

    # ---- 4.6 零依赖 AST 扫描 ----

    def test_zero_stdlib_imports_only(self):
        """AST scan: list_steps.py imports only stdlib or a same-dir sibling (R2).
        Sibling allowance mirrors test_zero_deps.py — list_steps imports the shared
        static discipline table `discipline_core` (no third-party import)."""
        source = (SCRIPTS / "list_steps.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        # stdlib modules allowed (expand as needed) + same-dir sibling scripts
        stdlib = {"__future__", "argparse", "json", "sys", "pathlib", "ast", "contextlib",
                  "importlib", "io", "tempfile", "unittest"}
        allowed = stdlib | {p.stem for p in SCRIPTS.glob("*.py")}
        non_stdlib = imports - allowed
        self.assertEqual(non_stdlib, set(),
                       f"non-stdlib imports found: {non_stdlib}")

    # ---- 4.7 existing tests don't degrade ----

    def test_deterministic_tests_pass(self):
        """Verify test_deterministic.py can still import and run (smoke check)."""
        # Just ensure list_steps doesn't break the zero-deps invariant
        # that test_deterministic checks via AST scanning.
        test_path = HERE / "test_deterministic.py"
        if test_path.is_file():
            spec = importlib.util.spec_from_file_location("test_deterministic", test_path)
            mod = importlib.util.module_from_spec(spec)
            # Don't exec_module (runs unittest), just load without errors
            spec.loader.exec_module(mod)


    # ---- Step→IO contract-table sync (fix-mgh-init-resume-state-machine) ----

    def test_step_manifest_contract_table_sync(self):
        """core/contracts/init/step-manifest.md's Step→IO table stays in lockstep
        with list_steps.py's static step table: every tabulated step's kind +
        script must equal the stdout fields (the fan-out dispatch steps scout/t1/
        t2/t3 record fanout_runner.py — dispatcher-first; the table had drifted
        to the enumerator scripts for ~7 weeks across 4 architecture evolutions)."""
        import re
        contract = (HERE.parent / "core" / "contracts" / "init"
                    / "step-manifest.md").read_text(encoding="utf-8")
        rows = {}
        for line in contract.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 3:
                continue
            m = re.match(r"`([a-z][a-z0-9-]*)`$", cells[0])
            if not m:
                continue
            rows[m.group(1)] = (cells[1], cells[2])
        self.assertIn("t1", rows)  # parser sanity: the table was actually parsed
        code, out, _ = self._run()
        self.assertEqual(code, 0)
        impl = {s["step"]: s for s in self._json(out)["steps"]}
        for step_id, (kind_cell, script_cell) in sorted(rows.items()):
            self.assertIn(step_id, impl,
                          f"contract row {step_id}: absent from list_steps stdout")
            self.assertEqual(impl[step_id]["kind"], kind_cell,
                             f"step {step_id}: kind drift contract={kind_cell!r} "
                             f"impl={impl[step_id]['kind']!r}")
            want_script = None if script_cell in ("—", "-") else script_cell.strip("`")
            self.assertEqual(impl[step_id]["script"], want_script,
                             f"step {step_id}: script drift contract={script_cell!r} "
                             f"impl={impl[step_id]['script']!r}")



    def test_no_merge_step_row(self):
        # H11(b): the merge step (merge_inventories.py dead reference) is gone —
        # --merge is refused at step 0, never routed.
        src = (HERE.parent / "core" / "scripts" / "list_steps.py").read_text(
            encoding="utf-8")
        self.assertNotIn("merge_inventories", src)
        out = json.loads(self._steps()[-1]) if False else None


class NativeScoutBranchTest(unittest.TestCase):
    """fix-mgh-init-native-scout-dispatch: the env profile decides the scout
    step's face (consumer=init). Missing/auto profile on the opencode face =
    the native materializer entry + `native_arc` + the top-level `dispatch`
    field (host default); explicit runner = the established subprocess manifest
    byte-identical (no `dispatch`, no `native_arc`); claude/other faces stay
    subprocess; a resolved native on a non-opencode face fails loud (exit 2 +
    recipe, NEVER silently subprocess); missing scout native assets fail loud
    too; the native discipline variant stays byte-verbatim equal to
    resume_state's reminders for the same step/form."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.target = self.tmp / "proj"
        self.target.mkdir()
        sys.path.insert(0, str(HERE))
        from _sdr_install_mirror import build_claude_mirror, build_opencode_mirror
        self._build_opencode = build_opencode_mirror
        self._build_claude = build_claude_mirror

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, script, *args):
        p = subprocess.run([sys.executable, str(script), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        return p.returncode, p.stdout, p.stderr

    def _profile(self, body):
        (self.target / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.target / ".mgh" / "env-profile.json").write_text(
            json.dumps(body), encoding="utf-8")

    def _scout(self, data):
        return [s for s in data["steps"] if s["step"] == "scout"][0]

    def _step(self, data, step_id):
        return [s for s in data["steps"] if s["step"] == step_id][0]

    # --- dev tree (`other` face): subprocess unchanged + fail-closed native ---
    def test_dev_tree_no_profile_stays_subprocess(self):
        code, out, err = self._run(SCRIPTS / "list_steps.py",
                                   "--target", str(self.target))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertNotIn("dispatch", d)
        scout = self._scout(d)
        self.assertEqual(scout["script"], "fanout_runner.py")
        self.assertNotIn("native_arc", scout)

    def test_dev_tree_explicit_runner_stays_subprocess(self):
        self._profile({"v": 1, "dispatch_mode": "runner"})
        code, out, err = self._run(SCRIPTS / "list_steps.py",
                                   "--target", str(self.target))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertNotIn("dispatch", d)
        self.assertEqual(self._scout(d)["script"], "fanout_runner.py")

    def test_native_on_non_opencode_face_fail_closed(self):
        # dev tree = `other` face; profile explicitly native → exit 2 + recipe
        self._profile({"v": 1, "dispatch_mode": "native"})
        code, out, err = self._run(SCRIPTS / "list_steps.py",
                                   "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("only on the opencode face", err)
        self.assertIn("dispatch_mode", err)

    def test_dev_tree_bad_profile_fail_closed(self):
        self._profile({"v": 1, "dispatch_mode": "bogus"})
        code, out, err = self._run(SCRIPTS / "list_steps.py",
                                   "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("env profile rejected", err)
        self.assertIn("recipe:", err)

    # --- opencode face mirror: native default ---
    def _mirror_script(self, **assets):
        return self._build_opencode(self.tmp / "mirror", **assets) / "list_steps.py"

    def test_opencode_no_profile_is_native_host_default(self):
        script = self._mirror_script()
        code, out, err = self._run(script, "--target", str(self.target),
                                   "--step", "scout")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["dispatch"]["form"], "native")
        self.assertEqual(d["dispatch"]["source"], "host-default")
        self.assertFalse(d["dispatch"]["profile_exists"])
        self.assertEqual(d["dispatch"]["host_face"], "opencode")
        self.assertEqual(d["dispatch"]["consumer"], "init")
        self.assertFalse(d["dispatch"]["plan_present"])
        self.assertEqual(d["dispatch"]["native_agent"], "init-scout-native")
        self.assertTrue(Path(d["dispatch"]["profile_path"]).is_absolute())
        self.assertTrue(Path(d["dispatch"]["discipline_fragment"]).is_absolute())
        # fix-mgh-init-native-aggregate-dispatch: the dispatch field also
        # carries the aggregate face (fragment + per-tier agents + per-tier
        # plan-presence corroboration)
        self.assertTrue(Path(d["dispatch"]["aggregate_fragment"]).is_absolute())
        self.assertEqual(d["dispatch"]["aggregate_agents"], {
            "t1": "init-induct-native", "t2": "init-synthesis-native",
            "t3": "init-rulewriter-native",
            "scout-merge": "init-scout-merge-native"})
        self.assertEqual(d["dispatch"]["aggregate_plan_present"],
                         {"t1": False, "t2": False, "t3": False,
                          "scout-merge": False})
        scout = self._scout(d)
        self.assertEqual(scout["script"], "emit_native_plan.py")
        self.assertTrue(scout["invocation"].startswith("py "))
        self.assertIn("--tier scout", scout["invocation"])
        self.assertIn("--scout-plan <init-dir>/scout_plan.json", scout["invocation"])
        self.assertIn("--profile <target>", scout["invocation"])
        self.assertNotIn("fanout_runner", scout["invocation"])
        self.assertEqual([p["phase"] for p in scout["native_arc"]],
                         ["materialize", "waves", "merge"])
        waves = scout["native_arc"][1]
        self.assertEqual(waves["kind"], "subagent")
        self.assertEqual(waves["agent"], "init-scout-native")
        self.assertEqual(waves["discipline_fragment"],
                         d["dispatch"]["discipline_fragment"])
        # the scout-merge map companion switches to the materializer in the
        # native face (channel B/A per the aggregate fragment)
        self.assertEqual(len(scout["extra_invocations"]), 1)
        self.assertEqual(scout["extra_invocations"][0]["script"],
                         "emit_native_plan.py")
        self.assertIn("--tier scout-merge",
                      scout["extra_invocations"][0]["invocation"])
        # the aggregate steps (t1/t2/t3) switch to their native faces too
        # (second call: the first was --step scout, single-step mode)
        code_f, out_f, err_f = self._run(script, "--target", str(self.target))
        self.assertEqual(code_f, 0, err_f)
        d = json.loads(out_f)
        t1 = self._step(d, "t1")
        self.assertEqual(t1["script"], "emit_native_plan.py")
        self.assertIn("--tier t1", t1["invocation"])
        self.assertIn("native_plan_t1.json", t1["output"]["path_pattern"])
        self.assertEqual([p["phase"] for p in t1["native_arc"]],
                         ["materialize", "dispatch", "gate"])
        self.assertEqual(t1["native_arc"][1]["agent"], "init-induct-native")
        self.assertEqual(t1["native_arc"][1]["tool"], "mgh_dispatch")
        t2 = self._step(d, "t2")
        self.assertEqual([p["phase"] for p in t2["native_arc"]],
                         ["gate", "materialize", "dispatch", "rollup"])
        self.assertIn("plan_aggregate.py", t2["native_arc"][0]["invocation"])
        t3 = self._step(d, "t3")
        self.assertEqual([p["phase"] for p in t3["native_arc"]],
                         ["materialize", "dispatch", "gate"])
        self.assertEqual(t3["native_arc"][1]["agent"], "init-rulewriter-native")
        # the native discipline variant rides the step
        text = json.dumps(scout["discipline"], ensure_ascii=False)
        for needle in ("init-native-wave", "emit_native_plan.py", "--retry-failed",
                       "同一条 assistant 消息", "唯一写者是子代理自身", "units_total"):
            self.assertIn(needle, text, needle)
        for step_id in ("t1", "t2", "t3"):
            dtext = json.dumps(self._step(d, step_id)["discipline"],
                               ensure_ascii=False)
            for needle in ("mgh_dispatch", "init-aggregate-native-dispatch",
                           "units_total"):
                self.assertIn(needle, dtext, f"{step_id}: {needle}")

    def test_opencode_auto_profile_is_native(self):
        self._profile({"v": 1, "dispatch_mode": "auto"})
        script = self._mirror_script()
        code, out, err = self._run(script, "--target", str(self.target))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["dispatch"]["form"], "native")
        self.assertEqual(d["dispatch"]["source"], "host-default")
        self.assertTrue(d["dispatch"]["profile_exists"])

    def test_opencode_explicit_runner_falls_back_byte_identical(self):
        # explicit runner on the opencode mirror must be the PRE-change
        # subprocess manifest, path-normalized: after replacing each install
        # tree's scripts dir with a placeholder, the mirror's runner stdout and
        # the dev tree's (unchanged runner face) are byte-identical — no
        # dispatch, no native_arc, subprocess discipline.
        script = self._mirror_script()
        code_p, out_p, err_p = self._run(script, "--target", str(self.target))
        self._profile({"v": 1, "dispatch_mode": "runner"})
        code_r, out_r, err_r = self._run(script, "--target", str(self.target))
        self.assertEqual(code_r, 0, err_r)
        code_d, out_d, err_d = self._run(SCRIPTS / "list_steps.py",
                                         "--target", str(self.target))
        self.assertEqual(code_d, 0, err_d)
        # stdout is JSON: backslashes are escaped, so normalize the ESCAPED form
        esc = lambda s: str(s).replace("\\", "\\\\")
        mirror_norm = out_r.replace(esc(script.parent), "<scripts>")
        dev_norm = out_d.replace(esc(SCRIPTS), "<scripts>")
        self.assertEqual(mirror_norm, dev_norm)
        d = json.loads(out_r)
        self.assertNotIn("dispatch", d)
        scout = self._scout(d)
        self.assertEqual(scout["script"], "fanout_runner.py")
        self.assertNotIn("native_arc", scout)
        self.assertEqual(scout["discipline"]["path_recipes"][0]["id"],
                         "scout-fanout-dispatcher")

    def test_opencode_plan_artifact_corroboration(self):
        script = self._mirror_script()
        (self.target / ".mgh-init").mkdir()
        (self.target / ".mgh-init" / "native_plan.json").write_text(
            "{}", encoding="utf-8")
        code, out, err = self._run(script, "--target", str(self.target),
                                   "--step", "scout")
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["dispatch"]["plan_present"])

    def test_missing_init_agent_fails_loud(self):
        script = self._mirror_script(init_agent=False)
        code, out, err = self._run(script, "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("init-scout-native.md", err)
        self.assertIn("install.sh --opencode", err)
        self.assertIn("dispatch_mode", err)

    def test_missing_init_fragment_fails_loud(self):
        script = self._mirror_script(init_fragment=False)
        code, out, err = self._run(script, "--target", str(self.target),
                                   "--step", "scout")
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("init-scout-native-dispatch.md", err)

    def test_explicit_runner_skips_the_asset_gate(self):
        # runner form does not need the native assets at all — a stripped
        # install tree must still emit the subprocess manifest.
        self._profile({"v": 1, "dispatch_mode": "runner"})
        script = self._mirror_script(init_agent=False, init_fragment=False)
        code, out, err = self._run(script, "--target", str(self.target))
        self.assertEqual(code, 0, err)
        self.assertNotIn("dispatch", json.loads(out))

    def test_claude_face_stays_subprocess_face(self):
        script = self._build_claude(self.tmp / "claude-mirror") / "list_steps.py"
        code, out, err = self._run(script, "--target", str(self.target))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertNotIn("dispatch", d)
        scout = self._scout(d)
        self.assertEqual(scout["script"], "fanout_runner.py")
        self.assertNotIn("native_arc", scout)

    def test_claude_face_explicit_native_fail_closed(self):
        script = self._build_claude(self.tmp / "claude-mirror") / "list_steps.py"
        self._profile({"v": 1, "dispatch_mode": "native"})
        code, out, err = self._run(script, "--target", str(self.target))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("only on the opencode face", err)

    def test_native_discipline_verbatim_equals_resume_native_reminders(self):
        # one static table, two consumers — the native form must hold the same
        # byte-verbatim equality the subprocess form asserts.
        script = self._mirror_script()
        init_dir = self.target / ".mgh-init"
        init_dir.mkdir()
        (init_dir / "run_config.json").write_text(
            json.dumps({"target": str(self.target), "format": "opencode"}),
            encoding="utf-8")
        (init_dir / "controls_candidates.json").write_text(
            json.dumps({"candidates": [], "source": "regex"}), encoding="utf-8")
        (init_dir / "clusters.json").write_text(
            json.dumps({"repo": str(self.target), "clusters": [],
                        "truncated": False}), encoding="utf-8")
        (init_dir / "scout_plan.json").write_text(
            json.dumps({"batches": [{"batch_id": "b1"}, {"batch_id": "b2"}]}),
            encoding="utf-8")
        p = subprocess.run([sys.executable, str(script.parent / "resume_state.py"),
                            "--target", str(self.target)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(p.returncode, 0, p.stderr)
        state = json.loads(p.stdout)
        self.assertEqual(state["step"], "scout")
        self.assertEqual(state["dispatch"]["form"], "native")
        code, out, err = self._run(script, "--target", str(self.target),
                                   "--step", "scout")
        self.assertEqual(code, 0, err)
        listed = json.loads(out)["steps"][0]["discipline"]
        self.assertEqual(listed, state["discipline_reminders"])


if __name__ == "__main__":
    unittest.main()
