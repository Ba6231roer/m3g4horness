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
import contextlib, importlib.util, io, json, os, re, sys, tempfile, unittest
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
# snake_case. Tool ids are lowercase; bash/write/edit/read/glob/grep are handled (read-side
# out-of-tree confinement decides on both platforms) PLUS apply_patch (opencode's multi-file
# mutating tool, whose patchText markers normalize extracts into paths[]). A direct `rg`/`grep`/
# … in Bash routes through the `bash` tool + the guard's Bash file-search rule (no separate
# HANDLED entry).
HANDLED = {"bash", "write", "edit", "read", "glob", "grep", "apply_patch"}
# apply_patch marker lines (opencode packages/core/src/patch.ts:35-51). GLUE ONLY — the test
# mirror extracts paths[]/operations[] exactly as the shim does (no confinement decision here).
_PATCH_MARKER_RX = re.compile(
    r'\*\*\* (?:Add|Update|Delete) File: (.+?)$|\*\*\* Move to: (.+?)$', re.MULTILINE)


def _normalize_apply_patch(patch_text: str):
    paths, operations = [], []
    for m in _PATCH_MARKER_RX.finditer(patch_text):
        raw = (m.group(1) or m.group(2) or "").strip()
        if raw:
            paths.append(raw)
            line = patch_text[max(0, m.start()):m.start() + 20].lower()
            if "delete file" in line:
                operations.append("delete")
            elif "move to" in line:
                operations.append("move")
            elif "update file" in line:
                operations.append("update")
            else:
                operations.append("add")
    return {"tool_name": "ApplyPatch", "tool_input": {"paths": paths, "operations": operations}}


