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
# HANDLED entry). TWO GENERATIONS converge on the same guard faces (fix-mgh-opencode2-plugin-
# compat): opencode 2.x renamed `bash` -> `shell` and ships a `patch` tool (same patchText
# field + marker syntax as 1.x `apply_patch`; confirmed packages/core/src/tool/plugin/{shell,
# patch}.ts) — the same install may be loaded by a 2.0.x or 2.1.x host, so both generations
# must stay handled. read/write/edit/glob/grep kept their names across both generations.
HANDLED = {"bash", "shell", "write", "edit", "read", "glob", "grep", "apply_patch", "patch"}
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
    # two generations, one Bash face: 1.x `bash` and 2.x `shell` both carry {command}.
    if tool in ("bash", "shell"):
        return {"tool_name": "Bash", "tool_input": {"command": a.get("command", "")}}
    if tool == "glob":
        return {"tool_name": "Glob", "tool_input": {"pattern": a.get("pattern", ""),
                                                    "path": a.get("path", "")}}
    if tool == "grep":
        # grep source field: schema-validated `include`, falls back to `glob`.
        return {"tool_name": "Grep", "tool_input": {"pattern": a.get("pattern", ""),
                                                    "path": a.get("path", ""),
                                                    "glob": a.get("include") or a.get("glob", "")}}
    # two generations, one ApplyPatch face: 1.x `apply_patch` and 2.x `patch` both carry the
    # SAME patchText field + marker syntax (opencode packages/core/src/tool/plugin/patch.ts).
    if tool in ("apply_patch", "patch"):
        return _normalize_apply_patch(a.get("patchText", ""))
    # write/edit/read: filePath ?? file_path ?? path (path is the opencode schema field).
    fp = a.get("filePath") or a.get("file_path") or a.get("path") or ""
    name = "Read" if tool == "read" else "Write" if tool == "write" else "Edit"
    return {"tool_name": name, "tool_input": {"file_path": fp}}


# --- opencode 2.x plugin module-contract shape (fix-mgh-opencode2-plugin-compat) ---
# Shared source-form assertions, applied to the repo shim AND to the INSTALLED copy (imported
# by tests/test_install_opencode_plugin.py). Anchors STRUCTURAL features (default export +
# awaited hook registration + anchor capture/injection), never verbatim prose — a refactor
# that keeps the structure passes. The 2.x loader rejects a 1.x-shaped file with only a WARN
# (fail-soft; sessions continue) so shape drift is undetectable at runtime by design — CI is
# the only fail-loud position (no opencode/Bun runtime here). Source facts this encodes:
# default export { id, setup } (packages/core/src/plugin/module.ts Module schema); hooks via
# ctx.tool.hook("execute.before", cb) with a SINGLE event object {tool, input, ...}
# (packages/plugin/src/effect/tool.ts ToolHooks) and the permission gate via
# ctx.permission.hook("evaluate", cb) with the mutable evaluation event
# {action, resources, effect, message} (packages/plugin/src/effect/permission.ts
# PermissionEvaluation); ctx.location.directory = session project root
# (packages/schema/src/location.ts Location.Info).
_V2_REQUIRED_RX = [
    (re.compile(r"export default \{\s*id:"),
     "default export carrying an id field (2.x module contract; a named export is REJECTED "
     "by the 2.x loader — fail-soft WARN, guard silently absent)"),
    (re.compile(r"async setup\("), "async setup(ctx) entry"),
    (re.compile(r"await ctx\.tool\.hook\("),
     "tool hook registration awaited inside setup (a fire-and-forget registration lets the first "
     "tool call slip past an unregistered hook)"),
    (re.compile(r"await ctx\.permission\.hook\("),
     "permission gate registration awaited inside setup (add-mgh-native-permission-gate: the "
     "same anti-race contract covers BOTH hook faces — a fire-and-forget registration lets the "
     "first permission assertion slip past an unregistered gate)"),
    (re.compile(r"ctx\.location\.directory"), "project-root anchor captured in setup"),
    (re.compile(r"cwd:\s*projectRoot"),
     "payload cwd injection (2.x service-process cwd is unrelated to the project)"),
    (re.compile(r"event\??\.tool"), "2.x single event object: tool id read from event.tool"),
    (re.compile(r"event\??\.input"), "2.x single event object: args read from event.input"),
    (re.compile(r"new Blob\(\[stdin\]\)"), "stdin delivered as Blob (the D7 root cause)"),
    (re.compile(r"existsSync"), "guard-file existence pre-check (fail-soft)"),
    (re.compile(r"can't open file"), "can't-open-file exit-2 fallback (fail-soft)"),
    (re.compile(r"console\.warn"),
     "non-blocking diagnostics downgraded to best-effort output (no ctx.client.app.log in 2.x)"),
]
_V2_FORBIDDEN = [
    ("export const BlockAdhocScripts", "1.x named-export hook-map form (rejected by the 2.x loader)"),
    ("output: { args", "1.x two-parameter (input, output) callback form"),
    ("ctx.client", "1.x client.app.log diagnostic channel (absent in 2.x)"),
]


