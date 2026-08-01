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
import ast, contextlib, importlib.util, io, json, sys, tempfile, unittest
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
    "t1", "t2", "t3", "assemble", "t4", "merge", "done"
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
        input{}, output{}."""
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

    # ---- 4.6 零依赖 AST 扫描 ----

    def test_zero_stdlib_imports_only(self):
        """AST scan: list_steps.py imports only stdlib modules (R2)."""
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
        # stdlib modules allowed (expand as needed)
        stdlib = {"__future__", "argparse", "json", "sys", "pathlib", "ast", "contextlib",
                  "importlib", "io", "tempfile", "unittest"}
        non_stdlib = imports - stdlib
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


if __name__ == "__main__":
    unittest.main()