def normalize(tool: str, args: dict):
    a = args or {}
    if tool == "bash":
        return {"tool_name": "Bash", "tool_input": {"command": a.get("command", "")}}
    if tool == "glob":
        return {"tool_name": "Glob", "tool_input": {"pattern": a.get("pattern", ""),
                                                    "path": a.get("path", "")}}
    if tool == "grep":
        # grep source field: schema-validated `include`, falls back to `glob`.
        return {"tool_name": "Grep", "tool_input": {"pattern": a.get("pattern", ""),
                                                    "path": a.get("path", ""),
                                                    "glob": a.get("include") or a.get("glob", "")}}
    if tool == "apply_patch":
        return _normalize_apply_patch(a.get("patchText", ""))
    # write/edit/read: filePath ?? file_path ?? path (path is the opencode schema field).
    fp = a.get("filePath") or a.get("file_path") or a.get("path") or ""
    name = "Read" if tool == "read" else "Write" if tool == "write" else "Edit"
    return {"tool_name": name, "tool_input": {"file_path": fp}}


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

    # --- tool-scope: bash/write/edit/read/glob/grep/apply_patch are handled ---
    def test_bash_write_edit_read_glob_grep_handled(self):
        self.assertEqual(HANDLED, {"bash", "write", "edit", "read", "glob", "grep", "apply_patch"})
        # normalize covers the read-side tools (camelCase -> snake_case the guard expects).
        self.assertEqual(
            normalize("read", {"filePath": "D:/x.java"}),
            {"tool_name": "Read", "tool_input": {"file_path": "D:/x.java"}})
        self.assertEqual(
            normalize("glob", {"pattern": "**/*.java", "path": "D:/repo"}),
            {"tool_name": "Glob", "tool_input": {"pattern": "**/*.java", "path": "D:/repo"}})
        self.assertEqual(
            normalize("grep", {"pattern": "Foo", "path": "D:/repo", "glob": "*.java"}),
            {"tool_name": "Grep", "tool_input": {"pattern": "Foo", "path": "D:/repo", "glob": "*.java"}})

    # --- apply_patch handled: HANDLED includes apply_patch; normalize extracts patchText markers ---
    def test_apply_patch_handled_and_normalized(self):
        self.assertIn("apply_patch", HANDLED)
        # patchText marker extraction -> paths[]/operations[] (glue-only; no confinement decision).
        self.assertEqual(
            normalize("apply_patch", {"patchText":
                "*** Add File: D:/out/evil.ps1\n*** Delete File: D:/parent/sonB/y.java\n"
                "*** Move to: D:/a/z.md"}),
            {"tool_name": "ApplyPatch", "tool_input": {
                "paths": ["D:/out/evil.ps1", "D:/parent/sonB/y.java", "D:/a/z.md"],
                "operations": ["add", "delete", "move"]}})

    # --- read-side confinement parity: normalized opencode read/glob/grep/bash-rg reach the
    #     SAME guard decision the claude side gets (harden-mgh-read-confinement) ---
    def test_read_out_of_tree_blocked(self):
        code, err = self._oc("read", {"filePath": r"D:\parent\sonB\x.java"},
                             target=r"D:\parent\sonA")
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)

    def test_read_in_tree_passes(self):
        code, _ = self._oc("read", {"filePath": r"D:\parent\sonA\src\A.java"},
                           target=r"D:\parent\sonA")
        self.assertEqual(code, 0)

    def test_glob_out_of_tree_blocked(self):
        code, _ = self._oc("glob", {"pattern": "**/*.java", "path": r"D:\parent\sonB"},
                           target=r"D:\parent\sonA")
        self.assertEqual(code, 2)

    def test_grep_in_tree_passes(self):
        code, _ = self._oc("grep", {"pattern": "x", "path": r"D:\parent\sonA", "glob": "*.java"},
                           target=r"D:\parent\sonA")
        self.assertEqual(code, 0)

    def test_bash_rg_out_of_tree_blocked(self):
        # a direct `rg` in Bash routes through the bash tool + the guard's Bash file-search
        # rule (D9) — same decision as the claude side; no separate HANDLED entry needed.
        code, _ = self._oc("bash", {"command": r'rg "x" D:\parent\sonB\src'},
                           target=r"D:\parent\sonA")
        self.assertEqual(code, 2)

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

    # --- file-association script-exec rule: decides identically on the opencode side ---
    def test_bash_file_assoc_callop_blocked(self):
        # the observed Windows scout deadlock shape (opencode runs Bash under PowerShell ->
        # `& "<abs>.py"` resolves the .py association -> Notepad/dialog deadlock). The
        # normalized opencode bash event reaches the SAME guard decision as claude.
        code, err = self._oc("bash", {"command":
            r'& "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --out x y.java'})
        self.assertEqual(code, 2)
        self.assertIn("file association", err)

    def test_bash_file_assoc_bare_py_blocked(self):
        code, _ = self._oc("bash", {"command":
            r'"D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x'})
        self.assertEqual(code, 2)

    def test_bash_file_assoc_py_launcher_passes(self):
        code, _ = self._oc("bash", {"command":
            r'py "D:\proj\chunk_sources.py" --in x --out y.json'})
        self.assertEqual(code, 0)

    def test_bash_file_assoc_script_as_arg_passes(self):
        # operand-vs-arg: a .py that is only a --flag arg to a launched command passes.
        code, _ = self._oc("bash", {"command":
            r'py "D:\proj\discover.py" --in "D:\other.py"'})
        self.assertEqual(code, 0)

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

    # --- apply_patch parity: shim extracts patchText markers -> guard decides identically ---
    def test_apply_patch_out_of_tree_add_blocked(self):
        # patchText with an out-of-tree add -> shim extracts paths[] -> guard blocks (init
        # allowlist, .ps1 is also a script-ext). Same decision the claude side would render.
        code, err = self._oc("apply_patch",
            {"patchText": "*** Add File: D:/out/evil.ps1\nsome content"},
            target=r"D:\parent\sonA")
        self.assertEqual(code, 2)
        self.assertIn("ApplyPatch", err)

    def test_apply_patch_out_of_tree_delete_delete_wording(self):
        code, err = self._oc("apply_patch",
            {"patchText": "*** Delete File: D:/parent/sonB/y.java"},
            target=r"D:\parent\sonA")
        self.assertEqual(code, 2)
        self.assertIn("irreversible", err.lower())   # delete op => delete-side wording

    def test_apply_patch_in_tree_sanctioned_passes(self):
        target = tempfile.mkdtemp(prefix="mgh_ap_op_")
        code, _ = self._oc("apply_patch",
            {"patchText": f"*** Add File: {target}/.mgh-init/x.json\nx"},
            target=target)
        self.assertEqual(code, 0)

    # --- arg-name defense-in-depth: schema-validated `path` arg still confines (D9) ---
    def test_write_path_arg_out_of_tree_blocked(self):
        # opencode schema field is `path` (not filePath); the fallback chain resolves it -> the
        # out-of-tree write is still confined (rather than silently passing on an empty filePath).
        target = tempfile.mkdtemp(prefix="mgh_path_")
        code, err = self._oc("write", {"path": "D:/xxxraw.json"}, target=target)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_read_path_arg_out_of_tree_blocked(self):
        # read side: a `path` arg (schema-validated) resolves and is confined.
        code, _ = self._oc("read", {"path": r"D:\parent\sonB\x.java"},
                           target=r"D:\parent\sonA")
        self.assertEqual(code, 2)

    def test_grep_include_arg_normalized(self):
        # grep source field: schema `include` falls back to `glob` — normalize maps include.
        self.assertEqual(
            normalize("grep", {"pattern": "x", "path": "D:/repo", "include": "*.java"}),
            {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "D:/repo", "glob": "*.java"}})


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
        # init allowlist + activation/out-of-tree/introspection + temp-dir I/O detection +
        # read-side confinement + Bash file-search detection + write/delete-side confinement
        # (mutation verbs / redirect / py -c write tokens) + ApplyPatch guard-side branching.
        for forbidden in ("_INTRO_TOKENS", "_PYC_RX", "_SCRIPT_EXTS", "_read_sentinel",
                          "_resolve_domain", "_allowlist_write_blocked", "_is_out_of_tree",
                          "_ALLOWLIST_SUBTREES", "out_roots", "_detect_temp_io", "_TEMP_WRITE_RX",
                          "_is_file_assoc_script_exec", "_CMD_BODY_EXT_RX", "_LAUNCHER_PREFIXES",
                          "_read_out_of_tree", "_out_of_tree_file_search", "_FILE_SEARCH_VERBS",
                          "_FILE_SEARCH_VERB_RX", "_ABS_PATH_TOKEN_RX", "_read_recipe",
                          "is_relative_to",
                          "_WRITE_VERBS", "_DELETE_VERBS", "_MUTATION_VERB_RX",
                          "_out_of_tree_mutation", "_REDIRECT_RX", "_PYC_WRITE_TOKENS",
                          "_write_recipe", "_COPY_MOVE_DEST_VERBS",
                          "_is_temp_redirect_target", "_redirect_in_sanctioned"):
            self.assertNotIn(forbidden, text, f"shim reimplements guard logic ({forbidden}) — not glue-only")

    def test_both_guards_embed_new_sentinel_logic(self):
        """Byte-identity must be of the NEW guard, not a stale twin: both canonical and opencode
        guard carry the sentinel-activation + script-ext-set + init-allowlist + temp-dir I/O
        detection logic + write/delete-side confinement (mutation verbs / redirect / py -c write
        tokens / ApplyPatch)."""
        for guard in (CC_GUARD, OC_GUARD):
            text = guard.read_text(encoding="utf-8")
            for marker in ("_read_sentinel", "_resolve_domain", "_SCRIPT_EXTS",
                           "_allowlist_write_blocked", "_ALLOWLIST_SUBTREES", "out_roots",
                           ".active", "_detect_temp_io", "_TEMP_WRITE_RX", "_temp_path_rx",
                           "MGH_UT_INIT_ACTIVE", ".mgh-ut-init", "test_groups.json",
                           "_is_file_assoc_script_exec", "_CMD_BODY_EXT_RX",
                           "_LAUNCHER_PREFIXES", "_CALL_OP_RX",
                           "_read_out_of_tree", "_out_of_tree_file_search", "_FILE_SEARCH_VERBS",
                           "_FILE_SEARCH_VERB_RX", "_ABS_PATH_TOKEN_RX", "_read_recipe",
                           "_WRITE_VERBS", "_DELETE_VERBS", "_MUTATION_VERB_RX",
                           "_out_of_tree_mutation", "_REDIRECT_RX", "_PYC_WRITE_TOKENS",
                           "_write_recipe", "ApplyPatch"):
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

    def test_shim_handles_apply_patch_and_path_fallback(self):
        """Source-form assertion that the shim feeds apply_patch (HANDLED + normalize marker
        extraction) and uses the `path`/`include` arg-name fallback chains (D9 defense-in-depth).
        These mirror the normalize() contract above; asserting the source form catches drift
        between the test mirror and the actual shim (which CI cannot exercise at runtime)."""
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn('"apply_patch"', text)              # HANDLED set includes apply_patch
        self.assertIn("PATCH_MARKER_RX", text)            # marker extraction present
        self.assertIn("ApplyPatch", text)                 # emits tool_name ApplyPatch
        # arg-name fallback chains (path for write/edit/read; include for grep)
        self.assertIn("args?.path", text)
        self.assertIn("args?.include", text)


