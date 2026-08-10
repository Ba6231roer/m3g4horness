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

_DOMAIN_ENV = {"init": "MGH_INIT_ACTIVE", "sast": "MGH_SAST_ACTIVE",
               "sra": "MGH_SRA_ACTIVE", "srr": "MGH_SRR_ACTIVE",
               "ut-init": "MGH_UT_INIT_ACTIVE"}


def _load():
    spec = importlib.util.spec_from_file_location("block_adhoc_scripts", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_hook(mod, payload, domain="init", active="1"):
    """Invoke mod.main() with the given run-domain env set; isolate every OTHER mgh
    domain env so the test is deterministic. Returns (exit_code, stderr)."""
    key = _DOMAIN_ENV[domain]
    siblings = [v for d, v in _DOMAIN_ENV.items() if d != domain]
    old_val = os.environ.get(key)
    old_siblings = {s: os.environ.pop(s, None) for s in siblings}
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
        for s, val in old_siblings.items():
            if val is not None:
                os.environ[s] = val
    return code, err.getvalue()


_RUN_ROOTS = {"init": ".mgh-init", "sast": "security-scan", "sra": ".mgh-sra",
              "srr": ".mgh-srr", "ut-init": ".mgh-ut-init"}
_DOMAIN_KEYS = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE",
                "MGH_UT_INIT_ACTIVE")


def _run_with_sentinel(mod, payload, domain, sentinel_dict, mgh_target_env=None):
    """Run mod.main() with NO MGH_*_ACTIVE env (simulating opencode mid-session: the plugin
    process does not inherit bash-exported env) but with a disk sentinel
    <cwd>/<run-root>/.active present under a fresh temp cwd. The sentinel activates the guard
    AND its `target`/`out_roots` drive the subtree check -- proving the opencode reliability
    boundary is closed by the sentinel. Pass sentinel_dict=None to write NO sentinel (inactive
    baseline). Returns (exit_code, stderr). Restores cwd + env + removes the sentinel."""
    run_root = _RUN_ROOTS[domain]
    old_active = {k: os.environ.pop(k, None) for k in _DOMAIN_KEYS}
    for k in _DOMAIN_KEYS:
        os.environ.pop(k, None)
    old_target = os.environ.get("MGH_TARGET")
    if mgh_target_env is None:
        os.environ.pop("MGH_TARGET", None)
    else:
        os.environ["MGH_TARGET"] = mgh_target_env
    cwd_tmp = tempfile.mkdtemp(prefix="mgh_sentcwd_")
    spath = Path(cwd_tmp) / run_root / ".active"
    if sentinel_dict is not None:
        spath.parent.mkdir(parents=True, exist_ok=True)
        spath.write_text(json.dumps(sentinel_dict), encoding="utf-8")
    old_cwd = os.getcwd()
    old_stdin = sys.stdin
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
        if sentinel_dict is not None:
            try:
                spath.unlink()
            except OSError:
                pass
        for k, v in old_active.items():
            if v is not None:
                os.environ[k] = v
        if old_target is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = old_target
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

    def test_block_leaf_script_write(self):
        # whitelist removed (D2): leaf scripts are read-only at runtime -- editing a sanctioned
        # leaf .py during a run is the "agent edits list_clusters.py" failure shape -> BLOCK.
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/discover_controls.py"}})
        self.assertEqual(code, 2)
        self.assertIn("discover_controls.py", err)

    def test_block_tests_dir_script_write(self):
        # no tests/tools/hooks whitelist exemption either (D2): any script ext in a run -> BLOCK.
        code, _ = self._run({"tool_name": "Write", "tool_input": {"file_path": "tests/test_x.py"}})
        self.assertEqual(code, 2)

    def test_block_script_extension_set(self):
        # script extension set (D3): .ps1/.sh/.ts leak past the old .py-only check -> BLOCK.
        for ext in (".ps1", ".sh", ".bash", ".bat", ".ts", ".js"):
            code, _ = self._run({"tool_name": "Write", "tool_input": {
                "file_path": f"process_induct{ext}"}})
            self.assertEqual(code, 2, f"script ext {ext} not blocked")

    def test_pass_non_script_artifact_write(self):
        # .json/.md are NOT in the script set (legit artifacts); their *location* is governed by
        # the write-confinement rule, not this one. No MGH_TARGET/sentinel -> allowlist degrades.
        for name in ("x.json", "y.md"):
            code, _ = self._run({"tool_name": "Write", "tool_input": {"file_path": name}})
            self.assertEqual(code, 0, f"non-script {name} blocked by the script rule")

    def test_inactive_passes_script_write(self):
        # install/CI/dev (guard inactive) -> script writes pass; the whitelist removal only
        # bites at runtime.
        code, _ = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "tests/test_x.py"}}, active="")
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
        # init positive allowlist: drive-root is outside every sanctioned subtree.
        self.assertIn("sanctioned init subtrees", err)
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


