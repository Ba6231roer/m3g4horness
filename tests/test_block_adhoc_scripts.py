#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""block_adhoc_scripts.py PreToolUse hook decision matrix (R5.7 deliverable, FD4).

Double-column assertions: PASS legitimate leaf-script invocations + whitelisted writes;
BLOCK py -c introspection + ad-hoc .py writes. Active only inside a mgh run-domain
(MGH_INIT_ACTIVE=1 for /mgh-init, MGH_SAST_ACTIVE=1 for /mgh-sast).
"""
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "releases" / "claude-code" / "hooks" / "block_adhoc_scripts.py"

_DOMAIN_ENV = {"init": "MGH_INIT_ACTIVE", "sast": "MGH_SAST_ACTIVE"}


def _load():
    spec = importlib.util.spec_from_file_location("block_adhoc_scripts", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(mod, payload, domain="init", active="1"):
    """Invoke mod.main() with the given run-domain env set; isolate the other mgh env
    so the test is deterministic. Returns (exit_code, stderr)."""
    key = _DOMAIN_ENV[domain]
    other = _DOMAIN_ENV["sast" if domain == "init" else "init"]
    old_val = os.environ.get(key)
    old_other = os.environ.pop(other, None)
    os.environ[key] = active
    old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.stdin = old_stdin
        if old_val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = old_val
        if old_other is not None:
            os.environ[other] = old_other
    return code, err.getvalue()


class TestBlockAdhocScriptsInit(unittest.TestCase):
    """/mgh-init run-domain (MGH_INIT_ACTIVE=1)."""

    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="init", active=active)

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

    # --- out-of-tree Write/Edit (subtree guard; MGH_TARGET set) ---
    def _run_with_target(self, payload, target):
        """Run the hook with MGH_TARGET set (init domain), restoring env after."""
        old = os.environ.get("MGH_TARGET")
        if target is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = target
        try:
            return self._run(payload)
        finally:
            if old is None:
                os.environ.pop("MGH_TARGET", None)
            else:
                os.environ["MGH_TARGET"] = old

    def test_pass_in_tree_rule_write(self):
        target = tempfile.mkdtemp(prefix="mgh_tgt_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/.claude/rules/security-x.md"}}, target)
        self.assertEqual(code, 0)

    def test_pass_in_tree_checkpoint_write(self):
        target = tempfile.mkdtemp(prefix="mgh_tgt_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/.mgh-init/checkpoints/scout/scout-001.json"}}, target)
        self.assertEqual(code, 0)

    def test_block_out_of_tree_drive_root(self):
        target = tempfile.mkdtemp(prefix="mgh_tgt_")
        code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, target)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)
        self.assertIn("checkpoint_path", err)  # recipe points at list_* stdout field

    def test_block_out_of_tree_other_dir(self):
        target = tempfile.mkdtemp(prefix="mgh_tgt_")
        other = tempfile.mkdtemp(prefix="mgh_other_")
        code, _ = self._run_with_target({"tool_name": "Edit", "tool_input": {
            "file_path": f"{other}/x.md"}}, target)
        self.assertEqual(code, 2)

    def test_subtree_guard_degrades_without_target(self):
        # MGH_TARGET missing -> the subtree check MUST pass (degrade, never block)
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, None)
        self.assertEqual(code, 0)


class TestBlockAdhocScriptsSast(unittest.TestCase):
    """/mgh-sast run-domain (MGH_SAST_ACTIVE=1) — mirror of the init column
    (harden-mgh-sast-orchestration-discipline FD4 / task 5.4)."""

    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="sast", active=active)

    # --- PASS (legitimate) ---
    def test_inactive_passes_introspection_silently(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}}, active="")
        self.assertEqual(code, 0)

    def test_pass_legit_leaf_invocation(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": "py .claude/mgh-core/scripts/prefilter.py --in checkpoints/s4_candidates.json --out checkpoints/s5_filtered.json"}})
        self.assertEqual(code, 0)

    def test_pass_list_chunks_invocation(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": "py .claude/mgh-core/scripts/list_chunks.py --chunks checkpoints/s3_chunks.json"}})
        self.assertEqual(code, 0)

    def test_pass_whitelisted_py_write(self):
        code, _ = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/list_verify_jobs.py"}})
        self.assertEqual(code, 0)

    # --- BLOCK (violations) ---
    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'security-scan/checkpoints/s5_filtered.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("list_verify_jobs", err)   # sast recipe points at sast primitives
        self.assertIn("mgh-sast", err)           # domain-labelled message

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_prep_chunks.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_prep_chunks.py", err)
        self.assertIn("mgh-sast", err)


if __name__ == "__main__":
    unittest.main()