def assert_shim_v2_shape(text: str):
    for rx, why in _V2_REQUIRED_RX:
        if rx.search(text) is None:
            raise AssertionError(f"opencode shim misses 2.x shape token ({why}): /{rx.pattern}/")
    for token, why in _V2_FORBIDDEN:
        if token in text:
            raise AssertionError(f"opencode shim carries 1.x shape token ({why}): {token!r}")


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

    # --- tool-scope: bash/shell/write/edit/read/glob/grep/apply_patch/patch are handled ---
    def test_bash_write_edit_read_glob_grep_handled(self):
        self.assertEqual(HANDLED, {"bash", "shell", "write", "edit", "read", "glob", "grep",
                                   "apply_patch", "patch"})
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

    # --- two-generation tool-id convergence (fix-mgh-opencode2-plugin-compat): both
    #     generations normalize IDENTICALLY onto the same guard face; dropping either
    #     generation silently un-guards that host (upgrade-drift AND revert-drift). ---
    def test_shell_introspection_blocked(self):
        # the 2.x renamed id reaches the SAME Bash-face decision (convergence, not a listing).
        code, err = self._oc("shell", {"command": 'py -c "import json; json.load(open(\'x.json\'))"'})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_bash_and_shell_normalize_identically(self):
        for tool in ("bash", "shell"):
            self.assertEqual(
                normalize(tool, {"command": 'py -c "import json"'}),
                {"tool_name": "Bash", "tool_input": {"command": 'py -c "import json"'}})

    def test_apply_patch_and_patch_normalize_identically(self):
        self.assertIn("patch", HANDLED)
        text = "*** Add File: D:/out/evil.ps1\ncontent"
        for tool in ("apply_patch", "patch"):
            self.assertEqual(
                normalize(tool, {"patchText": text}),
                {"tool_name": "ApplyPatch",
                 "tool_input": {"paths": ["D:/out/evil.ps1"], "operations": ["add"]}})
        # a missing patchText field => empty extraction (the guard passes on empty paths[];
        # the 2.x `patch` tool actually carries patchText — confirmed from source).
        for tool in ("apply_patch", "patch"):
            self.assertEqual(
                normalize(tool, {}),
                {"tool_name": "ApplyPatch", "tool_input": {"paths": [], "operations": []}})

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

    # --- leaf-script source read block decides identically on the opencode side (f2) ---
    def test_read_leaf_script_source_blocked(self):
        # normalized opencode read event -> guard blocks the mgh-core/scripts leaf source
        # Read with the leaf recipe (same decision the claude side renders).
        code, err = self._oc("read", {
            "filePath": r"D:\proj\.opencode\mgh-core\scripts\list_clusters.py"})
        self.assertEqual(code, 2)
        self.assertIn("leaf script source", err)
        self.assertIn("stderr", err)

    def test_read_leaf_script_path_arg_blocked(self):
        # `path` arg-name fallback also reaches the leaf-source decision (D9 parity).
        code, _ = self._oc("read", {
            "path": r"D:\proj\.claude\mgh-core\scripts\resume_state.py"})
        self.assertEqual(code, 2)

    def test_read_target_own_py_passes_leaf_rule(self):
        # the target project's own .py (no mgh-core/scripts segment) passes on opencode too.
        code, _ = self._oc("read", {"filePath": r"D:\proj\src\auth\PermGuard.py"},
                           target=r"D:\proj")
        self.assertEqual(code, 0)

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
                          "is_relative_to", "_is_leaf_script_read",
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
                           "_is_leaf_script_read", "leaf script source",
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

    def test_shim_fails_soft_on_missing_guard_file(self):
        """python exits 2 (`can't open file ...`) for a MISSING guard script — the same exit
        code as a deny. The shim MUST pre-check the guard file (node:fs existsSync) before
        spawning and treat a can't-open-file exit 2 as fail-soft pass + one diagnostic,
        NEVER as a deny (a skewed/missing install used to deny every handled call)."""
        text = SHIM.read_text(encoding="utf-8")
        self.assertIn("existsSync", text)         # spawn-time existence pre-check
        self.assertIn("node:fs", text)            # Bun-compatible stdlib import
        self.assertIn("can't open file", text)    # exit-2 signature fallback (fail-soft)

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