class TestWiringCoverage(unittest.TestCase):
    """Guard tool-surface wiring coverage (harden-mgh-init-scout-path-binding, consultation
    layer D2) — ONE invariant across both hosts: every tool name the guard's main()
    dispatches on MUST be covered by BOTH wiring faces:
      (a) the claude-side default PreToolUse matcher injected by tools/install_hook.py
          (`_DEFAULT_MATCHER`, `|`-split);
      (b) the opencode .ts shim's HANDLED set via its lowercase mapping in normalize().
    Adding a guard decision branch without extending both wiring faces = a DEAD branch on
    that host (the claude matcher previously covered only Bash|Write|Edit, so the
    read-side branches were never consulted and an out-of-tree Read reached the host
    permission prompt instead of failing loud). This test structurally closes that gap
    class: forget to extend a face -> CI fails here."""

    _DISPATCH_RX = re.compile(
        r'if tool == "([A-Za-z_]+)"'          # if tool == "Bash"
        r'|elif tool in \(([^)]*)\)')         # elif tool in ("Read", "Glob", ...)

    def _guard_dispatch_tools(self):
        """Statically extract every tool name the guard's main() dispatches on. The
        dispatch shape is fixed (`if tool == "X"` / `elif tool in ("X", "Y")`); if the
        guard is ever refactored to another shape this extractor (and this test) must be
        updated in lockstep — same maintenance contract as the parity mirror above."""
        src = CC_GUARD.read_text(encoding="utf-8")
        names = set()
        for m in self._DISPATCH_RX.finditer(src):
            if m.group(1):
                names.add(m.group(1))
            else:
                for lit in re.findall(r'"([A-Za-z_]+)"', m.group(2)):
                    names.add(lit)
        self.assertTrue(names, "no dispatch tools extracted — extractor drifted from the "
                               "guard's main() dispatch shape")
        return names

    def test_every_guard_branch_is_in_claude_matcher(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "install_hook_wiring", ROOT / "tools" / "install_hook.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        matcher = {t.strip() for t in mod._DEFAULT_MATCHER.split("|") if t.strip()}
        missing = self._guard_dispatch_tools() - matcher
        self.assertFalse(missing,
            f"guard dispatches on {sorted(missing)} but the claude PreToolUse default "
            f"matcher does not carry them — those branches are DEAD on claude (extend "
            f"tools/install_hook.py::_DEFAULT_MATCHER)")

    def test_every_guard_branch_is_in_shim_handled(self):
        shim = SHIM.read_text(encoding="utf-8")
        handled = re.search(r'const HANDLED = new Set\(\[(.*?)\]\)', shim, re.DOTALL)
        self.assertIsNotNone(handled, "shim HANDLED set not found — shim drifted")
        handled_set = {t.strip().strip('"\'') for t in handled.group(1).split(",") if t.strip()}
        # the shim normalizes to the guard's tool_name via lowercase ids; map each
        # dispatch name to its lowercase / opencode-native id.
        oc_ids = {n.lower().replace("applypatch", "apply_patch") for n in
                  self._guard_dispatch_tools()}
        # Bash -> bash, ApplyPatch -> apply_patch, Read/Glob/Grep -> read/glob/grep, etc.
        missing = {i for i in oc_ids if i not in handled_set}
        self.assertFalse(missing,
            f"guard dispatches on {sorted(missing)} but the opencode shim HANDLED set does "
            f"not carry them — those branches are DEAD on opencode (extend HANDLED + "
            f"normalize in block_adhoc_scripts.ts)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
