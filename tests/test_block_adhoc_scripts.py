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
               "sdr": "MGH_SDR_ACTIVE",
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
              "srr": ".mgh-srr", "sdr": ".mgh-sdr", "ut-init": ".mgh-ut-init"}
_DOMAIN_KEYS = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE",
                "MGH_SDR_ACTIVE", "MGH_UT_INIT_ACTIVE")


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


class TestReadSideConfinement(unittest.TestCase):
    """Read-side out-of-tree confinement (harden-mgh-read-confinement). The read side is the
    peer of the write out-of-tree check (same MGH_TARGET precedence + is_relative_to
    semantics), NOT a positive-allowlist check — any file inside the target tree is
    readable. It turns the soft failure (cross-module read reaching the host permission
    prompt and interrupting the run, e.g. a parent-repo submodule cwd) into a fail-loud
    recipe. Covers both surfaces: the tool-abstraction layer (Read/Glob/Grep) and the Bash
    file-search escape route (rg/grep/findstr/find/…). target absent => degrade to pass."""

    def setUp(self):
        self.m = _load()

    def _read(self, payload, target):
        """init run-domain with MGH_TARGET set; isolate sibling domain env. Returns (code,err)."""
        key = _DOMAIN_ENV["init"]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != "init"]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = "1"
        os.environ["MGH_TARGET"] = target
        old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        return code, err.getvalue()

    def _read_no_target(self, payload, active="1"):
        """init run-domain, MGH_TARGET unset (degrade-path baseline)."""
        key = _DOMAIN_ENV["init"]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != "init"]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = active
        os.environ.pop("MGH_TARGET", None)
        old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        return code, err.getvalue()

    _PARENT = r"D:\parent"        # submodule layout: cwd/target = sonA, sibling = sonB
    _SONA = r"D:\parent\sonA"
    _SONB = r"D:\parent\sonB"

    # --- tool-abstraction layer: Read ---
    def test_read_parent_dir_file_blocked(self):
        code, err = self._read({"tool_name": "Read", "tool_input": {
            "file_path": self._SONB + r"\src\Main.java"}}, self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)
        self.assertIn("sibling", err)

    def test_read_in_tree_file_passes(self):
        code, _ = self._read({"tool_name": "Read", "tool_input": {
            "file_path": self._SONA + r"\src\auth\PermGuard.java"}}, self._SONA)
        self.assertEqual(code, 0)

    def test_read_sonA_target_blocks_parent(self):
        # target IS sonA (submodule cwd); reading the parent dir itself is the leak shape.
        code, _ = self._read({"tool_name": "Read", "tool_input": {
            "file_path": self._PARENT + r"\README.md"}}, self._SONA)
        self.assertEqual(code, 2)

    # --- tool-abstraction layer: Glob / Grep ---
    def test_glob_path_sibling_blocked(self):
        code, _ = self._read({"tool_name": "Glob", "tool_input": {
            "pattern": "**/*.java", "path": self._SONB}}, self._SONA)
        self.assertEqual(code, 2)

    def test_grep_no_path_cwd_outside_blocked(self):
        # cwd defaults to a temp dir (outside sonA); Grep with no path -> cwd anchor -> block (D4).
        code, err = self._read({"tool_name": "Grep", "tool_input": {
            "pattern": "TokenInterceptor"}}, self._SONA)
        self.assertEqual(code, 2)

    def test_grep_path_repo_root_passes(self):
        code, _ = self._read({"tool_name": "Grep", "tool_input": {
            "pattern": "TokenInterceptor", "path": self._SONA}}, self._SONA)
        self.assertEqual(code, 0)

    def test_glob_in_tree_path_passes(self):
        code, _ = self._read({"tool_name": "Glob", "tool_input": {
            "pattern": "**/*.java", "path": self._SONA + r"\src"}}, self._SONA)
        self.assertEqual(code, 0)

    # --- degrade + inactive ---
    def test_read_degrades_without_target(self):
        # active run-domain but MGH_TARGET unset AND no sentinel.target -> read side passes.
        code, _ = self._read_no_target({"tool_name": "Read", "tool_input": {
            "file_path": "D:/anywhere/x.java"}})
        self.assertEqual(code, 0)

    def test_inactive_session_passes_read(self):
        code, _ = self._read_no_target({"tool_name": "Read", "tool_input": {
            "file_path": self._SONB + r"\x.java"}}, active="")
        self.assertEqual(code, 0)

    # --- Bash file-search escape route (D9) ---
    def test_bash_rg_out_of_tree_blocked(self):
        code, err = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'rg "TokenInterceptor" {self._SONB}\\src'}}, self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("file search", err)

    def test_bash_rg_cwd_outside_blocked(self):
        # no explicit path -> cwd anchor; cwd is a temp dir outside sonA -> block (D4).
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": 'rg "TokenInterceptor"'}}, self._SONA)
        self.assertEqual(code, 2)

    def test_bash_rg_in_tree_passes(self):
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'rg "TokenInterceptor" {self._SONA}\\src'}}, self._SONA)
        self.assertEqual(code, 0)

    def test_bash_findstr_out_of_tree_blocked(self):
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'findstr /S "x" {self._SONB}\\*'}}, self._SONA)
        self.assertEqual(code, 2)

    def test_bash_find_out_of_tree_blocked(self):
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'find {self._SONB} -name "*.java"'}}, self._SONA)
        self.assertEqual(code, 2)

    def test_bash_grep_out_of_tree_blocked(self):
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'grep -r "x" {self._SONB}'}}, self._SONA)
        self.assertEqual(code, 2)

    # --- operand-vs-arg: a non-search-verb command with a path arg does NOT trip D9 ---
    def test_bash_non_search_verb_with_path_arg_passes(self):
        code, _ = self._read({"tool_name": "Bash", "tool_input": {
            "command": f'py "discover.py" --in "{self._SONA}\\src\\X.java"'}}, self._SONA)
        self.assertEqual(code, 0)

    def test_bash_file_search_inactive_passes(self):
        code, _ = self._read_no_target({"tool_name": "Bash", "tool_input": {
            "command": f'rg "x" {self._SONB}'}}, active="")
        self.assertEqual(code, 0)

    # --- cross-domain: read side fires in every run-domain (sast shown) ---
    def test_sast_read_out_of_tree_blocked(self):
        key = _DOMAIN_ENV["sast"]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != "sast"]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = "1"
        os.environ["MGH_TARGET"] = self._SONA
        old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(
            {"tool_name": "Read", "tool_input": {"file_path": self._SONB + r"\x.java"}}))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        self.assertEqual(code, 2)
        self.assertIn("mgh-sast", err.getvalue())

    # --- opencode reliability boundary: read side activates via disk sentinel ---
    def test_sentinel_target_drives_read_block(self):
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": self._SONB + r"\x.java"}},
            "init", {"domain": "mgh-init", "target": self._SONA, "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)

    def test_sentinel_no_target_read_degrades(self):
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": self._SONB + r"\x.java"}},
            "init", {"domain": "mgh-init", "target": "", "out_roots": [], "v": 1})
        self.assertEqual(code, 0)


