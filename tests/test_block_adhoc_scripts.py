#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""block_adhoc_scripts.py PreToolUse hook decision matrix (R5.7 deliverable, FD4).

Double-column assertions: PASS legitimate leaf-script invocations + whitelisted writes;
BLOCK py -c introspection + ad-hoc .py writes. Active only inside MGH_INIT_ACTIVE=1.
"""
import contextlib, importlib.util, io, json, os, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "releases" / "claude-code" / "hooks" / "block_adhoc_scripts.py"


def _load():
    spec = importlib.util.spec_from_file_location("block_adhoc_scripts", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBlockAdhocScripts(unittest.TestCase):
    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        old_env = os.environ.get("MGH_INIT_ACTIVE")
        os.environ["MGH_INIT_ACTIVE"] = active
        old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            if old_env is None:
                os.environ.pop("MGH_INIT_ACTIVE", None)
            else:
                os.environ["MGH_INIT_ACTIVE"] = old_env
        return code, err.getvalue()

    # --- PASS (legitimate) ---
    def test_inactive_passes_introspection_silently(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}}, active="")
        self.assertEqual(code, 0)

    def test_pass_legit_leaf_invocation(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": "py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init"}})
        self.assertEqual(code, 0)

    def test_pass_py_c_without_introspection(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {"command": 'py -c "print(1)"'}})
        self.assertEqual(code, 0)

    def test_pass_whitelisted_py_write(self):
        code, _ = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/discover_controls.py"}})
        self.assertEqual(code, 0)

    def test_pass_tests_py_write(self):
        code, _ = self._run({"tool_name": "Write", "tool_input": {"file_path": "tests/test_x.py"}})
        self.assertEqual(code, 0)

    # --- BLOCK (violations) ---
    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)  # recipe points at sanctioned primitive

    def test_block_python_c_variant(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'python -c "import json; json.load(open(\'x.json\'))"'}})
        self.assertEqual(code, 2)

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_prep_scout_batches.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_prep_scout_batches.py", err)


if __name__ == "__main__":
    unittest.main()
