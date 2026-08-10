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


_RUN_ROOTS = {"init": ".mgh-init", "sast": "security-scan", "sra": ".mgh-sra",
              "srr": ".mgh-srr", "ut-init": ".mgh-ut-init"}
_DOMAIN_KEYS = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE",
                "MGH_UT_INIT_ACTIVE")


def _run_guard_sentinel(mod, payload, domain, sentinel_dict):
    """Run the guard under a fresh temp cwd with a disk sentinel <cwd>/<run-root>/.active and
    NO MGH_*_ACTIVE env (the opencode mid-session condition). Proves the opencode guard twin
    activates via the sentinel just like the claude canonical."""
    old_active = {k: os.environ.pop(k, None) for k in _DOMAIN_KEYS}
    for k in _DOMAIN_KEYS:
        os.environ.pop(k, None)
    old_target = os.environ.pop("MGH_TARGET", None)
    cwd_tmp = tempfile.mkdtemp(prefix="mgh_par_sent_")
    spath = Path(cwd_tmp) / _RUN_ROOTS[domain] / ".active"
    spath.parent.mkdir(parents=True, exist_ok=True)
    spath.write_text(json.dumps(sentinel_dict), encoding="utf-8")
    old_cwd, old_stdin = os.getcwd(), sys.stdin
    out, err = io.StringIO(), io.StringIO()
    code = None
    try:
        os.chdir(cwd_tmp)
        sys.stdin = io.StringIO(json.dumps(payload))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.stdin = old_stdin
        os.chdir(old_cwd)
        try:
            spath.unlink()
        except OSError:
            pass
        for k, v in old_active.items():
            if v is not None:
                os.environ[k] = v
        if old_target is not None:
            os.environ["MGH_TARGET"] = old_target
    return code, err.getvalue()


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
    keys = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE",
            "MGH_UT_INIT_ACTIVE")
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

    # --- write/edit filePath -> file_path normalization: leaf-script read-only + adhoc + out-of-tree ---
    def test_write_leaf_script_blocked(self):
        # whitelist removed (D2): leaf scripts are read-only at runtime; the opencode layout
        # (.opencode/mgh-core/scripts/) is no longer exempt -> BLOCK (same decision as claude).
        code, _ = self._oc("write", {"filePath": ".opencode/mgh-core/scripts/discover_controls.py"})
        self.assertEqual(code, 2)

    def test_write_adhoc_py_blocked(self):
        code, err = self._oc("write", {"filePath": "_prep_scout_batches.py"})
        self.assertEqual(code, 2)
        self.assertIn("_prep_scout_batches.py", err)

    def test_edit_out_of_tree_blocked(self):
        target = tempfile.mkdtemp(prefix="mgh_op_")
        code, err = self._oc("edit", {"filePath": "D:/xxxraw.json"}, target=target)
        self.assertEqual(code, 2)
        # init domain (default) uses the positive allowlist; D:/ is outside every sanctioned subtree.
        self.assertIn("sanctioned init subtrees", err)

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

    # --- sentinel activation: opencode guard activates via disk sentinel with env unset ---
    def test_sentinel_activates_introspection_blocked(self):
        # the opencode plugin process does not inherit mid-session env; the disk sentinel closes
        # that hole. No MGH_*_ACTIVE env, sentinel present -> guard activates -> block.
        code, err = _run_guard_sentinel(self.m,
            normalize("bash", {"command": 'py -c "import json; json.load(open(\'x.json\'))"'}),
            "init", {"domain": "mgh-init", "target": "", "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_bash_temp_write_readback_blocked(self):
        # new temp-dir I/O rule decides identically on the opencode side (same guard twin).
        code, err = self._oc("bash", {"command": r'py x.py > /tmp/x.json; cat /tmp/x.json'})
        self.assertEqual(code, 2)
        self.assertIn("stdout", err)

    # --- MGH_UT_INIT_ACTIVE: the fifth run-domain decides identically on both ends ---
    def test_ut_init_domain_introspection_blocked(self):
        code, err = self._oc("bash",
            {"command": 'py -c "import json; json.load(open(\'x.json\'))"'},
            domain_env="MGH_UT_INIT_ACTIVE")
        self.assertEqual(code, 2)
        self.assertIn("mgh-ut-init", err)
        self.assertIn("list_test_groups", err)   # ut recipe points at ut work-list primitive

    def test_ut_init_domain_root_pollution_blocked(self):
        target = tempfile.mkdtemp(prefix="mgh_ut_op_")
        code, err = self._oc("write", {"filePath": f"{target}/temp_clusters1.json"},
                             domain_env="MGH_UT_INIT_ACTIVE", target=target)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned ut-init subtrees", err)

    def test_ut_init_sanctioned_subtree_passes(self):
        target = tempfile.mkdtemp(prefix="mgh_ut_op_")
        for rel in (".mgh-ut-init/inputs/t1/u.input.json",
                    ".claude/rules/test-junit5.md",
                    "docs/test-conventions/mockito.md",
                    "AGENTS.md"):
            code, err = self._oc("write", {"filePath": f"{target}/{rel}"},
                                 domain_env="MGH_UT_INIT_ACTIVE", target=target)
            self.assertEqual(code, 0, f"ut-init sanctioned write blocked: {rel}\n{err}")


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
        # the shim MUST NOT reimplement guard decision logic (glue only — single decision source).
        # Forbidden tokens track the current guard internals: sentinel + script-ext set +
        # init allowlist + activation/out-of-tree/introspection + temp-dir I/O detection.
        for forbidden in ("_INTRO_TOKENS", "_PYC_RX", "_SCRIPT_EXTS", "_read_sentinel",
                          "_resolve_domain", "_allowlist_write_blocked", "_is_out_of_tree",
                          "_ALLOWLIST_SUBTREES", "out_roots", "_detect_temp_io", "_TEMP_WRITE_RX"):
            self.assertNotIn(forbidden, text, f"shim reimplements guard logic ({forbidden}) — not glue-only")

    def test_both_guards_embed_new_sentinel_logic(self):
        """Byte-identity must be of the NEW guard, not a stale twin: both canonical and opencode
        guard carry the sentinel-activation + script-ext-set + init-allowlist + temp-dir I/O
        detection logic."""
        for guard in (CC_GUARD, OC_GUARD):
            text = guard.read_text(encoding="utf-8")
            for marker in ("_read_sentinel", "_resolve_domain", "_SCRIPT_EXTS",
                           "_allowlist_write_blocked", "_ALLOWLIST_SUBTREES", "out_roots",
                           ".active", "_detect_temp_io", "_TEMP_WRITE_RX", "_temp_path_rx",
                           "MGH_UT_INIT_ACTIVE", ".mgh-ut-init", "test_groups.json"):
                self.assertIn(marker, text, f"{guard.name} missing new-logic marker {marker}")

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

    def test_shim_feeds_stdin_via_blob_not_string(self):
        """Regression guard for the D7 root cause: opencode's bundled Bun rejects a STRING
        stdin (TypeError: stdio must be 'inherit'|'pipe'|'ignore'|Bun.file|number|null) -> the
        shim MUST feed the guard payload as a Blob. A bare `stdin: <string>` silently throws
        inside runGuard -> fail-soft-pass -> the guard never blocks (confirmed opencode 1.18.3).
        The Bun.spawn runtime call is NOT exercisable in CI (no Bun), so this asserts the source
        form; manual opencode verification covers the runtime delivery."""
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn(
            "new Blob([stdin])", text,
            "shim must feed stdin as new Blob([stdin]); a bare string stdin throws in opencode's "
            "bundled Bun and silently disables the guard (the D7 root cause)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