class TestBlockAdhocScriptsUtInit(unittest.TestCase):
    """/mgh-ut-init run-domain (MGH_UT_INIT_ACTIVE=1) — the fifth domain. Same shape as init's
    positive allowlist: ut-init writes rules into .claude/rules + docs/test-conventions +
    AGENTS.md, so root-level pollution fails loud just like init's."""

    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="ut-init", active=active)

    def _run_with_target(self, payload, target):
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

    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("list_test_groups", err)  # recipe points at the ut work-list primitive

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_prep_extract.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_prep_extract.py", err)

    def test_block_root_pollution(self):
        # ut-init writes rules into the project root — a root-level temp file fails loud
        # (same in-tree root-pollution shape init guards against).
        target = tempfile.mkdtemp(prefix="mgh_ut_tgt_")
        code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/temp_groups1.json"}}, target)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned ut-init subtrees", err)

    def test_pass_sanctioned_subtrees(self):
        target = tempfile.mkdtemp(prefix="mgh_ut_tgt_")
        for rel in (".mgh-ut-init/inputs/t1/u.input.json",
                    ".claude/rules/test-junit5.md",
                    "docs/test-conventions/mockito.md",
                    "AGENTS.md"):
            code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
                "file_path": f"{target}/{rel}"}}, target)
            self.assertEqual(code, 0, f"ut-init sanctioned write blocked: {rel}\n{err}")

    def test_block_out_of_tree_drive_root(self):
        target = tempfile.mkdtemp(prefix="mgh_ut_tgt_")
        code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, target)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned ut-init subtrees", err)

    def test_block_cat_test_groups_aggregate(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": "cat .mgh-ut-init/test_groups.json"}})
        self.assertEqual(code, 2)
        self.assertIn("input_path", err)

    def test_sentinel_activates_introspection_block(self):
        # env unset, disk sentinel .mgh-ut-init/.active present -> guard activates (opencode
        # reliability boundary closed for the fifth domain too).
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {
                "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            "ut-init", {"domain": "mgh-ut-init", "target": "", "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)


class TestBlockAdhocScriptsSentinel(unittest.TestCase):
    """Disk-sentinel activation (D1): the guard activates via <cwd>/<run-root>/.active even
    when NO MGH_*_ACTIVE env is set -- closing the opencode reliability boundary (the .ts
    plugin process does not inherit mid-session bash-exported env, so env-only activation left
    the opencode guard dormant for a whole run). The sentinel also carries `target`, so the
    subtree check fires on opencode without env MGH_TARGET, and `out_roots[]` honors custom
    --out/--rules-dir. init positive-allowlist confinement (D4) is covered here too."""

    def setUp(self):
        self.m = _load()

    def _sent(self, payload, domain, sentinel_dict, mgh_target_env=None):
        return _run_with_sentinel(self.m, payload, domain, sentinel_dict, mgh_target_env)

    _NOENV = {"domain": "mgh-init", "target": "", "out_roots": [], "v": 1}

    # --- sentinel activates the guard with env unset (opencode hole closed) ---
    def test_sentinel_activates_introspection_block(self):
        code, err = self._sent({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            "init", self._NOENV)
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_sentinel_activates_script_write_block(self):
        code, _ = self._sent({"tool_name": "Write", "tool_input": {"file_path": "_prep.py"}},
                             "init", self._NOENV)
        self.assertEqual(code, 2)

    def test_no_sentinel_no_env_is_silent(self):
        # neither env nor sentinel -> guard inactive -> exit 0 (zero day-to-day noise).
        code, _ = self._sent({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            "init", None)
        self.assertEqual(code, 0)

    # --- sentinel carries target -> subtree check fires without env MGH_TARGET ---
    def test_sentinel_target_drives_out_of_tree_block(self):
        # env MGH_TARGET unset; sentinel.target=<tmp> -> Write outside that tree is blocked
        # (proves MGH_TARGET is taken from the sentinel, not env).
        target = tempfile.mkdtemp(prefix="mgh_stgt_")
        code, err = self._sent({"tool_name": "Write", "tool_input": {"file_path": "D:/raw.json"}},
            "sra", {"domain": "mgh-sra", "target": target, "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_sentinel_no_target_degrades(self):
        # sentinel present (activates) but target empty + no env MGH_TARGET -> subtree degrades.
        code, _ = self._sent({"tool_name": "Write", "tool_input": {"file_path": "D:/raw.json"}},
            "sra", {"domain": "mgh-sra", "target": "", "out_roots": [], "v": 1})
        self.assertEqual(code, 0)

    # --- init positive allowlist: root pollution blocked, sanctioned subtrees pass (D4) ---
    def test_init_root_pollution_blocked(self):
        target = tempfile.mkdtemp(prefix="mgh_poll_")
        code, err = self._sent({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/temp_clusters1.json"}},
            "init", {"domain": "mgh-init", "target": target, "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_init_sanctioned_subtrees_pass(self):
        target = tempfile.mkdtemp(prefix="mgh_san_")
        sent = {"domain": "mgh-init", "target": target, "out_roots": [], "v": 1}
        for path in (f"{target}/.mgh-init/inputs/t1/u.input.json",
                     f"{target}/.claude/rules/x.md",
                     f"{target}/docs/security-controls/a.md",
                     f"{target}/AGENTS.md"):
            code, _ = self._sent({"tool_name": "Write", "tool_input": {"file_path": path}},
                                 "init", sent)
            self.assertEqual(code, 0, f"sanctioned write blocked: {path}")

    def test_init_custom_out_root_passes(self):
        # sentinel out_roots[] honors a customized --out / --rules-dir absolute root.
        target = tempfile.mkdtemp(prefix="mgh_out_")
        custom = tempfile.mkdtemp(prefix="mgh_custom_")
        code, _ = self._sent({"tool_name": "Write", "tool_input": {"file_path": f"{custom}/x.json"}},
            "init", {"domain": "mgh-init", "target": target, "out_roots": [custom], "v": 1})
        self.assertEqual(code, 0)


class TestBlockAdhocScriptsAggregateRead(unittest.TestCase):
    """Whole-read of a multi-unit aggregate (cat/head/tail) is blocked in every run-domain
    (request-context-budget defense-in-depth; the structural fix is per-unit materialization).
    The recipe points the agent at the list_* --materialize input_path."""

    def setUp(self):
        self.m = _load()

    def _bash(self, cmd, domain="init"):
        return _run_hook(self.m, {"tool_name": "Bash", "tool_input": {"command": cmd}},
                         domain=domain)

    # --- BLOCK: shell whole-read of an init aggregate ---
    def test_block_cat_clusters_json(self):
        code, err = self._bash("cat .mgh-init/clusters.json")
        self.assertEqual(code, 2)
        self.assertIn("input_path", err)        # recipe -> list_* --materialize input_path
        self.assertIn("describe_artifact", err)

    def test_block_head_controls_inventory_json(self):
        code, _ = self._bash("head -n 100 .mgh-init/controls_inventory.json")
        self.assertEqual(code, 2)

    def test_block_tail_scout_plan_json(self):
        code, _ = self._bash("tail -n 50 .mgh-init/scout_plan.json")
        self.assertEqual(code, 2)

    def test_block_python_c_whole_read(self):
        # the pre-existing py -c introspection guard already catches this shape too
        code, _ = self._bash('py -c "import json; json.load(open(\'.mgh-init/clusters.json\'))"')
        self.assertEqual(code, 2)

    # --- PASS: legit leaf invocation references the aggregate as a --flag, not a read verb ---
    def test_pass_list_clusters_with_clusters_flag(self):
        code, _ = self._bash("py .claude/mgh-core/scripts/list_clusters.py "
                             "--clusters .mgh-init/clusters.json --materialize .mgh-init/inputs/t1")
        self.assertEqual(code, 0)

    def test_pass_merge_scout_refs_aggregates_as_flags(self):
        code, _ = self._bash("py .claude/mgh-core/scripts/merge_scout.py "
                             "--clusters .mgh-init/clusters.json --candidates .mgh-init/controls_candidates.json")
        self.assertEqual(code, 0)

    def test_pass_cat_non_aggregate(self):
        code, _ = self._bash("cat .mgh-init/report.md")
        self.assertEqual(code, 0)

    # --- cross-domain aggregates (the four domains share the guard; sast/sra/srr covered) ---
    def test_block_sast_aggregate(self):
        code, err = self._bash("cat security-scan/checkpoints/s5_filtered.json", domain="sast")
        self.assertEqual(code, 2)
        self.assertIn("mgh-sast", err)

    def test_block_sra_aggregate(self):
        code, err = self._bash("cat .mgh-sra/change_context.json", domain="sra")
        self.assertEqual(code, 2)
        self.assertIn("mgh-sra", err)
        self.assertIn("input_path", err)   # recipe -> prepare_augment --materialize input_path

    def test_block_srr_aggregate(self):
        code, err = self._bash("cat .mgh-srr/change_context.json", domain="srr")
        self.assertEqual(code, 2)
        self.assertIn("mgh-srr", err)
        self.assertIn("input_path", err)   # recipe -> ingest_requirements --materialize input_path

    def test_pass_srr_ingest_materialize(self):
        # legit leaf invocation: ingest_requirements --materialize is the sanctioned per-unit
        # input primitive (NOT a whole-read) — MUST pass (request-context-budget adoption).
        code, _ = self._bash("py .claude/mgh-core/scripts/ingest_requirements.py "
                             "--doc req.md --materialize .mgh-srr/inputs/augment", domain="srr")
        self.assertEqual(code, 0)


class TestBlockAdhocScriptsTempIo(unittest.TestCase):
    """Temp-dir write + read-back within a SINGLE Bash invocation is blocked (defense-in-depth
    for the orchestrator stdout-consumption discipline; the primary fix is the fragment's
    "stdout 直消费"). Conservative: write-only temp I/O, in-tree redirects, read-only temp
    access, and inactive sessions all pass."""

    def setUp(self):
        self.m = _load()

    def _bash(self, cmd, domain="init", active="1"):
        return _run_hook(self.m, {"tool_name": "Bash", "tool_input": {"command": cmd}},
                         domain=domain, active=active)

    # --- BLOCK: temp write + read-back in the same invocation ---
    def test_block_pwsh_env_temp_write_readback(self):
        code, err = self._bash(
            r'py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan .mgh-init/scout_plan.json '
            r'> $env:TEMP/scout_page0.json; Get-Content $env:TEMP/scout_page0.json -Raw | ConvertFrom-Json')
        self.assertEqual(code, 2)
        self.assertIn("stdout", err)
        self.assertIn("stdout 直消费", err)   # recipe points at the discipline's direct-consumption

    def test_block_posix_tmp_write_readback(self):
        code, _ = self._bash(
            r'py .claude/mgh-core/scripts/list_scout_batches.py --scout-plan x '
            r'> /tmp/scout_page0.json; cat /tmp/scout_page0.json | jq .')
        self.assertEqual(code, 2)

    def test_block_env_tmp_variant(self):
        code, _ = self._bash(r'py x.py > $env:TMP/scout.json; type $env:TMP\scout.json')
        self.assertEqual(code, 2)

    def test_block_pct_temp_variant(self):
        code, _ = self._bash(r'py x.py > %TEMP%\scout.json & type %TEMP%\scout.json')
        self.assertEqual(code, 2)

    def test_block_quoted_path(self):
        code, _ = self._bash(r'py x.py > "$env:TEMP/x.json"; gc "$env:TEMP/x.json"')
        self.assertEqual(code, 2)

    # --- PASS: conservative non-blocks ---
    def test_pass_in_tree_redirect(self):
        # redirect to the sanctioned subtree is NOT a temp-dir pattern -> pass.
        code, _ = self._bash(r'py .claude/mgh-core/scripts/discover_controls.py --repo . '
                             r'> .mgh-init/discover_stdout.log')
        self.assertEqual(code, 0)

    def test_pass_temp_write_without_readback(self):
        # write-only temp I/O (no read-back) is NOT flagged — handled by the discipline prompt.
        code, _ = self._bash(r'py .claude/mgh-core/scripts/discover_controls.py --repo . > /tmp/debug.log')
        self.assertEqual(code, 0)

    def test_pass_temp_read_only(self):
        # read-only temp access (no write in the same invocation) is NOT a pairing.
        code, _ = self._bash(r'cat /tmp/old.json')
        self.assertEqual(code, 0)

    def test_pass_leaf_flag_temp_path(self):
        # a `--out /tmp/...` flag (no `>` redirect) is NOT flagged.
        code, _ = self._bash(r'py .claude/mgh-core/scripts/chunk_sources.py --out /tmp/slice.json')
        self.assertEqual(code, 0)

    def test_pass_inactive_session(self):
        # outside any run-domain: no Bash scan at all.
        code, _ = self._bash(r'py x.py > /tmp/x.json; cat /tmp/x.json', active="")
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

    def test_block_leaf_script_write(self):
        # whitelist removed (D2): leaf scripts read-only at runtime; editing list_verify_jobs.py
        # during a sast run -> BLOCK.
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/list_verify_jobs.py"}})
        self.assertEqual(code, 2)
        self.assertIn("mgh-sast", err)

    # --- BLOCK (violations) ---
    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'security-scan/checkpoints/s5_filtered.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("list_verify_jobs", err)   # sast recipe points at sast primitives
        self.assertIn("mgh-sast", err)           # domain-labelled message

    def test_block_introspection_s3_chunks(self):
        # whole-read of the s3 multi-chunk aggregate (s4 fan-out source) is blocked too;
        # the sast recipe points at list_chunks (request-context-budget: per-chunk input_path).
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'security-scan/checkpoints/s3_chunks.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("list_chunks", err)
        self.assertIn("mgh-sast", err)

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_prep_chunks.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_prep_chunks.py", err)
        self.assertIn("mgh-sast", err)


class TestBlockAdhocScriptsSra(unittest.TestCase):
    """/mgh-sra run-domain (MGH_SRA_ACTIVE=1) — mirrors the init column (the sra domain
    gets the same three guards: introspection / ad-hoc .py / out-of-tree). MGH_TARGET is
    the project root, so both change-draft and project-memory writes are in-tree."""

    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="sra", active=active)

    def _run_with_target(self, payload, target):
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

    # --- PASS (legitimate) ---
    def test_inactive_passes_introspection_silently(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}}, active="")
        self.assertEqual(code, 0)

    def test_pass_legit_leaf_invocation(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": "py .claude/mgh-core/scripts/prepare_augment.py --change foo --rules .mgh-init"}})
        self.assertEqual(code, 0)

    def test_block_leaf_script_write(self):
        # whitelist removed (D2): editing merge_memory.py during an sra run -> BLOCK.
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/merge_memory.py"}})
        self.assertEqual(code, 2)
        self.assertIn("mgh-sra", err)

    def test_pass_in_tree_draft_write(self):
        # change draft path under the project subtree
        target = tempfile.mkdtemp(prefix="mgh_sra_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/openspec/changes/c/.mgh-sra/drafts/payment-api.md"}}, target)
        self.assertEqual(code, 0)

    def test_pass_in_tree_memory_write(self):
        # project-level business memory under the project subtree
        target = tempfile.mkdtemp(prefix="mgh_sra_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/.mgh-sra/business_context.json"}}, target)
        self.assertEqual(code, 0)

    # --- BLOCK (violations) ---
    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'c/.mgh-sra/change_context.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("prepare_augment", err)   # sra recipe points at sra primitives
        self.assertIn("mgh-sra", err)           # domain-labelled message

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_aggregate_augment.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_aggregate_augment.py", err)
        self.assertIn("mgh-sra", err)

    def test_block_out_of_tree_drive_root(self):
        target = tempfile.mkdtemp(prefix="mgh_sra_")
        code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, target)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)
        self.assertIn("draft_path", err)        # recipe points at producer stdout field

    def test_block_out_of_tree_other_dir(self):
        target = tempfile.mkdtemp(prefix="mgh_sra_")
        other = tempfile.mkdtemp(prefix="mgh_other_")
        code, _ = self._run_with_target({"tool_name": "Edit", "tool_input": {
            "file_path": f"{other}/spec.md"}}, target)
        self.assertEqual(code, 2)

    def test_subtree_guard_degrades_without_target(self):
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, None)
        self.assertEqual(code, 0)