class TestSentinelReadRoots(unittest.TestCase):
    """Sentinel read_roots[] (add-mgh-sdr): declared external roots grant READ-ONLY access
    on BOTH faces — the tool face (Read/Glob/Grep) and the Bash face (search/listing verbs +
    the catch-all path-token allowset) — when active via disk sentinel (semantic reversal:
    the Bash face now judges the same unified allow-set, not MGH_TARGET alone). The write
    side (tool + Bash verb + redirect) and the leaf-source block are NEVER relaxed. Fail-
    closed: a declared root must exist and be a directory at judgment time (a missing root
    grants zero). Absent read_roots = byte-for-byte legacy behavior."""

    def setUp(self):
        self.m = _load()

    def _setup_trees(self):
        target = tempfile.mkdtemp(prefix="mgh_sdr_tgt_")
        front = tempfile.mkdtemp(prefix="mgh_sdr_front_")
        other = tempfile.mkdtemp(prefix="mgh_sdr_other_")
        Path(front, "src", "api").mkdir(parents=True, exist_ok=True)
        Path(front, "src", "api", "pay.js").write_text("// front", encoding="utf-8")
        Path(other, "x.js").write_text("// other", encoding="utf-8")
        return Path(target), Path(front), Path(other)

    def _sentinel(self, target, front, missing=False):
        roots = [str(front)]
        if missing:
            roots = [str(Path(front.parent, "gone_front"))]
        return {"domain": "mgh-sdr", "target": str(target),
                "out_roots": [], "read_roots": roots, "v": 1}

    def test_declared_root_read_passes(self):
        target, front, _ = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(front, "src", "api", "pay.js"))}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 0, err)

    def test_undeclared_sibling_read_blocked(self):
        target, front, other = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(other, "x.js"))}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)

    def test_glob_declared_root_passes(self):
        target, front, _ = self._setup_trees()
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Glob", "tool_input": {"pattern": "*.js", "path": str(front)}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 0)

    def test_grep_undeclared_blocked(self):
        target, front, other = self._setup_trees()
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": str(other)}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)

    def test_write_into_declared_root_still_blocked(self):
        # non-script artifact: the out-of-tree write rule (not the script-ext rule) must fire —
        # read_roots[] never grants write access even for .json/.md artifacts.
        target, front, _ = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Write", "tool_input": {"file_path": str(Path(front, "notes.json"))}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_bash_rg_declared_root_now_passes(self):
        # semantic reversal: the Bash face judges the unified read allow-set, so a declared
        # root is Bash-searchable exactly like it is tool-face-readable.
        target, front, _ = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {"command": f"rg pattern {front}\\src"}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 0, err)

    def test_bash_rg_outside_target_and_roots_blocked(self):
        # the complementary face: outside the target tree AND every declared root => blocked.
        target, front, other = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {"command": f"rg pattern {other}"}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)

    def test_bash_write_declared_root_still_blocked(self):
        # mutation rules run BEFORE the read net: a write-shaped hit surfaces the write-side
        # recipe (read_roots never relaxes a write, not even via the catch-all).
        target, front, _ = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {"command": f"Set-Content {front}\\evil.txt x"}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)

    def test_no_read_roots_byte_identical_legacy(self):
        # a legacy sentinel without read_roots: out-of-tree read blocked as before,
        # no parse error, in-tree read passes.
        target, front, _ = self._setup_trees()
        legacy = {"domain": "mgh-srr", "target": str(target), "out_roots": [], "v": 1}
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(front, "x.js"))}},
            "srr", legacy)
        self.assertEqual(code, 2)
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(target, "a.json"))}},
            "srr", legacy)
        self.assertEqual(code, 0)

    def test_nonexistent_declared_root_grants_zero(self):
        target, front, other = self._setup_trees()
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(front, "src", "api", "pay.js"))}},
            "sdr", self._sentinel(target, front, missing=True))
        self.assertEqual(code, 2)

    def test_sdr_run_root_sentinel_discovered(self):
        # the .mgh-sdr run-root is a first-class discovery location: a sentinel placed at
        # <target>/.mgh-sdr/.active activates the guard for a subdirectory-anchored call.
        target, front, other = self._setup_trees()
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(Path(other, "x.js"))}},
            "sdr", self._sentinel(target, front))
        self.assertEqual(code, 2)
        self.assertIn("mgh-sdr", err)