class TestShimV2ModuleShape(unittest.TestCase):
    """opencode 2.x plugin module contract (fix-mgh-opencode2-plugin-compat). The shim MUST
    be a default export { id, setup } with the hook registered via an AWAITED ctx.tool.hook
    call, reading the single event object (event.tool / event.input) and injecting the
    captured project root (ctx.location.directory) as the payload cwd. A 1.x-shaped file is
    rejected by the 2.x loader with only a WARN — the guard would be silently absent for the
    whole run — so the shape is asserted statically here (and on the installed copy by
    tests/test_install_opencode_plugin.py); manual opencode verification covers the runtime."""

    def test_shim_satisfies_v2_module_shape(self):
        assert_shim_v2_shape(SHIM.read_text(encoding="utf-8"))

    def test_reverting_to_1x_shape_trips_the_assertion(self):
        # a minimal 1.x-shaped file (named export + (input, output) callback + client.app.log)
        # must FAIL the shared assertion — proving it actually detects the rejected shape.
        one_x = (
            'import { existsSync } from "node:fs"\n'
            'export const BlockAdhocScripts = async (ctx: { client?: any }) => ({\n'
            '  "tool.execute.before": async (input: { tool: string }, output: { args: any }) => {\n'
            '    await ctx.client?.app?.log?.({ body: {} })\n'
            '  },\n'
            '})\n'
        )
        with self.assertRaises(AssertionError):
            assert_shim_v2_shape(one_x)

    def test_handled_converges_both_tool_generations(self):
        # 2.x renamed tool ids (bash -> shell; the patch-shaped tool id `patch`) — BOTH
        # generations must stay in HANDLED and normalize: the same install file may be loaded
        # by a 2.0.x or 2.1.x host, and dropping either generation silently un-guards that
        # host. Deleting either id from the shim turns this test red.
        shim = SHIM.read_text(encoding="utf-8")
        handled = re.search(r'const HANDLED = new Set\(\[(.*?)\]\)', shim, re.DOTALL)
        self.assertIsNotNone(handled, "shim HANDLED set not found — shim drifted")
        handled_set = {t.strip().strip('"\'') for t in handled.group(1).split(",") if t.strip()}
        for gen1, gen2 in (("bash", "shell"), ("apply_patch", "patch")):
            self.assertIn(gen1, handled_set,
                          f"1.x id {gen1} dropped — revert-drift un-guards older hosts")
            self.assertIn(gen2, handled_set,
                          f"2.x id {gen2} missing — upgrade-drift un-guards 2.x hosts")
        # normalize maps both generations onto the SAME guard face (source form).
        self.assertIn('tool === "bash" || tool === "shell"', shim)
        self.assertIn('tool === "apply_patch" || tool === "patch"', shim)


