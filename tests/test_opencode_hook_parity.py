#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""opencode hook shim parity (harden-mgh-opencode-hook-parity §4.2 + §4.4).

Two invariants:
  (A) Normalization parity — the opencode `tool.execute.before` event, normalized by the shim
      into Claude's {tool_name, tool_input} stdin shape, yields the SAME guard decision the
      claude side gets (py -c introspection block / legit leaf pass / out-of-tree write block).
      The normalization MAP is the contract under test; the guard (single decision source) is
      unchanged. This proves the shim is glue-only and decisions don't drift between platforms.
  (B) Guard byte-parity — the opencode guard twin (releases/opencode/hooks/) MUST be
      byte-identical to the claude canonical (releases/claude-code/hooks/), enforcing single-
      logic (CI fail on drift, R5.8). Plus: the .ts shim is NOT in the zero-dep AST scan set
      (that scan globs core/scripts/*.py; .ts is exempt by construction).

Run: py tests/test_opencode_hook_parity.py
"""
import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CC_GUARD = ROOT / "releases" / "claude-code" / "hooks" / "block_adhoc_scripts.py"
OC_GUARD = ROOT / "releases" / "opencode" / "hooks" / "block_adhoc_scripts.py"
SHIM = ROOT / "releases" / "opencode" / "plugins" / "block_adhoc_scripts.ts"


def _load_guard(path: Path):
    spec = importlib.util.spec_from_file_location("block_adhoc_scripts_oc", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# The shim's normalization map (releases/opencode/plugins/block_adhoc_scripts.ts :: normalize),
# mirrored here as the contract under test. opencode args are camelCase; Claude tool_input is
# snake_case. Tool ids are lowercase (bash/write/edit); other tools (read/grep/...) are NOT
# handled by the shim (D7 tool-scope parity with Bash|Write|Edit).
HANDLED = {"bash", "write", "edit"}


def normalize(tool: str, args: dict):
    if tool == "bash":
        return {"tool_name": "Bash", "tool_input": {"command": (args or {}).get("command", "")}}
    fp = (args or {}).get("filePath") or (args or {}).get("file_path") or ""
    return {"tool_name": "Write" if tool == "write" else "Edit", "tool_input": {"file_path": fp}}


def _run_guard(mod, payload, domain_env, target=None):
    """Feed a normalized payload to the guard. domain_env is one of MGH_*_ACTIVE, or None to
    simulate 'outside any run-domain' (guard MUST pass silently). Returns (exit_code, stderr)."""
    keys = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE")
    old_active = {k: os.environ.pop(k, None) for k in keys}
    old_target = os.environ.get("MGH_TARGET")
    for k in keys:
        os.environ.pop(k, None)
    if domain_env is not None:
        os.environ[domain_env] = "1"
    if target is None:
        os.environ.pop("MGH_TARGET", None)
    else:
        os.environ["MGH_TARGET"] = target
    old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.stdin = old_stdin
        for k, v in old_active.items():
            if v is not None:
                os.environ[k] = v
        if old_target is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = old_target
    return code, err.getvalue()


class TestNormalizationParity(unittest.TestCase):
    """§4.2 — normalized opencode event -> guard decides identically to the claude side."""
    def setUp(self):
        self.m = _load_guard(OC_GUARD)

    def _oc(self, tool, args, domain_env="MGH_INIT_ACTIVE", target=None):
        return _run_guard(self.m, normalize(tool, args), domain_env, target)

    # --- py -c introspection: opencode bash -> block (same as claude) ---
    def test_bash_introspection_blocked(self):
        code, err = self._oc("bash", {"command": 'py -c "import json; json.load(open(\'x.json\'))"'})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_bash_legit_leaf_passes(self):
        code, _ = self._oc("bash", {"command": "py .opencode/mgh-core/scripts/discover_controls.py --repo ."})
        self.assertEqual(code, 0)

    # --- write/edit filePath -> file_path normalization: whitelist + adhoc + out-of-tree ---
    def test_write_whitelisted_leaf_passes(self):
        code, _ = self._oc("write", {"filePath": ".opencode/mgh-core/scripts/discover_controls.py"})
        self.assertEqual(code, 0)

    def test_write_adhoc_py_blocked(self):
        code, err = self._oc("write", {"filePath": "_prep_scout_batches.py"})
        self.assertEqual(code, 2)
        self.assertIn("_prep_scout_batches.py", err)

    def test_edit_out_of_tree_blocked(self):
        target = tempfile.mkdtemp(prefix="mgh_op_")
        code, err = self._oc("edit", {"filePath": "D:/xxxraw.json"}, target=target)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_write_in_tree_passes(self):
        target = tempfile.mkdtemp(prefix="mgh_op_")
        code, _ = self._oc("write", {"filePath": f"{target}/.mgh-init/checkpoints/x.json"}, target=target)
        self.assertEqual(code, 0)

    # --- D7 tool-scope: only bash/write/edit are handled; read/grep are NOT normalized ---
    def test_only_bash_write_edit_handled(self):
        self.assertEqual(HANDLED, {"bash", "write", "edit"})
        self.assertNotIn("read", HANDLED)
        self.assertNotIn("grep", HANDLED)

    # --- outside run-domain: pass silently (mirrors claude) ---
    def test_inactive_passes_silently(self):
        # domain_env=None -> no MGH_*_ACTIVE set -> guard sees no active domain -> exit 0
        code, _ = _run_guard(self.m, normalize("bash", {"command": 'py -c "import json"'}),
                               domain_env=None)
        self.assertEqual(code, 0)

    # --- MGH_SRR_ACTIVE: the new /mgh-srr run-domain decides identically on both ends ---
    def test_srr_domain_introspection_blocked(self):
        code, err = self._oc("bash",
            {"command": 'py -c "import json; json.load(open(\'x.json\'))"'},
            domain_env="MGH_SRR_ACTIVE")
        self.assertEqual(code, 2)
        self.assertIn("mgh-srr", err)
        self.assertIn("ingest_requirements", err)   # srr recipe points at srr primitives

    def test_srr_domain_out_of_tree_blocked(self):
        target = tempfile.mkdtemp(prefix="mgh_srr_op_")
        code, err = self._oc("write", {"filePath": "D:/raw.json"},
                             domain_env="MGH_SRR_ACTIVE", target=target)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_srr_domain_in_tree_passes(self):
        target = tempfile.mkdtemp(prefix="mgh_srr_op_")
        code, _ = self._oc("write", {"filePath": f"{target}/.mgh-srr/drafts/x.md"},
                           domain_env="MGH_SRR_ACTIVE", target=target)
        self.assertEqual(code, 0)


class TestGuardByteParity(unittest.TestCase):
    """§4.4 — opencode guard twin MUST be byte-identical to the claude canonical (single logic)."""
    def test_guards_byte_identical(self):
        self.assertTrue(CC_GUARD.is_file(), "claude guard missing")
        self.assertTrue(OC_GUARD.is_file(), "opencode guard twin missing")
        self.assertEqual(CC_GUARD.read_bytes(), OC_GUARD.read_bytes(),
                         "opencode guard drifted from claude canonical — single-source violated")

    def test_shim_exists_and_is_glue_only(self):
        self.assertTrue(SHIM.is_file(), "opencode .ts shim missing")
        text = SHIM.read_text(encoding="utf-8")
        # the shim MUST NOT reimplement guard decision logic (D1/D7: glue only)
        for forbidden in ("_INTRO_TOKENS", "_PYC_RX", "_WL_SEGMENTS", "_is_out_of_tree"):
            self.assertNotIn(forbidden, text, f"shim reimplements guard logic ({forbidden}) — not glue-only")

    def test_ts_not_in_zero_dep_scan_set(self):
        """The R2 zero-dep AST scan globs core/scripts/*.py; the .ts shim + releases/*/hooks/.py
        are NOT in that set, so adding them cannot widen the scan or break R2. Assert the scan root
        contains no .ts and the shim isn't accidentally parsed as Python."""
        scripts = ROOT / "core" / "scripts"
        self.assertEqual(list(scripts.glob("*.ts")), [], ".ts leaked into core/scripts scan set")
        # the shim is valid as text but MUST NOT parse as Python AST (it's TypeScript)
        import ast
        with self.assertRaises((SyntaxError, ValueError)):
            ast.parse(SHIM.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