class TestBlockAdhocScriptsSrr(unittest.TestCase):
    """/mgh-srr run-domain (MGH_SRR_ACTIVE=1) — mirrors the sra column (same three guards:
    introspection / ad-hoc .py / out-of-tree). MGH_TARGET is the project root, so review-dir
    draft/report and shared project-memory writes are in-tree."""

    def setUp(self):
        self.m = _load()

    def _run(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="srr", active=active)

    def _run_with_target(self, payload, target):
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

    # --- PASS (legitimate) ---
    def test_inactive_passes_introspection_silently(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'x.json\'))"'}}, active="")
        self.assertEqual(code, 0)

    def test_pass_legit_leaf_invocation(self):
        code, _ = self._run({"tool_name": "Bash", "tool_input": {
            "command": "py .claude/mgh-core/scripts/ingest_requirements.py --doc req.md"}})
        self.assertEqual(code, 0)

    def test_block_leaf_script_write(self):
        # whitelist removed (D2): editing render_report.py during an srr run -> BLOCK.
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": ".claude/mgh-core/scripts/render_report.py"}})
        self.assertEqual(code, 2)
        self.assertIn("mgh-srr", err)

    def test_pass_in_tree_draft_write(self):
        target = tempfile.mkdtemp(prefix="mgh_srr_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/.mgh-srr/drafts/freeform-review.md"}}, target)
        self.assertEqual(code, 0)

    def test_pass_in_tree_shared_memory_write(self):
        # srr shares sra's project-level business memory
        target = tempfile.mkdtemp(prefix="mgh_srr_")
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": f"{target}/.mgh-sra/business_context.json"}}, target)
        self.assertEqual(code, 0)

    # --- BLOCK (violations) ---
    def test_block_introspection_py_c(self):
        code, err = self._run({"tool_name": "Bash", "tool_input": {
            "command": 'py -c "import json; json.load(open(\'.mgh-srr/change_context.json\'))"'}})
        self.assertEqual(code, 2)
        self.assertIn("ingest_requirements", err)   # srr recipe points at srr primitives
        self.assertIn("mgh-srr", err)               # domain-labelled message

    def test_block_adhoc_py_write(self):
        code, err = self._run({"tool_name": "Write", "tool_input": {
            "file_path": "_aggregate_report.py"}})
        self.assertEqual(code, 2)
        self.assertIn("_aggregate_report.py", err)
        self.assertIn("mgh-srr", err)

    def test_block_out_of_tree_drive_root(self):
        target = tempfile.mkdtemp(prefix="mgh_srr_")
        code, err = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, target)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)
        self.assertIn("draft_path", err)        # recipe points at producer stdout field

    def test_block_out_of_tree_other_dir(self):
        target = tempfile.mkdtemp(prefix="mgh_srr_")
        other = tempfile.mkdtemp(prefix="mgh_other_")
        code, _ = self._run_with_target({"tool_name": "Edit", "tool_input": {
            "file_path": f"{other}/report.md"}}, target)
        self.assertEqual(code, 2)

    def test_subtree_guard_degrades_without_target(self):
        code, _ = self._run_with_target({"tool_name": "Write", "tool_input": {
            "file_path": "D:/xxxraw.json"}}, None)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