class TestLeafScriptReadBlock(unittest.TestCase):
    """Leaf-script source read block (f2) — the read-side peer of "leaf scripts read-only".
    A `Read` of a script-extension file under an installed `mgh-core/scripts/` path segment
    fails loud (exit 2 + stderr recipe); the target project's own `.py`, a non-mgh-core
    `.py`, non-script artifacts, and inactive sessions all pass. The path segment is the
    discriminator, NOT the extension alone (design D3)."""

    def setUp(self):
        self.m = _load()

    def _read(self, payload, active="1"):
        return _run_hook(self.m, payload, domain="init", active=active)

    def test_read_claude_layout_leaf_py_blocked(self):
        # .claude/mgh-core/scripts/*.py — the canonical claude install layout.
        code, err = self._read({"tool_name": "Read", "tool_input": {
            "file_path": r"D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py"}})
        self.assertEqual(code, 2)
        self.assertIn("leaf script source", err)
        self.assertIn("stderr", err)                     # recipe: report errors from stderr

    def test_read_opencode_layout_leaf_py_blocked(self):
        # .opencode/mgh-core/scripts/*.py — the opencode install layout (host-neutral match).
        code, err = self._read({"tool_name": "Read", "tool_input": {
            "file_path": r"D:\parent\sonA\.opencode\mgh-core\scripts\discover_controls.py"}})
        self.assertEqual(code, 2)
        self.assertIn("leaf script source", err)

    def test_read_leaf_ps1_blocked(self):
        # any script extension under mgh-core/scripts (not just .py).
        code, _ = self._read({"tool_name": "Read", "tool_input": {
            "file_path": r"D:\parent\sonA\.claude\mgh-core\scripts\helper.ps1"}})
        self.assertEqual(code, 2)

    def test_read_target_own_py_passes(self):
        # the target project's own source (.py AND .java) — extension alone is NOT the
        # discriminator; without the mgh-core/scripts segment it passes.
        for fp in (r"D:\parent\sonA\src\auth\PermGuard.py",
                   r"D:\parent\sonA\src\auth\PermGuard.java"):
            code, _ = self._read({"tool_name": "Read", "tool_input": {"file_path": fp}})
            self.assertEqual(code, 0, fp)

    def test_read_non_mgh_core_py_passes(self):
        # a vendored .py outside the mgh-core/scripts segment (e.g. target's tools/).
        code, _ = self._read({"tool_name": "Read", "tool_input": {
            "file_path": r"D:\parent\sonA\tools\helper.py"}})
        self.assertEqual(code, 0)

    def test_read_mgh_core_non_script_artifact_passes(self):
        # .json/.md under mgh-core (prompts/contracts) are NOT script sources — pass.
        for fp in (r"D:\parent\sonA\.claude\mgh-core\prompts\fragments\t1.md",
                   r"D:\parent\sonA\.opencode\mgh-core\contracts\hooks\runtime-enforcement.md",
                   r"D:\parent\sonA\.mgh-init\checkpoints\scout\batch-001.json"):
            code, _ = self._read({"tool_name": "Read", "tool_input": {"file_path": fp}})
            self.assertEqual(code, 0, fp)

    def test_inactive_session_passes_leaf_read(self):
        # no env, no sentinel -> guard dormant -> leaf Read passes (install/CI/dev).
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {
                "file_path": r"D:\parent\sonA\.claude\mgh-core\scripts\list_clusters.py"}},
            "init", None)
        self.assertEqual(code, 0)

    def test_sentinel_activated_leaf_read_blocked(self):
        # sentinel activation (opencode mid-session shape) also enforces the leaf read block.
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {
                "file_path": r"D:\parent\sonA\.opencode\mgh-core\scripts\list_clusters.py"}},
            "init", {"domain": "mgh-init", "target": r"D:\parent\sonA", "out_roots": [],
                     "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("leaf script source", err)

    def test_glob_grep_not_affected_by_leaf_rule(self):
        # the leaf rule fires on Read only; Glob/Grep carry no file_path (pattern tools) and
        # stay governed by the out-of-tree anchor check (here: no path + temp cwd IS the
        # cwd-drift shape for Grep, and Glob in-tree passes — both unchanged semantics).
        code, _ = self._read({"tool_name": "Glob", "tool_input": {
            "pattern": "mgh-core/scripts/*.py", "path": r"D:\parent\sonA"}})
        self.assertEqual(code, 0)                        # Glob anchor in-tree → pass


class TestSentinelUpwardWalk(unittest.TestCase):
    """Best-anchor + bounded upward sentinel discovery (harden-mgh-init-scout-path-binding,
    activation layer D1). The anchor = the hook payload `cwd` field when present (claude
    PreToolUse carries the session/tool cwd — the context that issued the tool call),
    falling back to the guard process cwd (opencode plugin process). The walk closes the
    anchor-mismatch gap: a reader subagent whose anchor cwd is a subdirectory of the target
    at ANY depth still discovers the sentinel at <target>/<run-root>/.active (the prior
    cwd-only lookup missed it -> guard dormant -> whole read/write side silently degraded).
    An anchor entirely outside the target tree does NOT hit -> correct dormancy."""

    def setUp(self):
        self.m = _load()

    def _run_at_anchor(self, payload, anchor: Path, sentinel_at: Path | None,
                       sentinel_dict, mgh_target_env=None):
        """Run main() with the guard process cwd = a NEUTRAL temp dir (never the sentinel
        tree), the payload carrying `cwd`=anchor, and an optional sentinel at sentinel_at.
        Env: no MGH_*_ACTIVE (pure sentinel-activation path). Restores cwd + env."""
        old_active = {k: os.environ.pop(k, None) for k in _DOMAIN_KEYS}
        old_target = os.environ.get("MGH_TARGET")
        if mgh_target_env is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = mgh_target_env
        neutral = tempfile.mkdtemp(prefix="mgh_walk_neutral_")
        spath = sentinel_at / ".active" if sentinel_at is not None else None
        if spath is not None:
            spath.parent.mkdir(parents=True, exist_ok=True)
            spath.write_text(json.dumps(sentinel_dict), encoding="utf-8")
        old_cwd, old_stdin = os.getcwd(), sys.stdin
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            os.chdir(neutral)
            body = dict(payload)
            body["cwd"] = str(anchor)
            sys.stdin = io.StringIO(json.dumps(body))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.chdir(old_cwd)
            if spath is not None:
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

    def setUp_target_tree(self):
        """target/.mgh-init/.active sentinel root + a deep subdirectory anchor."""
        target = Path(tempfile.mkdtemp(prefix="mgh_walk_tgt_"))
        (target / ".mgh-init").mkdir(parents=True, exist_ok=True)
        deep = target / "aa" / "bb" / "cc"
        deep.mkdir(parents=True, exist_ok=True)
        return target, deep

    def test_subdir_anchor_walks_up_to_sentinel_and_blocks(self):
        # anchor = target subdirectory (3 levels deep); sentinel at <target>/.mgh-init/.active
        # -> upward walk hits -> guard active -> out-of-tree Read blocked (exit 2).
        target, deep = self.setUp_target_tree()
        code, err = self._run_at_anchor(
            {"tool_name": "Read", "tool_input": {"file_path": r"D:\out\x.java"}},
            deep, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)

    def test_payload_cwd_takes_precedence_over_process_cwd(self):
        # payload cwd = target subdir; guard PROCESS cwd = neutral temp (NOT in the target
        # chain). Discovery MUST use the payload cwd (the prior cwd-only lookup at the
        # process cwd missed the sentinel -> dormant -> pass).
        target, deep = self.setUp_target_tree()
        code, err = self._run_at_anchor(
            {"tool_name": "Bash", "tool_input": {
                "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            deep, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_subdir_anchor_in_tree_read_passes(self):
        # anchor inside the tree, Read inside the SAME target tree -> pass (the walk arms
        # the guard without over-blocking legitimate batch reads).
        target, deep = self.setUp_target_tree()
        code, _ = self._run_at_anchor(
            {"tool_name": "Read", "tool_input": {"file_path": str(target / "src" / "X.java")}},
            deep, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 0)

    def test_outside_tree_anchor_stays_dormant(self):
        # anchor = a temp dir entirely outside the target chain (opencode started
        # elsewhere): no hit on the walked chain -> dormant -> exit 0 (documented residual
        # boundary; the guard NEVER scans the drive).
        elsewhere = Path(tempfile.mkdtemp(prefix="mgh_walk_out_"))
        target, _ = self.setUp_target_tree()
        code, _ = self._run_at_anchor(
            {"tool_name": "Bash", "tool_input": {
                "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            elsewhere, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 0)

    def test_anchor_walk_bounded_16_levels(self):
        # a 17-level deep anchor with the sentinel at its root still arms the guard only if
        # the sentinel dir is within 16 ancestors. Build 20 levels; the sentinel at the top
        # root is BEYOND the bound from the deep anchor -> dormant (bounded walk, no
        # pathological deep-chain stat cost).
        root = Path(tempfile.mkdtemp(prefix="mgh_walk_deep_"))
        (root / ".mgh-init").mkdir(parents=True, exist_ok=True)
        deep = root
        for i in range(20):
            deep = deep / f"d{i:02d}"
        deep.mkdir(parents=True, exist_ok=True)
        code, _ = self._run_at_anchor(
            {"tool_name": "Bash", "tool_input": {
                "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            deep, root / ".mgh-init",
            {"domain": "mgh-init", "target": str(root), "out_roots": [], "v": 1})
        self.assertEqual(code, 0)   # beyond the 16-level bound -> not discovered

    def test_walk_hits_within_bound(self):
        # mirror: a 15-level deep anchor (within the bound) still discovers the sentinel.
        root = Path(tempfile.mkdtemp(prefix="mgh_walk_ok_"))
        (root / ".mgh-init").mkdir(parents=True, exist_ok=True)
        deep = root
        for i in range(15):
            deep = deep / f"d{i:02d}"
        deep.mkdir(parents=True, exist_ok=True)
        code, err = self._run_at_anchor(
            {"tool_name": "Bash", "tool_input": {
                "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
            deep, root / ".mgh-init",
            {"domain": "mgh-init", "target": str(root), "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("describe_artifact", err)

    def test_multi_domain_first_hit_by_precedence(self):
        # two sentinels on the same chain (sra BELOW init in _DOMAINS order wins: sast >
        # sra > srr > init): anchor under a tree carrying both -> sra dispatched.
        target, deep = self.setUp_target_tree()
        (target / ".mgh-sra").mkdir(parents=True, exist_ok=True)
        sra_sent = target / ".mgh-sra" / ".active"
        sra_sent.write_text(json.dumps(
            {"domain": "mgh-sra", "target": str(target), "out_roots": [], "v": 1}),
            encoding="utf-8")
        try:
            code, err = self._run_at_anchor(
                {"tool_name": "Bash", "tool_input": {
                    "command": 'py -c "import json; json.load(open(\'x.json\'))"'}},
                deep, target / ".mgh-init",
                {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
            self.assertEqual(code, 2)
            self.assertIn("mgh-sra", err)   # sra precedes init in _DOMAINS
        finally:
            try:
                sra_sent.unlink()
            except OSError:
                pass

    # --- the two real-world provenance shapes (proposal Why): .. chain + hallucinated
    #     prefix, judged under sentinel activation with the anchor deep in the tree ---
    def test_dotdot_chain_drive_root_overshoot_blocked(self):
        # `Read <target>\aa\bb\cc\..\..\..\..\..\..\xxxx` folds to the drive root ->
        # outside the target tree -> exit 2 + read-side recipe (the reported D-root
        # permission-prompt interrupt shape, caught BEFORE it reaches the host).
        target, deep = self.setUp_target_tree()
        chain_path = str(deep) + "\\..\\..\\..\\..\\..\\..\\xxxx"
        code, err = self._run_at_anchor(
            {"tool_name": "Read", "tool_input": {"file_path": chain_path}},
            deep, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)

    def test_hallucinated_prefix_out_of_tree_blocked(self):
        # target dir is <tmp>/acme_wing_curr_proj; the model hallucinates the underscore
        # name as a separator pair (<tmp>/acme/wing/curr_proj) -> resolves outside the
        # tree -> exit 2 (same out-of-tree judgment, no directory-name semantics).
        target = Path(tempfile.mkdtemp(prefix="acme_wing_"))
        (target / ".mgh-init").mkdir(parents=True, exist_ok=True)
        deep = target / "src"
        deep.mkdir(parents=True, exist_ok=True)
        hallucinated = str(target.parent / "acme" / "wing" / "curr_proj" / "src" / "X.java")
        code, err = self._run_at_anchor(
            {"tool_name": "Read", "tool_input": {"file_path": hallucinated}},
            deep, target / ".mgh-init",
            {"domain": "mgh-init", "target": str(target), "out_roots": [], "v": 1})
        self.assertEqual(code, 2)
        self.assertIn("target tree", err)


class TestBlockAdhocScriptsFileAssoc(unittest.TestCase):
    """Bash execution of a script-extension file via the shell's file association is blocked
    in every run-domain (defense-in-depth; the primary fix is the stage-prompt `py <abs>`
    recipe). A script-ext path used as the COMMAND BODY (PowerShell call-operator
    `& "<…>.py"`, a bare `"<…>.py"` first token, or `./x.sh`) without an explicit
    interpreter-launcher prefix is the observed Windows deadlock shape (opencode runs every
    Bash command under PowerShell -> `.py` file association -> Notepad/dialog). Operand-vs-
    arg: a script path that is only a `--flag` argument to a launched command passes."""

    def setUp(self):
        self.m = _load()

    def _bash(self, cmd, domain="init", active="1"):
        return _run_hook(self.m, {"tool_name": "Bash", "tool_input": {"command": cmd}},
                         domain=domain, active=active)

    # --- BLOCK: script-ext path as command body, no launcher prefix ---
    def test_block_pwsh_callop_py(self):
        # the observed scout deadlock shape verbatim
        code, err = self._bash(
            r'& "D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" '
            r'--out "D:\proj\.mgh-init\slices\scout\scout-003" "d:\proj\X.java"')
        self.assertEqual(code, 2)
        self.assertIn("file association", err)
        self.assertIn("py", err)            # recipe points at the explicit-launcher form

    def test_block_bare_quoted_py_as_command_body(self):
        code, _ = self._bash(r'"D:\proj\.opencode\mgh-core\scripts\chunk_sources.py" --in x')
        self.assertEqual(code, 2)

    def test_block_pwsh_callop_ps1(self):
        code, _ = self._bash(r'& "C:\scripts\setup.ps1"')
        self.assertEqual(code, 2)

    def test_block_bare_dot_slash_sh(self):
        code, _ = self._bash('./x.sh')
        self.assertEqual(code, 2)

    def test_block_bare_dot_slash_py(self):
        code, _ = self._bash('./x.py --flag 1')
        self.assertEqual(code, 2)

    def test_block_callop_no_space(self):
        code, _ = self._bash('&"x.bat"')
        self.assertEqual(code, 2)

    # --- PASS: explicit interpreter-launcher prefix -> interpreter, no file association ---
    def test_pass_py_launcher(self):
        code, _ = self._bash(r'py "D:\proj\chunk_sources.py" --in x --out y.json')
        self.assertEqual(code, 0)

    def test_pass_python_launcher(self):
        code, _ = self._bash(r'python "D:\proj\chunk_sources.py" --in x')
        self.assertEqual(code, 0)

    def test_pass_python3_launcher(self):
        code, _ = self._bash(r'python3 "D:\proj\chunk_sources.py" --in x')
        self.assertEqual(code, 0)

    def test_pass_bash_launcher(self):
        code, _ = self._bash('bash "x.sh"')
        self.assertEqual(code, 0)

    def test_pass_pwsh_file_launcher(self):
        code, _ = self._bash('pwsh -File "x.ps1"')
        self.assertEqual(code, 0)

    def test_pass_powershell_file_launcher(self):
        code, _ = self._bash('powershell -File "x.ps1"')
        self.assertEqual(code, 0)

    def test_pass_cmd_c_launcher(self):
        code, _ = self._bash('cmd /c "x.bat"')
        self.assertEqual(code, 0)

    # --- operand-vs-arg: a script path that is only a --flag argument is NOT blocked ---
    def test_pass_script_path_as_flag_arg(self):
        # `py discover.py --in <other>.py` -- the .py is an arg, not the command body
        code, _ = self._bash(r'py "D:\proj\discover.py" --in "D:\other.py"')
        self.assertEqual(code, 0)

    def test_pass_legit_leaf_with_py_launcher(self):
        code, _ = self._bash(
            "py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init")
        self.assertEqual(code, 0)

    # --- clause isolation: a trailing .py in a later clause does not false-trip ---
    def test_pass_trailing_py_after_semicolon(self):
        code, _ = self._bash('py x.py; echo done.py')
        self.assertEqual(code, 0)

    # --- inactive session: no Bash scan at all (same as every other rule) ---
    def test_pass_inactive_session(self):
        code, _ = self._bash('& "x.py"', active="")
        self.assertEqual(code, 0)

    # --- cross-domain: the rule fires identically in every run-domain ---
    def test_block_sast_domain(self):
        code, err = self._bash(r'& "D:\proj\chunk_sources.py" --in x', domain="sast")
        self.assertEqual(code, 2)
        self.assertIn("mgh-sast", err)


class TestWriteSideConfinement(unittest.TestCase):
    """Write/delete/redirect/tool-face confinement (harden-mgh-write-confinement) — the mutation
    surface's deterministic closure, symmetric to the read side. Three surfaces, one detection
    mode (verb set / tool id + absolute-path token scan + is_relative_to(target) + cwd anchor):
      - Bash write/delete verbs (New-Item/Set-Content/mkdir/Copy-Item/Move-Item/tee/Remove-Item/…)
        invoked directly in Bash to bypass the native Write/Edit tool's confinement (W1/W3);
      - non-temp out-of-tree `>`/`>>` redirect (W2);
      - the tool face: claude MultiEdit/NotebookEdit (T2/T3) + opencode apply_patch (T1).
    Plus P1 (init/ut-init in-tree Bash write must land in a sanctioned subtree — root pollution)
    and L1 (rule-a relabel: `py -c` write shape with an out-of-tree path => write recipe, NOT
    introspection). target absent => degrade to pass; inactive session => silent pass."""

    def setUp(self):
        self.m = _load()

    _PARENT = r"D:\parent"
    _SONA = r"D:\parent\sonA"
    _SONB = r"D:\parent\sonB"
    _OUT = r"D:\out"

    def _bash(self, cmd, domain="init", target=None, cwd=None, active="1"):
        """Run a Bash payload in a run-domain with MGH_TARGET pinned (+ sibling-domain env
        isolated). target=None simulates the degrade path; cwd=None => a fresh temp dir outside
        sonA (for the D4 cwd-drift assertions). Returns (code, stderr)."""
        key = _DOMAIN_ENV[domain]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != domain]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = active
        if target is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = target
        cwd_tmp = cwd or tempfile.mkdtemp(prefix="mgh_wcwd_")
        old_cwd, old_stdin = os.getcwd(), sys.stdin
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            os.chdir(cwd_tmp)
            sys.stdin = io.StringIO(json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": cmd}}))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.chdir(old_cwd)
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        return code, err.getvalue()

    def _tool(self, payload, domain="init", target=None):
        key = _DOMAIN_ENV[domain]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != domain]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = "1"
        os.environ["MGH_TARGET"] = target
        old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        return code, err.getvalue()

    # --- W1: Bash write verbs out-of-tree -> block ---
    def test_block_set_content_out_of_tree(self):
        code, err = self._bash(f'Set-Content {self._OUT}\\f.json "x"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)

    def test_block_new_item_out_of_tree(self):
        code, _ = self._bash(f'New-Item -ItemType File -Path {self._OUT}\\f.json -Force',
                             target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_mkdir_out_of_tree(self):
        code, _ = self._bash(f'mkdir {self._OUT}\\d', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_out_file_out_of_tree(self):
        code, _ = self._bash(f'"x" | Out-File {self._OUT}\\f.json', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_tee_out_of_tree(self):
        code, _ = self._bash(f'echo x | tee {self._OUT}\\f.json', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_add_content_out_of_tree(self):
        code, _ = self._bash(f'Add-Content {self._OUT}\\f.json "x"', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_copy_item_dest_out_of_tree(self):
        # Copy-Item: source in-tree is fine; the DESTINATION (LAST abs token) is out-of-tree -> block.
        code, _ = self._bash(f'Copy-Item {self._SONA}\\x.java {self._OUT}\\', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_copy_item_dest_out_of_tree_even_if_source_out(self):
        code, _ = self._bash(f'Copy-Item {self._SONB}\\x.java {self._OUT}\\y.java',
                             target=self._SONA)
        self.assertEqual(code, 2)

    def test_copy_item_in_tree_dest_passes(self):
        # destination in a sanctioned subtree (init allowlist) -> passes.
        code, _ = self._bash(f'Copy-Item {self._SONA}\\x.java {self._SONA}\\.mgh-init\\y.java',
                             target=self._SONA)
        self.assertEqual(code, 0)

    def test_block_set_content_cwd_outside_d4(self):
        # no explicit path -> destination defaults to cwd; cwd is a temp dir outside sonA (D4).
        code, err = self._bash('Set-Content evil.txt "x"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)

    def test_in_tree_sanctioned_set_content_passes(self):
        code, _ = self._bash(f'Set-Content {self._SONA}\\.mgh-init\\report\\out.json "x"',
                             target=self._SONA)
        self.assertEqual(code, 0)

    def test_non_write_verb_with_path_arg_passes(self):
        # `py … --out x.json` is NOT a write verb (the path is a --flag arg) -> NOT a write-verb hit.
        code, _ = self._bash(f'py discover.py --out {self._SONA}\\.mgh-init\\x.json',
                             target=self._SONA)
        self.assertEqual(code, 0)

    # --- W3: destructive delete verbs out-of-tree -> block (delete-side recipe) ---
    def test_block_remove_item_sibling(self):
        code, err = self._bash(f'Remove-Item {self._SONB} -Recurse -Force', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree delete", err)
        self.assertIn("irreversible", err.lower())  # delete-side recipe calls out irreversibility
        self.assertIn("sibling", err)

    def test_block_rm_rf_out_of_tree(self):
        code, err = self._bash(f'rm -rf {self._OUT}', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree delete", err)

    def test_block_rmdir_out_of_tree(self):
        code, _ = self._bash(f'rmdir {self._OUT}\\d', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_pyc_shutil_rmtree_out_of_tree(self):
        # interpreter-indirect delete (rule-a relabel): shutil.rmtree + out-of-tree path -> delete.
        code, err = self._bash('py -c "import shutil; shutil.rmtree(\'D:/out\')"',
                               target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree delete", err)

    # --- W2: non-temp out-of-tree redirect -> block ---
    def test_block_redirect_out_of_tree(self):
        code, err = self._bash(f'echo x > {self._OUT}\\f.json', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree redirect", err)

    def test_block_append_redirect_out_of_tree(self):
        code, _ = self._bash(f'echo x >> {self._OUT}\\f.json', target=self._SONA)
        self.assertEqual(code, 2)

    def test_block_redirect_in_tree_root_p1(self):
        # in-tree but at the target root, outside the sanctioned subtrees -> init allowlist blocks.
        code, err = self._bash(f'echo x > {self._SONA}\\evil.txt', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_redirect_sanctioned_subtree_passes(self):
        code, _ = self._bash(f'echo x > {self._SONA}\\.mgh-init\\report\\out.json',
                             target=self._SONA)
        self.assertEqual(code, 0)

    def test_redirect_temp_readback_still_blocked(self):
        # the retained temp-I/O rule (temp write + read-back) fires independent of the redirect rule.
        code, _ = self._bash(r'py x.py > /tmp/x.json; cat /tmp/x.json', target=self._SONA)
        self.assertEqual(code, 2)

    # --- P1: in-tree Bash write confined to sanctioned subtrees (init/ut-init) ---
    def test_block_set_content_in_tree_root_pollution(self):
        code, err = self._bash(f'Set-Content {self._SONA}\\evil.txt "x"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_set_content_sanctioned_subtree_passes(self):
        code, _ = self._bash(f'Set-Content {self._SONA}\\.mgh-init\\report\\out.json "x"',
                             target=self._SONA)
        self.assertEqual(code, 0)

    def test_sast_in_tree_bash_write_passes(self):
        # sast has NO positive allowlist (only the out-of-tree check) -> in-tree write passes.
        code, _ = self._bash(f'Set-Content {self._SONA}\\src\\notes.txt "x"',
                             domain="sast", target=self._SONA)
        self.assertEqual(code, 0)

    def test_sast_out_of_tree_bash_write_blocked(self):
        code, _ = self._bash(f'Set-Content {self._OUT}\\f.json "x"',
                             domain="sast", target=self._SONA)
        self.assertEqual(code, 2)

    # --- T2/T3: claude MultiEdit / NotebookEdit enter the write-confinement branch ---
    def test_multiedit_out_of_tree_blocked(self):
        # init domain: out-of-tree falls outside every sanctioned subtree -> allowlist message.
        code, err = self._tool({"tool_name": "MultiEdit", "tool_input": {
            "file_path": self._OUT + r"\f.json"}}, target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_multiedit_sast_out_of_tree_blocked(self):
        # sast domain (no allowlist): out-of-tree -> the MGH_TARGET tree message.
        code, err = self._tool({"tool_name": "MultiEdit", "tool_input": {
            "file_path": self._OUT + r"\f.json"}}, domain="sast", target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_notebookedit_out_of_tree_blocked(self):
        code, err = self._tool({"tool_name": "NotebookEdit", "tool_input": {
            "notebook_path": self._OUT + r"\nb.ipynb"}}, target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)

    def test_notebookedit_not_script_ext_in_tree_root_blocked_only_by_tree(self):
        # .ipynb is NOT a script-ext (artifact); in-tree root for init hits the allowlist, NOT the
        # script-ext block — proves .ipynb is confined by tree location only, not by extension.
        code, err = self._tool({"tool_name": "NotebookEdit", "tool_input": {
            "notebook_path": self._SONA + r"\nb.ipynb"}}, target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("sanctioned init subtrees", err)            # allowlist hit (not script-ext)
        self.assertNotIn("Write/Edit of a script", err)           # NOT the script-ext block

    def test_multiedit_in_tree_sanctioned_passes(self):
        code, _ = self._tool({"tool_name": "MultiEdit", "tool_input": {
            "file_path": self._SONA + r"\.claude\rules\auth.md"}}, target=self._SONA)
        self.assertEqual(code, 0)

    def test_notebookedit_in_tree_sanctioned_passes(self):
        code, _ = self._tool({"tool_name": "NotebookEdit", "tool_input": {
            "notebook_path": self._SONA + r"\.mgh-init\nb.ipynb"}}, target=self._SONA)
        self.assertEqual(code, 0)

    # --- T1: ApplyPatch (opencode) confined path-by-path ---
    def test_applypatch_out_of_tree_add_blocked(self):
        code, err = self._tool({"tool_name": "ApplyPatch", "tool_input": {
            "paths": [self._OUT + r"\evil.ps1"], "operations": ["add"]}}, target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("ApplyPatch", err)

    def test_applypatch_out_of_tree_delete_delete_wording(self):
        code, err = self._tool({"tool_name": "ApplyPatch", "tool_input": {
            "paths": [self._SONB + r"\x.java"], "operations": ["delete"]}}, target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("irreversible", err.lower())  # delete operation => delete-side wording

    def test_applypatch_in_tree_sanctioned_passes(self):
        code, _ = self._tool({"tool_name": "ApplyPatch", "tool_input": {
            "paths": [self._SONA + r"\.mgh-init\x.json"], "operations": ["add"]}},
            target=self._SONA)
        self.assertEqual(code, 0)

    def test_applypatch_any_path_out_of_tree_blocked(self):
        # ANY path in the patch out-of-tree => block (even if another is in-tree).
        code, _ = self._tool({"tool_name": "ApplyPatch", "tool_input": {
            "paths": [self._SONA + r"\.mgh-init\a.json", self._OUT + r"\b.json"],
            "operations": ["add", "add"]}}, target=self._SONA)
        self.assertEqual(code, 2)

    # --- L1: rule-a relabel (py -c write shape => write recipe, NOT introspection) ---
    def test_pyc_write_out_of_tree_write_recipe(self):
        code, err = self._bash('py -c "open(\'D:/out/f\',\'w\').write(\'x\')"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)
        self.assertNotIn("introspection", err)    # write recipe, NOT the introspection recipe

    def test_pyc_makedirs_out_of_tree_blocked(self):
        # pure out-of-tree write (no introspection token at all) -> now caught (was a hole).
        code, err = self._bash('py -c "import os; os.makedirs(\'D:/out/d\')"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)

    def test_pyc_introspection_still_introspection_recipe(self):
        # legit introspection (read .json) still surfaces the introspection recipe (unchanged).
        code, err = self._bash('py -c "import json; json.load(open(\'x.json\'))"', target=self._SONA)
        self.assertEqual(code, 2)
        self.assertIn("introspection", err)

    # --- degrade + inactive ---
    def test_write_degrades_without_target(self):
        # active run-domain but MGH_TARGET unset -> write side degrades to pass.
        code, _ = self._bash(f'Set-Content {self._OUT}\\f.json "x"', target=None)
        self.assertEqual(code, 0)

    def test_inactive_session_passes_write(self):
        code, _ = self._bash(f'Set-Content {self._OUT}\\f.json "x"',
                             target=self._SONA, active="")
        self.assertEqual(code, 0)


class _RealTreeBashMixin:
    """Shared runner for the three new-rule test classes: builds REAL temp target/sibling
    trees (the rules chdir + Path.exists() judge real disk), pins MGH_TARGET, isolates
    sibling-domain env, and restores cwd/env. Returns (code, stderr)."""

    def _setup(self):
        self.m = _load()
        self.sona = Path(tempfile.mkdtemp(prefix="mgh_sona_"))
        self.sonb = Path(tempfile.mkdtemp(prefix="mgh_sonb_"))
        self.neutral = tempfile.mkdtemp(prefix="mgh_neutral_")
        (self.sona / "src").mkdir()

    def _teardown(self):
        import shutil
        shutil.rmtree(self.sona, ignore_errors=True)
        shutil.rmtree(self.sonb, ignore_errors=True)

    def _bash(self, cmd, target=None, cwd=None, active="1"):
        """target=None => degrade path (MGH_TARGET unset); cwd=None => the neutral temp dir
        (outside sona — the cwd-drift judge for bare verbs / relative refs)."""
        key = _DOMAIN_ENV["init"]
        sibs = [v for d, v in _DOMAIN_ENV.items() if d != "init"]
        old_sib = {s: os.environ.pop(s, None) for s in sibs}
        old_active = os.environ.get(key)
        old_target = os.environ.get("MGH_TARGET")
        os.environ[key] = active
        if target is None:
            os.environ.pop("MGH_TARGET", None)
        else:
            os.environ["MGH_TARGET"] = str(target)
        old_cwd, old_stdin = os.getcwd(), sys.stdin
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            os.chdir(cwd or self.neutral)
            sys.stdin = io.StringIO(json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": cmd}}))
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.stdin = old_stdin
            os.chdir(old_cwd)
            os.environ.pop(key, None) if old_active is None else os.environ.__setitem__(key, old_active)
            os.environ.pop("MGH_TARGET", None) if old_target is None else os.environ.__setitem__("MGH_TARGET", old_target)
            for s, v in old_sib.items():
                if v is not None:
                    os.environ[s] = v
        return code, err.getvalue()


class TestListingConfinement(unittest.TestCase, _RealTreeBashMixin):
    """Bash directory-listing escape route (rule j, harden-mgh-guard-listing-exec-confinement):
    ls/dir/Get-ChildItem/gci leading a simple command with an out-of-tree scope (explicit
    absolute-path argument, or no explicit path with the cwd outside the tree) is blocked —
    the enumeration peer of the file-search rule. In-tree listing, bare `ls` with an in-tree
    cwd, and no-target sessions pass. The observed real-machine shape: `ls /home` / `ls
    /adhome` hunting for prompts/scripts after a 404."""

    def setUp(self):
        self._setup()

    def tearDown(self):
        self._teardown()

    # --- BLOCK: out-of-tree listing ---
    def test_block_ls_home(self):
        code, err = self._bash("ls /home", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("directory listing", err)

    def test_block_ls_adhome(self):
        code, _ = self._bash("ls /adhome", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_ls_sibling_abs(self):
        code, _ = self._bash(f"ls {self.sonb}", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_get_childitem_drive(self):
        code, _ = self._bash("Get-ChildItem D:/", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_gci_sibling(self):
        code, _ = self._bash(f"gci {self.sonb}" + chr(92) + "src", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_ls_posix_deep(self):
        code, _ = self._bash("ls /adhome/xxx/gitlab_pab", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_ls_cwd_outside_no_path(self):
        # no explicit path -> cwd anchor; the neutral temp cwd is outside sona (D4 mirror).
        code, _ = self._bash("ls -la", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_ls_after_delimiter(self):
        code, _ = self._bash(f"py x.py --in a.java; ls {self.sonb}", target=self.sona,
                             cwd=self.sona)
        self.assertEqual(code, 2)

    def test_block_dir_dotdot_climb(self):
        # a relative argument whose cwd-relative resolution climbs outside the tree.
        code, err = self._bash("dir " + ".." + chr(92) + "..", target=self.sona,
                               cwd=self.sona / "src")
        self.assertEqual(code, 2)
        self.assertIn("directory listing", err)

    # --- PASS: in-tree / degrade / inactive ---
    def test_pass_ls_in_tree_relative(self):
        code, _ = self._bash("ls src", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_pass_ls_in_tree_abs(self):
        code, _ = self._bash("ls " + str(self.sona / "src"), target=self.sona)
        self.assertEqual(code, 0)

    def test_pass_bare_ls_cwd_in_tree(self):
        code, _ = self._bash("ls", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_pass_ls_flag_in_tree(self):
        code, _ = self._bash("ls -la " + str(self.sona / ".mgh-init"), target=self.sona)
        self.assertEqual(code, 0)

    def test_degrades_without_target(self):
        code, _ = self._bash("ls /home", target=None)
        self.assertEqual(code, 0)

    def test_inactive_session_passes(self):
        code, _ = self._bash("ls /home", target=self.sona, active="")
        self.assertEqual(code, 0)

    def test_pass_dir_inside_token_not_leading(self):
        # `dir` inside a non-leading token does NOT trip (verb is anchored at first-token
        # / delimiter position only).
        code, _ = self._bash("py x.py --textdir src", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)


class TestInterpreterExecConfinement(unittest.TestCase, _RealTreeBashMixin):
    """Bash interpreter out-of-tree execution (rule k): py/py3/python/python3/python2 running
    a script that resolves OUTSIDE the target tree is blocked — the explicit launcher prefix
    exempts the file-association rule, so the executed script's LOCATION is judged here.
    `--flag <path>` values are data paths, never the executed script; `py -c`/`-m` bodies are
    governed by the introspection/write-relabel rules; relative script paths are not judged."""

    def setUp(self):
        self._setup()

    def tearDown(self):
        self._teardown()

    # --- BLOCK: interpreter + out-of-tree script ---
    def test_block_py_home_script(self):
        code, err = self._bash("py /home/x/run.py", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree script", err)

    def test_block_python3_tilde_script(self):
        code, _ = self._bash("python3 ~/tools/scan.py", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_python_abs_sibling_script(self):
        code, _ = self._bash("python " + str(self.sonb / "tools" / "scan.py"),
                             target=self.sona)
        self.assertEqual(code, 2)

    def test_block_py_after_delimiter(self):
        code, _ = self._bash("ls src; py /home/x/run.py", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)

    # --- PASS: in-tree / flag-value / -c / relative / degrade ---
    def test_pass_installed_resume_state(self):
        # the canonical sanctioned invocation: with mgh-core actually installed under the
        # target, the stop-all rule (rule l) passes AND the interpreter rule judges the
        # script arg in-tree (relative form) -> pass.
        inst = self.sona / ".claude" / "mgh-core" / "scripts"
        inst.mkdir(parents=True)
        (inst / "resume_state.py").write_text("x", encoding="utf-8")
        code, _ = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                             target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_pass_in_tree_abs_script(self):
        code, _ = self._bash("py " + str(self.sona / ".mgh-init" / "tools" / "x.py") +
                             " --in a.json", target=self.sona)
        self.assertEqual(code, 0)

    def test_block_flag_value_out_of_tree_caught_by_net(self):
        # `--clusters <out-of-tree>` is a DATA path, never the executed script — rule k still
        # does not judge it, but the catch-all net now does (D5: accepted new block).
        code, err = self._bash("py x.py --clusters " + str(self.sonb / "c.json"),
                               target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)
        self.assertNotIn("out-of-tree script", err)   # rule k's own stance survives

    def test_block_flag_value_skipped_then_in_tree_script(self):
        # the flag value itself is out-of-tree: the net blocks the command even though the
        # executed script is in-tree (the net judges EVERY token, not just the script).
        code, err = self._bash("py x.py --clusters " + str(self.sonb / "c.json") + " " +
                               str(self.sona / "run.py"), target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)
        self.assertNotIn("out-of-tree script", err)

    def test_pyc_body_not_judged_here(self):
        # `py -c` has no script-extension positional argument: this rule does not fire; the
        # existing introspection rule owns the body (assert its recipe surfaces instead).
        code, err = self._bash("py -c \"import json; json.load(open('x.json'))\"",
                               target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("introspection", err)
        self.assertNotIn("out-of-tree script", err)

    def test_pass_relative_script_not_judged(self):
        # relative script paths are not location-judged (observed-shape stance).
        code, _ = self._bash("py ./local_helper.py", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_degrades_without_target(self):
        code, _ = self._bash("py /home/x/run.py", target=None)
        self.assertEqual(code, 0)

    def test_inactive_session_passes(self):
        code, _ = self._bash("py /home/x/run.py", target=self.sona, active="")
        self.assertEqual(code, 0)

    def test_pass_pwsh_file_launcher_unchanged(self):
        # pwsh -File keeps passing the file-association rule (unchanged), and non-interpreter
        # leading verbs never enter this rule.
        code, _ = self._bash("pwsh -File x.ps1", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)


class TestMghCoreMissingInstall(unittest.TestCase, _RealTreeBashMixin):
    """mgh-core missing-install stop-all (rule l, terminal state — checked BEFORE every other
    Bash rule): a command referencing an mgh-core/scripts script-extension path that is ABSENT
    on disk (cwd- AND target-relative) or exists OUTSIDE the tree (another project's install)
    => exit 2 + the stop-all recipe. Installed in-tree references pass; non-mgh-core missing
    paths never trip; existing rules' recipes are unaffected by the new first-position check
    (order regression)."""

    def setUp(self):
        self._setup()

    def tearDown(self):
        self._teardown()

    # --- BLOCK: missing install (stop-all recipe wording) ---
    def test_block_absent_mgh_core_script(self):
        # no mgh-core anywhere: cwd-relative AND target-relative resolution both miss.
        code, err = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                               target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("STOP ALL TASKS", err)
        self.assertIn("install", err.lower())
        self.assertIn("NEVER search other directories", err)

    def test_block_out_of_tree_mgh_core_reference(self):
        # mgh-core exists only in the SIBLING project (the root-project-only install shape):
        # the reference resolves outside the target tree -> stop-all.
        foreign = self.sonb / ".claude" / "mgh-core" / "scripts"
        foreign.mkdir(parents=True)
        (foreign / "resume_state.py").write_text("x", encoding="utf-8")
        code, err = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                               target=self.sona, cwd=self.sonb)
        self.assertEqual(code, 2)
        self.assertIn("STOP ALL TASKS", err)

    def test_block_absent_mgh_core_sh_reference(self):
        # any script extension under mgh-core/scripts trips (not just .py).
        code, err = self._bash("bash .opencode/mgh-core/scripts/helper.sh",
                               target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("STOP ALL TASKS", err)

    # --- PASS: installed / non-mgh-core / -c exclusion / degrade ---
    def test_pass_installed_in_tree_reference(self):
        inst = self.sona / ".claude" / "mgh-core" / "scripts"
        inst.mkdir(parents=True)
        (inst / "resume_state.py").write_text("x", encoding="utf-8")
        code, _ = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                             target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_pass_non_mgh_core_missing_path(self):
        # arbitrary in-tree user scripts are the caller's concern, not the guard's.
        code, _ = self._bash("py ./local_helper.py", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_pass_pyc_body_with_mgh_core_token(self):
        # `py -c` bodies are excluded (rules a/h own them) — the introspection recipe surfaces.
        code, err = self._bash("py -c \"print(open('.claude/mgh-core/scripts/x.py').read())\"",
                               target=self.sona)
        self.assertEqual(code, 2)   # introspection rule fires (open( token)
        self.assertIn("introspection", err)
        self.assertNotIn("STOP ALL TASKS", err)

    def test_degrades_without_target(self):
        code, _ = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                             target=None, cwd=self.sona)
        self.assertEqual(code, 0)

    def test_inactive_session_passes(self):
        code, _ = self._bash("py .claude/mgh-core/scripts/resume_state.py --target .",
                             target=self.sona, cwd=self.sona, active="")
        self.assertEqual(code, 0)

    # --- order regression: existing rules' hits are unaffected by the new first-position rule ---
    def test_order_introspection_recipe_unaffected(self):
        code, err = self._bash("py -c \"import json; json.load(open('x.json'))\"",
                               target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("introspection", err)
        self.assertNotIn("STOP ALL TASKS", err)

    def test_order_file_search_recipe_unaffected(self):
        code, err = self._bash(f"rg x {self.sonb}", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("file search", err)
        self.assertNotIn("STOP ALL TASKS", err)

    def test_order_aggregate_read_recipe_unaffected(self):
        code, err = self._bash("cat .mgh-init/clusters.json", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("input_path", err)
        self.assertNotIn("STOP ALL TASKS", err)


class TestBashPathAllowset(unittest.TestCase, _RealTreeBashMixin):
    """Rule m — the verb-independent fail-closed net (harden-mgh-bash-path-allowlist):
    EVERY path-like token in a Bash command must resolve inside the unified read allow-set
    (MGH_TARGET ∪ sentinel read_roots[] ∪ project config read_roots[]), regardless of which
    verb (if any) leads the command. Closes the enumeration-table escape class (robocopy /
    Get-Content / curl -o / Expand-Archive / …) that previously passed. Mutation rules run
    FIRST (write-shaped hits surface their write recipe); no path token => pass; unpinned
    target => degrade to pass (other rules still fire); URL tokens, bare `~`, and bare `..`
    are not judged."""

    def setUp(self):
        self._setup()

    def tearDown(self):
        self._teardown()

    # --- BLOCK: table-escape verbs with out-of-tree tokens ---
    def test_block_robocopy_out_of_tree_dest(self):
        # `robocopy` is in NO verb enumeration table — previously passed wholesale.
        code, err = self._bash(f"robocopy {self.sona}\\docs {self.sonb}\\backup",
                               target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)
        self.assertIn("read-roots.json", err)

    def test_block_get_content_out_of_tree_file(self):
        # plain read verb (not search/listing) — previously passed every rule.
        code, err = self._bash(f"Get-Content {self.sonb}\\notes.json", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)

    def test_block_type_dotdot_climb(self):
        # `..`-leading token resolved against the guard cwd climbs out of the tree.
        code, err = self._bash("type " + ".." + chr(92) + ".." + chr(92) + "secret.txt",
                               target=self.sona, cwd=self.sona / "src")
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)

    def test_block_tilde_path(self):
        # `~/`-leading token expands to the user profile — outside any allow root.
        code, _ = self._bash("cat ~/secrets.txt", target=self.sona)
        self.assertEqual(code, 2)

    def test_block_posix_abs(self):
        code, err = self._bash("cat /etc/passwd", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("read allow-set", err)

    def test_block_quoted_out_of_tree_token(self):
        # quoted tokens are judged too (quotes stripped by the extractor).
        code, _ = self._bash("rg pattern \"" + str(self.sonb / "src") + "\"",
                             target=self.sona, cwd=self.sona)
        self.assertEqual(code, 2)

    # --- PASS: in-tree / not-a-token / degrade / other-rules-first ---
    def test_pass_all_in_tree_tokens(self):
        inst = self.sona / ".claude" / "mgh-core" / "scripts"
        inst.mkdir(parents=True)
        (inst / "list_clusters.py").write_text("x", encoding="utf-8")
        (self.sona / ".mgh-init").mkdir()
        (self.sona / ".mgh-init" / "clusters.json").write_text("[]", encoding="utf-8")
        code, err = self._bash("py .claude/mgh-core/scripts/list_clusters.py --clusters " +
                               str(self.sona / ".mgh-init" / "clusters.json"),
                               target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0, err)

    def test_pass_url_token_excluded(self):
        # `https://…` must not yield a false `s:/…` path fragment (URL-scheme exclusion) —
        # with mgh-core installed in-tree, rule l passes and the net sees no path token.
        inst = self.sona / ".claude" / "mgh-core" / "scripts"
        inst.mkdir(parents=True)
        (inst / "tool.py").write_text("x", encoding="utf-8")
        code, err = self._bash("py .claude/mgh-core/scripts/tool.py --doc https://example.com/a/b",
                               target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0, err)

    def test_pass_bare_tilde_and_dotdot(self):
        # bare `~` and bare `..` are NOT path tokens (the verb rules own cwd judgments).
        code, err = self._bash("cd ~; cd ..", target=self.sona, cwd=self.sona)
        self.assertEqual(code, 0, err)

    def test_pass_no_path_token(self):
        code, err = self._bash("echo hello world", target=self.sona)
        self.assertEqual(code, 0, err)

    def test_degrades_without_target(self):
        code, _ = self._bash("cat /etc/passwd", target=None)
        self.assertEqual(code, 0)

    def test_no_target_other_rules_still_fire(self):
        # unpinned target degrades ONLY the path net; the introspection rule is path-free.
        code, err = self._bash("py -c \"import json; json.load(open('x.json'))\"", target=None)
        self.assertEqual(code, 2)
        self.assertIn("introspection", err)

    def test_mutation_rule_still_wins_before_net(self):
        # a known write verb to an out-of-tree destination surfaces the WRITE recipe,
        # never the read-net recipe (D2: mutation rules run first).
        code, err = self._bash(f"Set-Content {self.sonb}\\evil.txt x", target=self.sona)
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)
        self.assertNotIn("read allow-set", err)


class TestReadRootsConfig(unittest.TestCase):
    """Project read-roots config <target>/.mgh/read-roots.json (harden-mgh-bash-path-
    allowlist): extends the unified read allow-set in EVERY run-domain, alongside the
    sentinel's read_roots[] (union). READ-ONLY on both faces (tool + Bash); the write side
    keeps judging MGH_TARGET alone. Fail-closed: missing file = unchanged behavior;
    malformed JSON / wrong-typed read_roots = zero grants, no crash; each entry needs
    exist-and-is-dir containment (a missing entry grants zero); unknown fields ignored."""

    def setUp(self):
        self.m = _load()

    def _setup_trees(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_cfg_tgt_"))
        shared = Path(tempfile.mkdtemp(prefix="mgh_cfg_shared_"))
        other = Path(tempfile.mkdtemp(prefix="mgh_cfg_other_"))
        (shared / "specs").mkdir(parents=True, exist_ok=True)
        (shared / "specs" / "auth.md").write_text("# spec", encoding="utf-8")
        (other / "f.txt").write_text("x", encoding="utf-8")
        (target / "in_tree.json").write_text("{}", encoding="utf-8")
        return target, shared, other

    def _sentinel(self, target, extra_roots=()):
        roots = [str(r) for r in extra_roots]
        return {"domain": "mgh-sast", "target": str(target),
                "out_roots": [], "read_roots": roots, "v": 1}

    def _write_config(self, target, body):
        cfg = target / ".mgh"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "read-roots.json").write_text(body, encoding="utf-8")

    def test_config_root_read_and_bash_rg_pass(self):
        target, shared, _ = self._setup_trees()
        self._write_config(target, json.dumps({"v": 1, "read_roots": [str(shared)]}))
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0, err)
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {"command": f"rg token {shared}\\specs"}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0, err)

    def test_write_into_config_root_blocked(self):
        target, shared, _ = self._setup_trees()
        self._write_config(target, json.dumps({"v": 1, "read_roots": [str(shared)]}))
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Write", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 2)
        self.assertIn("MGH_TARGET tree", err)

    def test_malformed_json_fail_closed_no_crash(self):
        target, shared, other = self._setup_trees()
        self._write_config(target, "{not valid json")
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 2)          # config root grants NOTHING when malformed
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(target / "in_tree.json")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0)          # in-tree judgments unaffected (no crash)

    def test_wrong_typed_read_roots_grants_zero(self):
        target, shared, _ = self._setup_trees()
        self._write_config(target, json.dumps({"v": 1, "read_roots": "not-a-list"}))
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 2)

    def test_missing_config_unchanged_behavior(self):
        target, shared, other = self._setup_trees()
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 2)          # no config => out-of-tree read blocked as before
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(target / "in_tree.json")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0)

    def test_config_union_with_sentinel_roots(self):
        target, shared, other = self._setup_trees()
        front = Path(tempfile.mkdtemp(prefix="mgh_cfg_front_"))
        (front / "x.js").write_text("// f", encoding="utf-8")
        self._write_config(target, json.dumps({"v": 1, "read_roots": [str(shared)]}))
        sent = self._sentinel(target, extra_roots=[front])
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", sent)
        self.assertEqual(code, 0, err)     # config-declared root
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(front / "x.js")}},
            "sast", sent)
        self.assertEqual(code, 0, err)     # sentinel-declared root — the union holds
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(other / "f.txt")}},
            "sast", sent)
        self.assertEqual(code, 2)          # sanity: everything else stays closed

    def test_nonexistent_config_entry_grants_zero(self):
        target, shared, _ = self._setup_trees()
        gone = shared.parent / "gone_shared"
        self._write_config(target, json.dumps({"v": 1, "read_roots": [str(gone)]}))
        code, _ = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 2)

    def test_unknown_fields_ignored(self):
        target, shared, _ = self._setup_trees()
        self._write_config(target, json.dumps(
            {"v": 1, "read_roots": [str(shared)], "approved_by": "user", "future": [1]}))
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Read", "tool_input": {"file_path": str(shared / "specs" / "auth.md")}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0, err)

    def test_residual_unknown_writeverb_into_declared_root_passes_net(self):
        # D6 residual boundary, pinned as documented behavior: an UNKNOWN write verb
        # targeting a declared read-only root passes the net (the token is inside the read
        # allow-set; the mutation rules do not recognize the verb). The sdr approval-flow
        # change governs this; disclosed in the honest-boundary docs.
        target, shared, _ = self._setup_trees()
        self._write_config(target, json.dumps({"v": 1, "read_roots": [str(shared)]}))
        code, err = _run_with_sentinel(self.m,
            {"tool_name": "Bash", "tool_input": {"command": f"somecmd --out {shared}\\x.txt"}},
            "sast", self._sentinel(target))
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