class TestPermissionGateShape(unittest.TestCase):
    """add-mgh-native-permission-gate: the shim's permission.evaluate gate is source-form
    asserted (no opencode/Bun runtime in CI). The gate is the ONE declared in-process decision
    exception (its fixed rewrite rules live in TS, not the Python guard) — so its branches are
    pinned here: removing any branch, un-awaiting the registration, or dropping the six-run-root
    check turns CI red. The path-membership glue is exercised as round-trip samples against a
    Python MIRROR of the shim's pure functions (same posture as normalize() above); source
    tokens pin the mirror to the shim so they cannot drift apart silently."""

    def _shim(self):
        return SHIM.read_text(encoding="utf-8")

    # --- Python mirror of the shim's normPath/inDeclaredRoot glue (contract under test) ---
    @staticmethod
    def _norm_path(p):
        p = re.sub(r"\\", "/", p)
        return re.sub(r"/+$", "", p).lower()

    @classmethod
    def _in_declared_root(cls, resource, root):
        res = cls._norm_path(re.sub(r"/\*$", "", resource))
        r = cls._norm_path(root)
        if not res or not r:
            return False
        return res == r or res.startswith(r + "/")

    def test_evaluate_registration_awaited_in_setup(self):
        shim = self._shim()
        self.assertIn('await ctx.permission.hook("evaluate"', shim,
                      "permission.evaluate registration missing or fire-and-forget — the first "
                      "permission assertion would slip past an unregistered gate")

    def test_rewrite_branches_present(self):
        shim = self._shim()
        # question branch: rewrite to deny only when not already deny.
        self.assertIn('event.action === "question"', shim, "question-reject branch missing")
        self.assertIn('event.effect !== "deny"', shim,
                      "question branch must leave a rule-level deny untouched")
        # ask branch: entry gated on effect === "ask", rewritten to deny with a substitute hint.
        self.assertIn('event.effect !== "ask"', shim,
                      "ask branch entry missing — the gate must only close asks")
        self.assertGreaterEqual(shim.count('event.effect = "deny"'), 2,
                                "ask->deny and question->deny rewrites both required")
        self.assertIn('event.message = "', shim, "deny rewrite carries no substitute hint")
        # read_roots exception: external_directory + EVERY resource inside a declared root -> allow.
        self.assertIn('event.action === "external_directory"', shim,
                      "external_directory exception branch missing")
        self.assertIn('event.effect = "allow"', shim,
                      "read_roots-allow rewrite missing — approved external repos would regress "
                      "to deny")
        self.assertIn(".every(", shim,
                      "allow exception must require EVERY resource inside read_roots (never "
                      "partial)")

    def test_six_run_roots_direct_child_check_no_ancestor_walk(self):
        shim = self._shim()
        m = re.search(r"const RUN_ROOTS = \[(.*?)\]", shim, re.DOTALL)
        self.assertIsNotNone(m, "RUN_ROOTS constant missing — run-domain identification drifted")
        roots = {t.strip().strip('"') for t in m.group(1).split(",") if t.strip()}
        self.assertEqual(
            roots,
            {".mgh-init", "security-scan", ".mgh-sra", ".mgh-srr", ".mgh-ut-init", ".mgh-sdr"},
            "six run roots drifted from the mgh contract")
        # direct-child sentinel check: the path is a plain concatenation, no upward walk.
        self.assertIn('runRoot + "/.active"', shim,
                      "sentinel path must be the direct child <projectRoot>/<runRoot>/.active")
        for walk_token in ("dirname(", '"/.."', "'..'", "parent"):
            self.assertNotIn(walk_token, shim[m.start():],
                             f"gate must NOT walk ancestors (out-of-project sentinel would be "
                             f"claimed): found {walk_token!r} in the gate section")

    def test_sentinel_fail_closed_and_exception_face(self):
        shim = self._shim()
        # present-but-unparsable sentinel: domain stays active, read_roots empty (asks deny).
        self.assertIn("read_roots", shim, "sentinel read_roots field not read")
        self.assertIn("Array.isArray(", shim,
                      "read_roots must be type-checked — a wrong-typed field grants nothing")
        # any error inside the callback passes the event untouched (never defects the host's
        # permission evaluation) with a best-effort diagnostic.
        self.assertIn("try {", shim, "gate callback has no exception face")
        self.assertIn("passing untouched", shim,
                      "gate error diagnostic missing (fail-open toward the host)")
        self.assertIn("unreadable sentinel", shim,
                      "unparsable-sentinel diagnostic missing (fail-closed toward asks)")

    def test_normalization_glue_roundtrip_samples(self):
        # round-trip samples over the mirrored glue: backslash/slash, case, trailing slash,
        # glob tail — the Windows faces the real host produces.
        cases = [
            # (resource, root, expected)
            (r"C:/ext/repo/*", r"C:\ext\repo", True),          # canonical external_directory ask
            (r"C:/ext/repo/sub/x.java", r"C:\Ext\Repo", True),  # case-insensitive + nested
            (r"c:/ext/repo/*", r"C:\EXT\REPO", True),           # drive + segment case folding
            (r"C:/ext/repo", "C:\\ext\\repo\\", True),          # no glob tail, trailing-slash root
            (r"C:/ext/repo2/*", r"C:\ext\repo", False),         # sibling dir: prefix must NOT match
            (r"C:/ext/other/*", r"C:\ext\repo", False),         # different tree
            (r"C:\ext\repo\*", r"C:/ext/repo", True),           # backslash resource face
            ("", r"C:\ext\repo", False),                        # empty resource grants nothing
            (r"C:/x/*", "", False),                             # empty root grants nothing
        ]
        for resource, root, expected in cases:
            self.assertEqual(self._in_declared_root(resource, root), expected,
                             f"inDeclaredRoot({resource!r}, {root!r}) != {expected}")

    def test_mirror_pinned_to_shim_source(self):
        # the Python mirror above must not drift from the shim's glue: the three normalization
        # behaviors are pinned as source tokens.
        shim = self._shim()
        self.assertIn(r'replace(/\\', shim, "backslash normalization missing in shim")
        self.assertIn("toLowerCase()", shim, "case folding missing in shim")
        self.assertIn(r'replace(/\/\*$', shim,
                      "glob-tail strip missing in shim (membership would never match the "
                      "external_directory resource face)")


class TestAgentQuestionDenyPinned(unittest.TestCase):
    """add-mgh-native-permission-gate fallback layer: EVERY opencode mgh agent definition pins
    `question: deny` (opencode defaults question to allow on the default agent — an unattended
    hang face that survives even with the plugin gate in place for non-mgh agent shapes), and
    every agent that needs external-directory isolation carries `external_directory: deny`
    (the fanout twins had it from the headless-dispatch pinning; their non-fanout siblings were
    the gap). The rule-level deny short-circuits BEFORE any hook, so this layer stands alone
    when the plugin is absent — deleting any pin turns CI red."""

    AGENT_DIR = ROOT / "releases" / "opencode" / "agent"
    # fanout twins (pinned historically for headless dispatch) + their non-fanout siblings
    # (same job, same isolation, previously unpinned).
    EXT_DENY_REQUIRED = {
        "init-induct", "init-induct-fanout",
        "init-rulewriter", "init-rulewriter-fanout",
        "init-scout", "init-scout-fanout",
        "init-scout-merge", "init-scout-merge-fanout",
        "init-synthesis", "init-synthesis-fanout",
        "sdr-review-fanout",
    }

    def _frontmatter(self, name):
        text = (self.AGENT_DIR / f"{name}.md").read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m, f"{name}: frontmatter block missing")
        return m.group(1)

    def test_every_opencode_agent_pins_question_deny(self):
        agents = sorted(p.stem for p in self.AGENT_DIR.glob("*.md"))
        self.assertGreaterEqual(len(agents), 30, "agent inventory unexpectedly small — "
                                                   "the pin check may be scanning the wrong dir")
        for name in agents:
            self.assertIn("  question: deny", self._frontmatter(name),
                          f"{name}: `question: deny` pin missing — an unattended run can hang "
                          f"on a user question via this agent")

    def test_isolation_agents_pin_external_directory_deny(self):
        for name in sorted(self.EXT_DENY_REQUIRED):
            self.assertTrue((self.AGENT_DIR / f"{name}.md").is_file(),
                            f"{name}.md missing — inventory drifted, update EXT_DENY_REQUIRED")
            self.assertIn("  external_directory: deny", self._frontmatter(name),
                          f"{name}: `external_directory: deny` pin missing — an unattended run "
                          f"can hang on an out-of-project read via this agent")

    def test_removing_a_pin_trips_the_assertion(self):
        # self-check: a frontmatter without the pin fails the same predicate used above.
        self.assertNotIn("  question: deny", "permission:\n  read: allow\n  edit: deny")
        self.assertNotIn("  external_directory: deny", "permission:\n  read: allow")



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

    DSH_SHIM = ROOT / "releases" / "dsh" / "plugins" / "mgh-guard.ts"

    def _dsh_tool_map(self):
        """Statically parse the dsh shim's exported TOOL_MAP object literal (id -> guard
        dispatch name). Same no-execute posture as the opencode HANDLED parse above."""
        src = self.DSH_SHIM.read_text(encoding="utf-8")
        m = re.search(r'export const TOOL_MAP = \{(.*?)\} as const', src, re.DOTALL)
        self.assertIsNotNone(m, "dsh shim TOOL_MAP not found — shim drifted from the "
                                "statically-parseable constant shape")
        body = re.sub(r'//[^\n]*', '', m.group(1))  # strip inline comments
        pairs = re.findall(r'(\w+)\s*:\s*"([A-Za-z_]+)"', body)
        self.assertTrue(pairs, "no TOOL_MAP pairs parsed — extractor drifted")
        return dict(pairs)

    def test_every_guard_branch_is_in_dsh_tool_map(self):
        """Third wiring face (add-mgh-dsh-host-foundation): every guard dispatch name must
        be a VALUE of the dsh shim's TOOL_MAP — otherwise the branch is unreachable on dsh
        (dead code). dsh-only names live here naturally; claude/opencode-native names ride
        the shim's claude-id passthrough entries (multiedit/notebookedit)."""
        mapped = set(self._dsh_tool_map().values())
        missing = self._guard_dispatch_tools() - mapped
        self.assertFalse(missing,
            f"guard dispatches on {sorted(missing)} but the dsh shim TOOL_MAP does not map "
            f"any dsh tool id onto them — those branches are DEAD on dsh (extend TOOL_MAP "
            f"+ normalize in releases/dsh/plugins/mgh-guard.ts)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
