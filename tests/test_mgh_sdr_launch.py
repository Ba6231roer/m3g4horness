#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Launcher self-test for mgh_sdr_launch.py (add-mgh-sdr task 5.2).

Builds a TEMP git pair (main repo with a feature branch + a fake external frontend repo),
runs the launcher with --dry-run (ZERO host-CLI spawn), and asserts the artifacts:
gates pass, sdr_context artifacts (baseline/external conclusions/context.json) exist,
the sentinel is written with read_roots[] = the searched external root, the orchestrator
prompt file carries the verbatim absolute paths, and --dry-run KEEPS the sentinel.
Also covers misuse gates: missing --repo (2), non-git repo (2), unknown --host (2),
missing multi-branch file (2), inline branch-list misuse (empty item / --multi-branch
conflict, both 2).

Run: py tests/test_mgh_sdr_launch.py
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAUNCH = HERE.parent / "core" / "scripts" / "mgh_sdr_launch.py"


def _git(repo: Path, *args: str):
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _commit_all(repo: Path, msg: str):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


class TestLauncherGates(unittest.TestCase):
    """Misuse gates fail-loud with exit 2 + recipe."""

    def setUp(self):
        self.m = _load()

    def _main(self, argv):
        old_argv = sys.argv
        sys.argv = ["mgh_sdr_launch.py"] + argv
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        except SystemExit as e:  # argparse misuse exits directly
            code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue(), err.getvalue()

    def test_missing_repo_exits_2(self):
        code, _, err = self._main([])
        self.assertEqual(code, 2)
        self.assertIn("--repo", err)

    def test_non_git_repo_exits_2(self):
        d = tempfile.mkdtemp(prefix="mgh_launch_nogit_")
        code, _, err = self._main(["--repo", d])
        self.assertEqual(code, 2)
        self.assertIn("git", err.lower())

    def test_unknown_host_exits_2(self):
        d = tempfile.mkdtemp(prefix="mgh_launch_host_")
        _init_repo(Path(d))
        code, _, err = self._main(["--repo", d, "--host", "no-such-cli"])
        self.assertEqual(code, 2)

    def test_missing_host_cli_exits_2(self):
        # neither opencode nor claude on PATH in the test sandbox PATH subset: simulate
        # by pointing PATH at an empty dir.
        d = tempfile.mkdtemp(prefix="mgh_launch_nohost_")
        _init_repo(Path(d))
        old_path = os.environ.get("PATH")
        os.environ["PATH"] = ""
        try:
            code, _, err = self._main(["--repo", d])
            self.assertEqual(code, 2)
            self.assertIn("host", err.lower())
        finally:
            if old_path is not None:
                os.environ["PATH"] = old_path

    def test_missing_multi_branch_file_exits_2(self):
        d = tempfile.mkdtemp(prefix="mgh_launch_mb_")
        _init_repo(Path(d))
        code, _, err = self._main(["--repo", d, "--multi-branch", "Z:/no/such.txt"])
        self.assertEqual(code, 2)


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("mgh_sdr_launch", LAUNCH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _native_assets_root(tmp: Path) -> Path:
    """A temp <mgh-core> root carrying the two native assets, so in-process
    launcher tests (run from the dev tree, whose sibling agent/ dir does not
    exist) exercise the native form without tripping the asset gate. The
    missing-asset path patches `_mgh_core_root` to a bare dir instead."""
    core = Path(tmp) / ".opencode" / "mgh-core"
    frag = core / "prompts" / "fragments"
    frag.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE.parent / "core" / "prompts" / "fragments"
                 / "sdr-native-dispatch.md", frag / "sdr-native-dispatch.md")
    agent = core.parent / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE.parent / "releases" / "opencode" / "agent"
                 / "sdr-review-native.md", agent / "sdr-review-native.md")
    return core


class TestLauncherDryRun(unittest.TestCase):
    """--dry-run end-to-end (zero spawn): artifacts + sentinel + prompt file."""

    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_launch_smoke_"))
        self.repo = self.tmp / "repo"
        self.front = self.tmp / "front"
        _init_repo(self.repo)
        _init_repo(self.front)
        # front repo: same-name branch + config + a route hit
        (self.front / "config").mkdir()
        (self.front / "config" / "buttonAuth.properties").write_text("a=1", encoding="utf-8")
        (self.front / "src").mkdir()
        (self.front / "src" / "pay.vue").write_text("axios.post('/pay/quick')",
                                                   encoding="utf-8")
        _commit_all(self.front, "init")
        _git(self.front, "checkout", "-qb", "feature-pay")
        (self.front / "config" / "buttonAuth.properties").write_text("pay/quick=allow",
                                                                     encoding="utf-8")
        _commit_all(self.front, "branch work")
        # main repo: design declares the external repo; feature branch adds an interface
        (self.repo / "AGENTS.md").write_text(
            "# 安全设计\n- 垂直越权:buttonAuth.properties 配置授权。\n"
            f"- 本地前端项目地址 {self.front.as_posix()},前端分支名与本项目一致。\n",
            encoding="utf-8")
        _commit_all(self.repo, "init")
        _git(self.repo, "checkout", "-qb", "feature-pay")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "PayController.java").write_text(
            "@RestController\npublic class PayController {\n"
            "    @PostMapping(\"/pay/quick\")\n    public String quick() { return \"ok\"; }\n}\n",
            encoding="utf-8")
        _commit_all(self.repo, "feat")
        # in-process launcher runs from the dev tree; give the native asset gate a
        # complete fake install root (opencode face) so the default native form can
        # run. `_detect_host` stays the real probe unless a test overrides it.
        self.install_root = _native_assets_root(self.tmp / "install")
        self.m._mgh_core_root = lambda: self.install_root

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _approve_front(self):
        """Write the project read-roots config (what read_roots_config.py produces)."""
        cfg = self.repo / ".mgh" / "read-roots.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"v": 1, "read_roots": [str(self.front)]}),
                       encoding="utf-8")

    def test_dry_run_artifacts_complete(self):
        self._approve_front()
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["branches"], ["feature-pay"])
        self.assertEqual(payload["pending_approval"], [])
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        # sdr_context artifacts
        ctx = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertTrue(Path(ctx["baseline_path"]).is_file())
        self.assertEqual(ctx["sensitive_catalog_source"], "default-template")
        # the resolved catalog is materialized as a standalone run-dir file
        self.assertTrue(Path(ctx["sensitive_catalog_path"]).is_file(),
                        "resolved catalog must be materialized into the run dir")
        self.assertEqual(len(ctx["external_repos"]), 1)
        self.assertTrue(Path(ctx["external_repos"][0]["summary_path"]).is_file())
        # sentinel written WITH read_roots (the searched external root) and KEPT by dry-run
        sentinel = json.loads((self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sentinel["domain"], "mgh-sdr")
        self.assertEqual(sentinel["target"], str(self.repo))
        self.assertEqual(sentinel["read_roots"], [str(self.front)])
        # orchestrator prompt carries the verbatim paths + the never-re-read instruction
        prompt = (run_dir / "orchestrator_prompt.md").read_text(encoding="utf-8")
        self.assertIn("NEVER", prompt)
        self.assertIn(str(ctx["baseline_path"]), prompt)

    # --- authorization gate (add-mgh-sdr-read-root-config 2.2) ---
    def test_unapproved_repo_zero_reads_sentinel_clean_pending_disclosed(self):
        # declared but NOT configured: zero retrieval, sentinel read_roots[] empty,
        # launcher stdout + prompt + stderr carry the pending-approval disclosure
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["pending_approval"], [str(self.front)])
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        ctx = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(ctx["external_repos"], [])
        self.assertFalse((run_dir / "external").exists())     # zero reads
        sentinel = json.loads((self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sentinel["read_roots"], [])          # NOT granted this run
        prompt = (run_dir / "orchestrator_prompt.md").read_text(encoding="utf-8")
        self.assertIn(str(self.front), prompt)
        self.assertIn("read_roots_config.py", prompt)
        self.assertIn("NEVER", prompt)
        self.assertIn("WARN", err)
        self.assertIn("NOT approved", err)
        self.assertIn("read_roots_config.py", err)

    def test_approved_after_config_write_is_retrieved(self):
        # the "user approved -> config written -> re-run same args" loop: second run
        # retrieves the repo, pending_approval empties, sentinel grants the root
        code1, _, _ = self._launch(["--repo", str(self.repo),
                                    "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code1, 0)
        self._approve_front()   # what read_roots_config.py --add produces
        code2, out2, err2 = self._launch(["--repo", str(self.repo),
                                          "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code2, 0, err2)
        payload = json.loads(out2)
        self.assertEqual(payload["pending_approval"], [])
        run_dirs = sorted((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        ctx = json.loads((run_dirs[-1] / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(len(ctx["external_repos"]), 1)
        sentinel = json.loads((self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sentinel["read_roots"], [str(self.front)])

    def _launch(self, argv):
        old_argv = sys.argv
        sys.argv = ["mgh_sdr_launch.py"] + argv
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        except SystemExit as e:  # argparse misuse exits directly
            code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue(), err.getvalue()

    # --- script-owned run state + idempotent sentinel refresh (add-mgh-sdr-resume-surface) ---

    def _sentinel_body(self):
        return json.loads((self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8"))

    def test_dry_run_keeps_the_sentinel(self):
        self._approve_front()
        code, _, err = self._launch(["--repo", str(self.repo),
                                     "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        self.assertTrue((self.repo / ".mgh-sdr" / ".active").is_file(),
                        "--dry-run must KEEP the sentinel (the next real run reuses it)")

    def test_repeat_launch_refreshes_one_identical_sentinel(self):
        self._approve_front()
        code1, _, err1 = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code1, 0, err1)
        first = (self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8")
        code2, _, err2 = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code2, 0, err2)
        # idempotent refresh: same single sentinel file, byte-identical content
        self.assertEqual((self.repo / ".mgh-sdr" / ".active").read_text(encoding="utf-8"),
                         first)
        sentinels = list((self.repo / ".mgh-sdr").glob(".active*"))
        self.assertEqual(len(sentinels), 1, f"sentinel copies left behind: {sentinels}")

    def test_run_config_is_script_written_and_carries_only_the_signal(self):
        self._approve_front()
        code, _, err = self._launch(["--repo", str(self.repo),
                                     "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        rc = run_dir / "run_config.json"
        self.assertTrue(rc.is_file(), "sdr_context did not write the codegraph signal")
        body = json.loads(rc.read_text(encoding="utf-8"))
        self.assertEqual(set(body), {"no_codegraph"})
        # the launcher passes no flag here, so this is sdr_context's DERIVED value: the
        # temp repo has no `.codegraph/`, so an honest signal is off
        self.assertEqual(body, {"no_codegraph": True})

    def test_launcher_signal_matches_the_grouping_predicate(self):
        """The launcher entry must reach the SAME signal as the host-shell entry, with no
        flag on either: the probe sinks into sdr_context.py — the one step both pass
        through — so an indexed repo reports on. The launcher's earlier flag-only default
        would have claimed `on` here even unindexed, telling reviewers their slice carried
        a whole call chain that the grouping stage never merged."""
        (self.repo / ".codegraph").mkdir(exist_ok=True)
        fake_bin = self.repo / "tools" / "codegraph.cmd"
        fake_bin.parent.mkdir(parents=True, exist_ok=True)
        fake_bin.write_text("@echo off\n", encoding="utf-8")
        old = os.environ.get("MGH_CODEGRAPH_BIN")
        os.environ["MGH_CODEGRAPH_BIN"] = str(fake_bin)
        try:
            self._approve_front()
            code, _, err = self._launch(["--repo", str(self.repo),
                                         "--branch", "feature-pay", "--dry-run"])
            self.assertEqual(code, 0, err)
            run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
            rc = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
            self.assertEqual(rc, {"no_codegraph": False})
        finally:
            if old is None:
                os.environ.pop("MGH_CODEGRAPH_BIN", None)
            else:
                os.environ["MGH_CODEGRAPH_BIN"] = old

    def test_no_codegraph_flag_reaches_the_run_config(self):
        self._approve_front()
        code, _, err = self._launch(["--repo", str(self.repo), "--branch", "feature-pay",
                                     "--dry-run", "--no-codegraph"])
        self.assertEqual(code, 0, err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        rc = json.loads((run_dir / "run_config.json").read_text(encoding="utf-8"))
        self.assertEqual(rc, {"no_codegraph": True})

    def test_sentinel_refresh_re_judges_roots_before_spawning(self):
        # Second authorization gate: sdr_context retrieved a root, but the project
        # config no longer approves it by spawn time (version skew / revoked grant).
        # The launcher's refresh MUST drop it rather than inherit it verbatim.
        def fake_context(repo, run_dir, base, branch, dims, read_roots, no_codegraph=False):
            return {"external_repos": [{"path": str(self.front), "slug": "front"}],
                    "external_skipped": [], "pending_approval": [],
                    "baseline_path": str(self.tmp / "baseline.md"),
                    "baseline_truncated": False,
                    "sensitive_catalog_source": "default-template",
                    "sensitive_catalog": {}}

        saved = self.m._run_context
        self.m._run_context = fake_context
        try:
            ok, outcome, _ = self.m._run_one(self.repo, "feature-pay", "master",
                                             "claude", None, [], True)
            self.assertTrue(ok, outcome)
            self.assertEqual(self._sentinel_body()["read_roots"], [],
                             "an unapproved root leaked into read_roots[]")
            self._approve_front()
            ok, outcome, _ = self.m._run_one(self.repo, "feature-pay", "master",
                                             "claude", None, [], True)
            self.assertTrue(ok, outcome)
            self.assertEqual(self._sentinel_body()["read_roots"], [str(self.front)])
        finally:
            self.m._run_context = saved

    def test_dry_run_multi_branch_serial(self):
        _git(self.repo, "checkout", "-qb", "feature-b2")
        (self.repo / "src" / "B2.java").write_text("class B2 {}\n", encoding="utf-8")
        _commit_all(self.repo, "b2")
        _git(self.repo, "checkout", "-q", "feature-pay")
        mb = self.tmp / "branches.txt"
        mb.write_text("# comment\nfeature-pay\nfeature-b2\n\n", encoding="utf-8")
        code, out, err = self._launch(["--repo", str(self.repo), "--dry-run",
                                       "--multi-branch", str(mb)])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["branches"], ["feature-pay", "feature-b2"])
        run_dirs = list((self.repo / ".mgh-sdr" / "runs").iterdir())
        self.assertEqual(len(run_dirs), 2, f"expected 2 run dirs, got {run_dirs}")

    def test_prompt_points_at_materialized_catalog_never_embeds_it(self):
        # fix-mgh-sdr-docs-shell-alignment 1.3/M6+L3: the orchestrator prompt CARRIES the
        # materialized catalog file's read-only path and NEVER embeds the object body —
        # the old [:4000] silent truncation is deleted, so "verbatim passthrough" of
        # paths is honest again at the launcher layer
        self._approve_front()
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        ctx = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
        prompt = (run_dir / "orchestrator_prompt.md").read_text(encoding="utf-8")
        self.assertIn(str(ctx["sensitive_catalog_path"]), prompt)
        self.assertNotIn("敏感目录对象:", prompt, "the object body must not be embedded")
        import inspect
        src = inspect.getsource(self.m)
        self.assertNotIn("[:4000]", src, "silent truncation must be gone")
        self.assertNotIn("'sensitive_catalog']", src,
                         "the object body is never read back for embedding")

    # --- fix-mgh-sdr-native-default-dispatch 3.2: prompt follows the form ---
    def _force_host(self, host):
        self.m._detect_host = lambda explicit=None: host

    def _prompt_of_last_run(self):
        run_dir = sorted((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))[-1]
        return (run_dir / "orchestrator_prompt.md").read_text(encoding="utf-8")

    def test_opencode_no_profile_prompt_is_native(self):
        self._approve_front()
        self._force_host("opencode")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        prompt = self._prompt_of_last_run()
        for needle in ("原生派发", "emit_native_plan.py", "sdr-review-native",
                       "mgh-dispatch: plan=<plan_path> unit=<短号>",
                       "sdr-native-dispatch.md", "native_watchdog.py"):
            self.assertIn(needle, prompt, needle)
        self.assertNotIn("fanout_runner", prompt)
        self.assertNotIn("--cred-file", prompt)
        self.assertIn("dispatch form=native", err)

    def test_opencode_runner_profile_prompt_is_subprocess(self):
        self._approve_front()
        (self.repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.repo / ".mgh" / "env-profile.json").write_text(
            json.dumps({"v": 1, "dispatch_mode": "runner"}), encoding="utf-8")
        self._force_host("opencode")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        prompt = self._prompt_of_last_run()
        self.assertIn("fanout_runner.py", prompt)
        self.assertIn("--wave 1", prompt)
        self.assertNotIn("emit_native_plan.py", prompt)
        self.assertIn("dispatch form=runner", err)

    def test_claude_prompt_keeps_subprocess_form(self):
        self._approve_front()
        self._force_host("claude")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        prompt = self._prompt_of_last_run()
        self.assertIn("fanout_runner.py", prompt)
        self.assertNotIn("emit_native_plan.py", prompt)
        self.assertIn("dispatch form=runner", err)

    def test_claude_explicit_native_exits_2_before_prompt(self):
        self._approve_front()
        (self.repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.repo / ".mgh" / "env-profile.json").write_text(
            json.dumps({"v": 1, "dispatch_mode": "native"}), encoding="utf-8")
        self._force_host("claude")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("not supported by the claude host", err)
        self.assertIn("--host opencode", err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        self.assertFalse((run_dir / "orchestrator_prompt.md").exists(),
                         "fail-closed must happen before the prompt is written")

    def test_bad_profile_exits_2_before_prompt(self):
        (self.repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.repo / ".mgh" / "env-profile.json").write_text("{broken",
                                                            encoding="utf-8")
        self._force_host("opencode")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("env profile rejected", err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        self.assertFalse((run_dir / "orchestrator_prompt.md").exists())

    def test_missing_native_assets_exit_2_before_prompt(self):
        (self.repo / ".mgh").mkdir(parents=True, exist_ok=True)
        (self.repo / ".mgh" / "env-profile.json").write_text(
            json.dumps({"v": 1, "dispatch_mode": "native"}), encoding="utf-8")
        bare = self.tmp / "bare-core"
        bare.mkdir()
        self.m._mgh_core_root = lambda: bare
        self._force_host("opencode")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 2)
        self.assertIn("sdr-review-native.md", err)
        self.assertIn("install.sh --opencode", err)
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        self.assertFalse((run_dir / "orchestrator_prompt.md").exists())

    def test_multibranch_dry_run_prompts_follow_the_form(self):
        _git(self.repo, "checkout", "-qb", "feature-b2")
        (self.repo / "src" / "B2.java").write_text("class B2 {}\n", encoding="utf-8")
        _commit_all(self.repo, "b2")
        _git(self.repo, "checkout", "-q", "feature-pay")
        mb = self.tmp / "branches-native.txt"
        mb.write_text("feature-pay\nfeature-b2\n", encoding="utf-8")
        self._force_host("opencode")
        code, out, err = self._launch(["--repo", str(self.repo), "--dry-run",
                                       "--multi-branch", str(mb)])
        self.assertEqual(code, 0, err)
        prompts = [p.read_text(encoding="utf-8") for p in
                   (self.repo / ".mgh-sdr" / "runs").glob("*/orchestrator_prompt.md")]
        self.assertEqual(len(prompts), 2)
        for prompt in prompts:
            self.assertIn("emit_native_plan.py", prompt)
            self.assertNotIn("fanout_runner", prompt)




class TestSpecialAuthPromptFace(unittest.TestCase):
    """fix-mgh-sdr-native-default-dispatch 7.x: the special-auth doc is a
    PROJECT-OWNED optional entry (`<repo>/.mgh/special-auth.md`). Present => the
    prompt carries exactly one "read it first" line (both dispatch forms);
    absent => zero special-auth bytes. The flow NEVER presets credential
    commands (mgh_credentials.py / cred_source.json / --cred-file /
    credential_expired)."""

    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_launch_auth_"))
        self.repo = self.tmp / "repo"
        _init_repo(self.repo)
        (self.repo / "AGENTS.md").write_text("# \u8bbe\u8ba1\n- \u8d8a\u6743\u914d\u7f6e\u3002\n",
                                             encoding="utf-8")
        _commit_all(self.repo, "init")
        _git(self.repo, "checkout", "-qb", "feature-pay")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "PayController.java").write_text(
            "@RestController\npublic class PayController {}\n", encoding="utf-8")
        _commit_all(self.repo, "feat")
        self.install_root = _native_assets_root(self.tmp / "install")
        self.m._mgh_core_root = lambda: self.install_root
        self.m._detect_host = lambda explicit=None: "claude"
        self.doc = self.repo / ".mgh" / "special-auth.md"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _launch(self, extra):
        old = sys.argv
        sys.argv = ["mgh_sdr_launch.py", *extra]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _prompt(self):
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        run_dir = sorted((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))[-1]
        return (run_dir / "orchestrator_prompt.md").read_text(encoding="utf-8"), err

    def test_doc_absent_generic_prompt_no_cred(self):
        prompt, err = self._prompt()
        self.assertNotIn("special-auth", prompt)
        self.assertNotIn("--cred-file", prompt)
        self.assertNotIn("special-auth", err)

    def test_doc_present_prompt_carries_one_entry_line(self):
        self.doc.parent.mkdir(parents=True, exist_ok=True)
        self.doc.write_text("# guide\n", encoding="utf-8")
        prompt, err = self._prompt()
        self.assertIn(str(self.doc.resolve()), prompt)
        self.assertIn("先 Read 该说明", prompt)
        for banned in ("mgh_credentials.py", "cred_source.json", "--cred-file",
                       "credential_expired"):
            self.assertNotIn(banned, prompt, banned)
        self.assertNotIn("special-auth", err)

    def test_doc_present_native_prompt_also_carries_the_entry(self):
        self.doc.parent.mkdir(parents=True, exist_ok=True)
        self.doc.write_text("# guide\n", encoding="utf-8")
        self.m._detect_host = lambda explicit=None: "opencode"
        prompt, err = self._prompt()
        self.assertIn("emit_native_plan.py", prompt)
        self.assertIn(str(self.doc.resolve()), prompt)
        for banned in ("mgh_credentials.py", "cred_source.json", "--cred-file",
                       "credential_expired"):
            self.assertNotIn(banned, prompt, banned)

import shutil  # noqa: E402  (tearDown uses it; placed here to keep the header import list stdlib-honest)


class TestLauncherReportSurface(unittest.TestCase):
    """fix-mgh-sdr-multibranch-findings: the post-run report claim targets THIS branch's
    run-dir sdr_manifest.json (`report` field) — the repo-root mgh-sdr-*.html mtime glob
    is gone (a probe branch used to claim the previous branch's report). --open remains
    a declared default-off contract (--help is the contract surface)."""

    def setUp(self):
        self.m = _load()

    def _main(self, argv):
        old_argv = sys.argv
        sys.argv = ["mgh_sdr_launch.py"] + argv
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = self.m.main()
                except SystemExit as e:
                    code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue(), err.getvalue()

    def test_help_declares_open(self):
        code, out, err = self._main(["--help"])
        self.assertEqual(code, 0)
        text = out + err
        self.assertIn("--open", text)
        # default-off is part of the contract: the launcher stays side-effect-free
        # unless the flag is explicitly passed
        self.assertIn("default off", text.lower())

    def test_open_is_default_off(self):
        # store_true => argparse default False: the flag never fires unless passed
        import inspect
        src = inspect.getsource(self.m)
        self.assertIn('"--open"', src)
        self.assertIn('action="store_true"', src)

    def test_report_claim_is_run_dir_manifest_never_a_repo_glob(self):
        import inspect
        src = inspect.getsource(self.m)
        # the cross-branch claiming glob is DELETED, not narrowed
        self.assertNotIn('repo.glob("mgh-sdr-*.html")', src)
        self.assertNotIn("mgh-sdr-*.md", src)
        # the only claim source is the run-dir manifest's report field + on-disk check
        self.assertIn("sdr_manifest.json", src)
        self.assertIn("no report produced for", src)
        # --open fires only on a real report file (a --dry-run outcome is the prompt
        # path and must never be opened)
        self.assertIn('outcome.endswith(".html")', src)


class _FakeHostMixin:
    """Shared harness: monkeypatches the loaded launcher module so a branch flow runs
    WITHOUT the real sdr_context.py or a real host CLI. `_run_context` returns a minimal
    in-memory ctx; `_spawn_host` records every call (host / repo / model / prompt) and
    simulates the host session's render step by writing the renderer's co-products
    (sdr_manifest.json + report.html) into the current branch's run dir before
    returning `spawn_code`."""

    def _install_fakes(self, m, spawn_code=0, write_manifest=True):
        self.m = m
        self.spawned = []
        self.run_dirs = []
        # hermetic host-error extraction (fix-mgh-sdr-host-error-capture): tests must
        # NEVER read the maintainer's real opencode global log — default to a
        # nonexistent tmp path (the absent/fail-soft state); evidence tests override
        # with a crafted log
        self.ev_dir = Path(tempfile.mkdtemp(prefix="mgh_launch_glog_"))
        self.addCleanup(shutil.rmtree, self.ev_dir, ignore_errors=True)
        m._opencode_global_log_path = lambda: self.ev_dir / "opencode.log"
        # native asset gate: these flows default to the opencode-native form, so a
        # complete fake install root keeps the gate satisfied (dev-tree runs have
        # no sibling agent/ dir).
        self.install_root = _native_assets_root(
            Path(tempfile.mkdtemp(prefix="mgh_launch_assets_")))
        self.addCleanup(shutil.rmtree, self.install_root.parent.parent,
                        ignore_errors=True)
        m._mgh_core_root = lambda: self.install_root

        def fake_context(repo, run_dir, base, branch, dims, read_roots,
                         no_codegraph=False):
            self.run_dirs.append(Path(run_dir))
            return {"external_repos": [], "external_skipped": [],
                    "pending_approval": [],
                    "baseline_path": str(self.repo / "baseline.md"),
                    "baseline_truncated": False,
                    "sensitive_catalog_source": "default-template",
                    "sensitive_catalog": {}}

        def fake_spawn(host, repo, prompt, model=None, spawn_window=None):
            self.spawned.append({"host": host, "repo": str(repo), "model": model,
                                 "prompt": prompt})
            if self.run_dirs:
                rd = self.run_dirs[-1]
                # two runs within the same second share the timestamped run dir: start
                # from a clean slate so a stale manifest from an earlier run cannot
                # masquerade as this run's render output
                for stale in ("sdr_manifest.json", "report.html"):
                    (rd / stale).unlink(missing_ok=True)
                if write_manifest:
                    (rd / "report.html").write_text("<html></html>", encoding="utf-8")
                    (rd / "sdr_manifest.json").write_text(
                        json.dumps({"report": str(rd / "report.html")}),
                        encoding="utf-8")
            return spawn_code

        m._run_context = fake_context
        m._spawn_host = fake_spawn

    def _two_branch_repo(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_launch_mb_"))
        self.repo = self.tmp / "repo"
        _init_repo(self.repo)
        (self.repo / "f.txt").write_text("base", encoding="utf-8")
        _commit_all(self.repo, "init")
        for name in ("feature-pay", "feature-b2"):
            _git(self.repo, "checkout", "-qb", name)
            (self.repo / "f.txt").write_text(name, encoding="utf-8")
            _commit_all(self.repo, name)
        _git(self.repo, "checkout", "-q", "master")

    def _launch(self, argv):
        old_argv = sys.argv
        sys.argv = ["mgh_sdr_launch.py"] + argv
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = self.m.main()
                except SystemExit as e:  # argparse misuse exits directly
                    code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue(), err.getvalue()


class TestBranchPrecheck(unittest.TestCase, _FakeHostMixin):
    """P1+P6 branch pre-check: an unresolvable branch ref is a deterministic early
    failure BEFORE any side effect — zero host spawn, zero run dir, zero sentinel —
    recorded FAILED (branch not found) while the later branches run on; launcher exit 1
    + FAILED summary. True run, --dry-run, and single-branch mode share the same gate."""

    def setUp(self):
        self.m = _load()
        self._two_branch_repo()
        self._install_fakes(self.m)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_multibranch_probe_fails_fast_zero_side_effects_rest_continue(self):
        mb = self.tmp / "branches.txt"
        mb.write_text("sdr-mb-nonexistent\nfeature-pay\nfeature-b2\n", encoding="utf-8")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--multi-branch", str(mb)])
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "", "a failed sweep must not print the stdout JSON payload")
        self.assertIn("branch not found: sdr-mb-nonexistent", err)
        self.assertIn("FAILED BRANCHES (1)", err)
        # zero spawn + zero run dir for the probe; the two real branches ran normally
        # (the host is whichever CLI auto-detection found — both spawns use it)
        self.assertEqual(len(self.spawned), 2)
        self.assertEqual(len({s["host"] for s in self.spawned}), 1)
        names = sorted(d.name for d in (self.repo / ".mgh-sdr" / "runs").iterdir())
        self.assertEqual(len(names), 2, f"run dirs: {names}")
        self.assertTrue(all("nonexistent" not in n for n in names))
        self.assertFalse((self.repo / ".mgh-sdr" / ".active").exists(),
                         "sentinel must not survive the sweep")

    def test_dry_run_invalid_list_fails_probe_valid_branch_still_produces(self):
        mb = self.tmp / "branches.txt"
        mb.write_text("sdr-mb-nonexistent\nfeature-pay\n", encoding="utf-8")
        code, out, err = self._launch(["--repo", str(self.repo), "--dry-run",
                                       "--multi-branch", str(mb)])
        self.assertEqual(code, 1, err)
        self.assertIn("branch not found: sdr-mb-nonexistent", err)
        self.assertEqual(self.spawned, [], "--dry-run spawns zero hosts overall")
        run_dirs = list((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        self.assertEqual(len(run_dirs), 1, "the valid branch still produces artifacts")
        self.assertTrue((run_dirs[0] / "orchestrator_prompt.md").is_file())
        self.assertFalse(any("nonexistent" in d.name
                             for d in (self.repo / ".mgh-sdr" / "runs").iterdir()))

    def test_single_branch_nonexistent_exits_1_zero_side_effects(self):
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "no-such-branch"])
        self.assertEqual(code, 1, err)
        self.assertIn("branch not found: no-such-branch", err)
        self.assertIn("FAILED BRANCHES (1)", err)
        self.assertEqual(self.spawned, [])
        runs = self.repo / ".mgh-sdr" / "runs"
        self.assertFalse(runs.is_dir() and any(runs.iterdir()), "zero run dirs")
        self.assertFalse((self.repo / ".mgh-sdr" / ".active").exists(),
                         "zero sentinel writes")


class TestReportClaimManifest(unittest.TestCase, _FakeHostMixin):
    """P2 report claim: the ONLY source is this branch's run-dir sdr_manifest.json
    `report` field (file must be on disk); missing manifest / missing file => FAILED
    (no-report) — a repo-root foreign report is NEVER claimed and --open never fires on
    a FAILED branch."""

    def setUp(self):
        self.m = _load()
        self._two_branch_repo()
        self._install_fakes(self.m)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _foreign_report(self):
        fr = self.repo / "mgh-sdr-19700101_000000_other.html"
        fr.write_text("<html>foreign</html>", encoding="utf-8")
        return fr

    def test_ok_claims_the_manifest_report_path(self):
        foreign = self._foreign_report()
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["reports"], [str(self.run_dirs[0] / "report.html")],
                         "the manifest path is claimed, not the repo-root foreign file")
        self.assertNotIn(str(foreign), out)

    def test_exit0_without_manifest_is_failed_no_report_never_claims_foreign(self):
        foreign = self._foreign_report()
        self._install_fakes(self.m, write_manifest=False)
        ok, outcome, _ = self.m._run_one(self.repo, "feature-pay", "master",
                                         "claude", None, [], False)
        self.assertFalse(ok)
        self.assertEqual(outcome, "no report produced for feature-pay")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay"])
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "")
        self.assertIn("no report produced for feature-pay", err)
        self.assertNotIn(str(foreign), err, "the foreign report is never claimed")

    def test_manifest_with_missing_report_file_is_failed(self):
        # manifest present but its `report` file is not on disk => FAILED (no-report)
        def fake_spawn_broken(host, repo, prompt, model=None, spawn_window=None):
            self.spawned.append({"host": host, "repo": str(repo), "model": model})
            rd = self.run_dirs[-1]
            (rd / "sdr_manifest.json").write_text(
                json.dumps({"report": str(rd / "report.html")}), encoding="utf-8")
            return 0

        self.m._spawn_host = fake_spawn_broken
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay"])
        self.assertEqual(code, 1, err)
        self.assertIn("no report produced for feature-pay", err)

    def test_open_fires_only_for_an_ok_branch_report(self):
        import webbrowser
        opened = []

        def record(uri, *a, **k):
            opened.append(str(uri))
            return True

        orig = webbrowser.open
        webbrowser.open = record
        try:
            code, _, err = self._launch(["--repo", str(self.repo), "--branch",
                                         "feature-pay", "--open"])
            self.assertEqual(code, 0, err)
            self.assertEqual([u for u in opened if u.endswith("report.html")],
                             opened, "exactly the ok report is opened")
        finally:
            webbrowser.open = orig
        self._install_fakes(self.m, write_manifest=False)
        opened.clear()
        webbrowser.open = record
        try:
            code, _, err = self._launch(["--repo", str(self.repo), "--branch",
                                         "feature-pay", "--open"])
            self.assertEqual(code, 1, err)
            self.assertEqual(opened, [], "--open must NOT fire on a FAILED branch")
        finally:
            webbrowser.open = orig


class TestInlineBranchList(unittest.TestCase, _FakeHostMixin):
    """add-mgh-sdr-inline-branch-list: `--branch-list "b1,b2"` is the INLINE multi-branch
    form feeding the SAME serial per-branch sweep as --multi-branch. Fail-loud misuse:
    any empty item (a,,b / trailing comma / all-whitespace value) exits 2 naming the
    offending item; --branch-list together with --multi-branch exits 2 (never a silent
    priority); --branch-list overrides the single --branch (same shape as --multi-branch
    over --branch)."""

    def setUp(self):
        self.m = _load()
        self._two_branch_repo()
        self._install_fakes(self.m)
        self.m._detect_host = lambda explicit=None: "claude"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- pure function `_split_branch_list` ---

    def _split(self, value):
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                return self.m._split_branch_list(value), err.getvalue(), None
        except SystemExit as e:
            return None, err.getvalue(), e.code

    def test_split_trims_items_and_preserves_order(self):
        branches, err, code = self._split(" feature-pay , feature-b2 ")
        self.assertIsNone(code, err)
        self.assertEqual(branches, ["feature-pay", "feature-b2"])

    def test_split_dedupes_keeping_first_and_order(self):
        branches, _, code = self._split("feature-pay,feature-b2,feature-pay")
        self.assertIsNone(code)
        self.assertEqual(branches, ["feature-pay", "feature-b2"])

    def test_empty_item_exits_2_naming_the_item_number(self):
        for value, bad_index in (("feature-pay,,feature-b2", 2), ("feature-pay,", 2),
                                 (",feature-pay", 1)):
            with self.subTest(value=value):
                branches, err, code = self._split(value)
                self.assertIsNone(branches)
                self.assertEqual(code, 2)
                self.assertIn(f"item {bad_index}", err, err)
                self.assertIn("recipe", err)

    def test_all_whitespace_exits_2(self):
        for value in ("", "   "):
            with self.subTest(value=value):
                branches, err, code = self._split(value)
                self.assertIsNone(branches)
                self.assertEqual(code, 2)

    # --- integration through main() (fake host, fake sdr_context) ---

    def test_branch_list_runs_the_serial_full_flow(self):
        code, out, err = self._launch(["--repo", str(self.repo), "--branch-list",
                                       "feature-pay, feature-b2"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["branches"], ["feature-pay", "feature-b2"])
        self.assertEqual(len(payload["reports"]), 2)
        self.assertEqual(len(self.spawned), 2)
        run_dirs = list((self.repo / ".mgh-sdr" / "runs").iterdir())
        self.assertEqual(len(run_dirs), 2, f"run dirs: {run_dirs}")
        self.assertFalse((self.repo / ".mgh-sdr" / ".active").exists(),
                         "sentinel must not survive the sweep")

    def test_branch_list_and_multi_branch_conflict_exits_2(self):
        mb = self.tmp / "branches.txt"
        mb.write_text("feature-pay\n", encoding="utf-8")
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--multi-branch", str(mb),
                                       "--branch-list", "feature-b2"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("recipe", err)
        self.assertEqual(self.spawned, [], "a misuse refusal spawns nothing")
        runs = self.repo / ".mgh-sdr" / "runs"
        self.assertFalse(runs.is_dir() and any(runs.iterdir()), "zero run dirs")
        self.assertFalse((self.repo / ".mgh-sdr" / ".active").exists(), "zero sentinel")

    def test_branch_list_overrides_single_branch(self):
        code, out, err = self._launch(["--repo", str(self.repo), "--branch",
                                       "feature-pay", "--branch-list", "feature-b2"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["branches"], ["feature-b2"])
        self.assertEqual(len(self.spawned), 1)
        names = [d.name for d in (self.repo / ".mgh-sdr" / "runs").iterdir()]
        self.assertEqual(len(names), 1, names)
        self.assertIn("feature-b2", names[0])
        self.assertNotIn("feature-pay", names[0])

    def test_help_documents_branch_list_flag(self):
        # real subprocess --help is the contract surface for the new flag (mirrors
        # test_help_documents_model_flag)
        r = subprocess.run([sys.executable, str(LAUNCH), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--branch-list", r.stdout)


class TestSpawnEnvAndFlags(unittest.TestCase):
    """P3 env hygiene: the spawned child env carries NO `PWD` (opencode resolves the
    project by `PWD ?? cwd` — an inherited PWD landed every session in the wrong
    project) and cwd = the target repo, BOTH hosts. P4 diagnosability: opencode spawn
    carries `--print-logs --log-level ERROR` (claude does not); `--model` passes through
    to both hosts, appended only when given; --help documents the flag (the launcher
    --help is the contract surface)."""

    def setUp(self):
        self.m = _load()
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_spawn_"))
        self.captured = []
        self._orig_run = self.m.subprocess.run

        def fake_run(cmd, **kwargs):
            self.captured.append((list(cmd), kwargs))
            return subprocess.CompletedProcess(cmd, 0)

        self.m.subprocess.run = fake_run

    def tearDown(self):
        self.m.subprocess.run = self._orig_run
        shutil.rmtree(self.repo, ignore_errors=True)

    def _last(self):
        return self.captured[-1]

    def test_env_has_no_pwd_and_cwd_is_repo_both_hosts(self):
        old = os.environ.get("PWD")
        os.environ["PWD"] = "C:/some/other/dir"
        try:
            for host in ("claude", "opencode"):
                with self.subTest(host=host):
                    self.assertEqual(self.m._spawn_host(host, self.repo, "p"), 0)
                    cmd, kwargs = self._last()
                    self.assertIsInstance(kwargs.get("env"), dict)
                    self.assertNotIn("PWD", kwargs["env"])
                    self.assertEqual(kwargs["cwd"], str(self.repo))
        finally:
            if old is None:
                os.environ.pop("PWD", None)
            else:
                os.environ["PWD"] = old

    def test_opencode_carries_log_flags_claude_does_not(self):
        self.m._spawn_host("opencode", self.repo, "p")
        cmd, _ = self._last()
        self.assertEqual(cmd[2], "--print-logs")
        self.assertEqual(cmd[3], "--log-level")
        self.assertIn(cmd[4], ("ERROR", "error"),
                      "the level spelling follows the installed host version")
        self.m._spawn_host("claude", self.repo, "p")
        cmd, _ = self._last()
        self.assertNotIn("--print-logs", cmd)
        self.assertNotIn("--log-level", cmd)

    def test_opencode_log_level_is_version_aware(self):
        # v1 (1.x) requires uppercase ERROR; v2 (2.x) rejects it for lowercase
        saved = self.m.subprocess.run
        try:
            self.m.subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(
                cmd, 0, stdout="opencode v2.1.0\n", stderr="")
            self.assertEqual(self.m._opencode_log_flags("opencode"),
                             ["--print-logs", "--log-level", "error"])
            self.m.subprocess.run = lambda cmd, **kw: subprocess.CompletedProcess(
                cmd, 0, stdout="1.19.3\n", stderr="")
            self.assertEqual(self.m._opencode_log_flags("opencode"),
                             ["--print-logs", "--log-level", "ERROR"])
        finally:
            self.m.subprocess.run = saved

    def test_model_passthrough_both_hosts_only_when_given(self):
        for host in ("opencode", "claude"):
            self.m._spawn_host(host, self.repo, "p", "prov/m1")
            cmd, _ = self._last()
            self.assertEqual(cmd[-2:], ["--model", "prov/m1"], host)
        for host in ("opencode", "claude"):
            self.m._spawn_host(host, self.repo, "p")
            cmd, _ = self._last()
            self.assertNotIn("--model", cmd, host)

    def test_help_documents_model_flag(self):
        # self.m.subprocess.run is monkeypatched for the other tests (the subprocess
        # module object is global) — this test intentionally uses the SAVED original.
        r = self._orig_run([sys.executable, str(LAUNCH), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--model <provider/model>", r.stdout)


class TestUpstreamOutputGuard(unittest.TestCase, _FakeHostMixin):
    """fix-mgh-sdr-docs-shell-alignment L1/L2: (a) the empty try/finally dead shell
    around the spawn is deleted with sentinel semantics untouched; (b) a missing/
    garbled/misshaped sdr_context stdout (version-skewed sibling, broken install) is a
    per-branch FAILED with the reason on stderr — NEVER a bare traceback; later
    branches continue; exit-code semantics unchanged; a pre-existing residual sentinel
    is left for the recovery entries (never silently removed on a failure path)."""

    def setUp(self):
        self.m = _load()
        self._two_branch_repo()
        self.spawned = []
        self.run_dirs = []
        # the healthy branch resolves the default opencode-native form: satisfy
        # the native asset gate with a complete fake install root
        self.install_root = _native_assets_root(
            Path(tempfile.mkdtemp(prefix="mgh_launch_assets_")))
        self.addCleanup(shutil.rmtree, self.install_root.parent.parent,
                        ignore_errors=True)
        self.m._mgh_core_root = lambda: self.install_root

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _no_dead_shell(self):
        import inspect
        src = inspect.getsource(self.m)
        self.assertNotIn("finally:\n        pass", src,
                         "the empty try/finally dead shell must be deleted")

    def _fake_upstream(self, first_branch_output: str):
        """Stub subprocess.run so sdr_context.py invocations return canned stdout:
        the FIRST branch gets `first_branch_output`, later ones a valid minimal
        record; the fake spawn renders manifest+report for its run dir."""
        real_run = self.m.subprocess.run
        calls = {"n": 0}
        # hermetic global log (fix-mgh-sdr-host-error-capture): same contract as the
        # _FakeHostMixin patch — tests never touch the real opencode log
        ev_dir = Path(tempfile.mkdtemp(prefix="mgh_launch_glog_"))
        self.addCleanup(shutil.rmtree, ev_dir, ignore_errors=True)
        self.m._opencode_global_log_path = lambda: ev_dir / "opencode.log"

        def fake_run(cmd, **kwargs):
            if any("sdr_context.py" in str(c) for c in cmd):
                calls["n"] += 1
                rd = Path(cmd[cmd.index("--run-dir") + 1])
                self.run_dirs.append(rd)
                if calls["n"] == 1:
                    return subprocess.CompletedProcess(cmd, 0,
                                                       stdout=first_branch_output,
                                                       stderr="")
                payload = {"external_repos": [], "external_skipped": [],
                           "pending_approval": [],
                           "baseline_path": str(rd / "baseline.md"),
                           "baseline_bytes": 0,
                           "baseline_truncated": False,
                           "sensitive_catalog_source": "default-template",
                           "sensitive_catalog_path": str(rd / "sensitive_catalog.json")}
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload),
                                                   stderr="")
            return real_run(cmd, **kwargs)

        def fake_spawn(host, repo, prompt, model=None, spawn_window=None):
            self.spawned.append(host)
            rd = self.run_dirs[-1]
            (rd / "report.html").write_text("<html></html>", encoding="utf-8")
            (rd / "sdr_manifest.json").write_text(
                json.dumps({"report": str(rd / "report.html")}), encoding="utf-8")
            return 0

        self.m.subprocess.run = fake_run
        self.m._spawn_host = fake_spawn
        return real_run

    def test_garbled_stdout_single_branch_failed_not_traceback(self):
        self._no_dead_shell()
        # residual sentinel from a crashed prior run: a failure path must NOT remove it
        (self.repo / ".mgh-sdr").mkdir(exist_ok=True)
        residual = self.repo / ".mgh-sdr" / ".active"
        residual.write_text(json.dumps({"domain": "mgh-sdr", "target": str(self.repo),
                                        "out_roots": [], "read_roots": [], "v": 1}),
                            encoding="utf-8")
        real_run = self._fake_upstream(first_branch_output="")
        try:
            code, out, err = self._launch(["--repo", str(self.repo),
                                           "--branch", "feature-pay"])
        finally:
            self.m.subprocess.run = real_run
        self.assertEqual(code, 1, err)
        self.assertEqual(out, "", "a failed run prints no stdout payload")
        self.assertIn("FAILED BRANCHES (1)", err)
        self.assertIn("upstream output unusable for feature-pay", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.spawned, [], "an unusable upstream record spawns nothing")
        self.assertTrue(residual.is_file(),
                        "the failed path must leave a residual sentinel for recovery")

    def test_multibranch_garbled_first_branch_later_branches_continue(self):
        mb = self.tmp / "branches.txt"
        mb.write_text("feature-pay\nfeature-b2\n", encoding="utf-8")
        real_run = self._fake_upstream(first_branch_output="<<<not json>>>")
        try:
            code, out, err = self._launch(["--repo", str(self.repo),
                                           "--multi-branch", str(mb)])
        finally:
            self.m.subprocess.run = real_run
        self.assertEqual(code, 1, err)
        self.assertIn("upstream output unusable for feature-pay", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(len(self.spawned), 1,
                         "the healthy branch still runs its full flow")
        self.assertNotIn("upstream output unusable for feature-b2", err)
        # exit-code semantics unchanged: >=1 branch FAILED => launcher exit 1
        self.assertIn("FAILED BRANCHES (1)", err)

    def test_empty_json_object_stdout_is_branch_failed(self):
        real_run = self._fake_upstream(first_branch_output="{}")
        try:
            ok, outcome, _ = self.m._run_one(self.repo, "feature-pay", "master",
                                             "claude", None, [], True)
        finally:
            self.m.subprocess.run = real_run
        self.assertFalse(ok)
        self.assertIn("upstream output unusable", outcome)


from datetime import datetime, timedelta, timezone  # noqa: E402  (host-error evidence tests)


class TestHostErrorEvidence(unittest.TestCase, _FakeHostMixin):
    """fix-mgh-sdr-host-error-capture: fanout sub-session provider errors are invisible
    on the parent `run --print-logs` face (they belong to OTHER opencode runs — verified
    2026-10-13 real-repo rerun, findings F1). The launcher therefore extracts
    time-window `level=ERROR` lines from the opencode user-level global log into
    <run-dir>/host_error.log after the host exits — success branches too (errors
    absorbed by opencode's internal retry are evidence), fail-soft (a missing/
    unparsable global log is a stderr note, NEVER a branch failure), and failure
    envelopes carry the evidence pointer (zero captures => recipe names the global
    log instead)."""

    T0 = datetime(2026, 10, 13, 9, 40, 0, tzinfo=timezone.utc)

    def setUp(self):
        self.m = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_launch_ev_"))
        self.glog = self.tmp / "global" / "opencode.log"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- pure extraction function ---

    def _write_log(self, text):
        self.glog.parent.mkdir(parents=True, exist_ok=True)
        self.glog.write_text(text, encoding="utf-8")

    def _extract(self, log_text=None, start=None, end=None):
        if log_text is not None:
            self._write_log(log_text)
        out = self.tmp / "run" / "host_error.log"
        out.parent.mkdir(parents=True, exist_ok=True)
        n = self.m._extract_host_errors(self.glog, start or self.T0,
                                        end or self.T0 + timedelta(minutes=5), out)
        return n, out

    def test_window_capture_and_edges(self):
        n, out = self._extract(
            "timestamp=2026-10-13T09:39:59.000Z level=ERROR old failure\n"
            "timestamp=2026-10-13T09:40:00.000Z level=ERROR at start\n"
            "timestamp=2026-10-13T09:40:30.000Z level=INFO noise\n"
            "timestamp=2026-10-13T09:40:30.500Z level=ERROR socket closed 断连\n"
            "timestamp=2026-10-13T09:40:31.000Z level=WARN warn noise\n"
            "timestamp=2026-10-13T09:45:00.000Z level=ERROR at end\n"
            "timestamp=2026-10-13T09:45:01.000Z level=ERROR after end\n")
        self.assertEqual(n, 2, "start-inclusive, end-exclusive, ERROR-only")
        body = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len([l for l in body if not l.startswith("#")]), 2)
        self.assertIn("at start", body[2])
        self.assertIn("socket closed 断连", body[3])
        self.assertNotIn("old failure", "\n".join(body))
        self.assertNotIn("at end", "\n".join(body))
        self.assertNotIn("after end", "\n".join(body))
        self.assertNotIn("WARN", "\n".join(body))

    def test_header_carries_source_and_utc_window(self):
        n, out = self._extract(
            "timestamp=2026-10-13T09:41:00.000Z level=ERROR boom\n")
        self.assertEqual(n, 1)
        head = out.read_text(encoding="utf-8").splitlines()[:2]
        self.assertTrue(head[0].startswith("# source: "))
        self.assertIn(str(self.glog), head[0])
        self.assertTrue(head[1].startswith("# window: "))
        self.assertIn("(UTC)", head[1])

    def test_error_line_without_parsable_timestamp_refuses_evidence(self):
        # an ERROR-shaped line we cannot time-bind makes the whole slice untrustworthy:
        # refuse it entirely (no file) rather than emit evidence of unknown provenance
        n, out = self._extract(
            "timestamp=2026-10-13T09:41:00.000Z level=INFO ok line\n"
            "level=ERROR no timestamp at all\n")
        self.assertIsNone(n)
        self.assertFalse(out.exists())
        n, out = self._extract(
            "timestamp=2026-10-13T09:41:00.000Z level=INFO ok line\n"
            "timestamp=not-a-date level=ERROR garbage timestamp\n")
        self.assertIsNone(n)
        self.assertFalse(out.exists())

    def test_naive_and_offset_timestamps_read_as_utc(self):
        n, out = self._extract(
            "timestamp=2026-10-13T09:40:30.000 level=ERROR naive\n"
            "timestamp=2026-10-13T17:40:31.000+08:00 level=ERROR offset\n")
        self.assertEqual(n, 2)
        self.assertIn("naive", out.read_text(encoding="utf-8"))
        self.assertIn("offset", out.read_text(encoding="utf-8"))

    def test_zero_capture_writes_header_only(self):
        n, out = self._extract(
            "timestamp=2026-10-13T09:39:00.000Z level=ERROR outside window\n")
        self.assertEqual(n, 0)
        lines = out.read_text(encoding="utf-8").splitlines()
        self.assertEqual([l for l in lines if not l.startswith("#")], [],
                         "header-only => 'extracted, zero captures' is distinguishable")

    def test_missing_log_is_not_extracted_no_file(self):
        n, out = self._extract()
        self.assertIsNone(n)
        self.assertFalse(out.exists())

    def test_log_without_any_timestamp_key_is_refused(self):
        # non-empty content with no `timestamp=` anywhere: upstream format drift —
        # refuse (same absent state) instead of a silent header-only "no errors"
        n, out = self._extract("level=ERROR something\nplain text\n")
        self.assertIsNone(n)
        self.assertFalse(out.exists())

    # --- integration through _run_one / main with a fake host + fake global log ---

    def _install_ev_fakes(self, spawn_code=0, error_in_window=False, host="opencode"):
        self._two_branch_repo()
        self._install_fakes(self.m, spawn_code=spawn_code)
        self.m._opencode_global_log_path = lambda: self.glog
        self.m._detect_host = lambda explicit=None: host
        m = self.m

        def fake_spawn(h, repo, prompt, model=None, spawn_window=None):
            self.spawned.append(h)
            if spawn_window is not None:
                spawn_window.append(datetime.now(timezone.utc))
            if error_in_window:
                glog = m._opencode_global_log_path()
                glog.parent.mkdir(parents=True, exist_ok=True)
                with open(glog, "a", encoding="utf-8") as f:
                    f.write(f"timestamp={datetime.now(timezone.utc).isoformat()} "
                            "level=ERROR session=fan-1 AI_APICallError: socket 断连\n")
            rd = self.run_dirs[-1]
            (rd / "report.html").write_text("<html></html>", encoding="utf-8")
            (rd / "sdr_manifest.json").write_text(
                json.dumps({"report": str(rd / "report.html")}), encoding="utf-8")
            return spawn_code

        m._spawn_host = fake_spawn

    def _launch_branch(self, spawn_code=0, error_in_window=False, host="opencode"):
        self._install_ev_fakes(spawn_code=spawn_code, error_in_window=error_in_window,
                               host=host)
        return self._launch(["--repo", str(self.repo), "--branch", "feature-pay"])

    def _ev_file(self):
        run_dir = next((self.repo / ".mgh-sdr" / "runs").glob("*-feature-pay"))
        return run_dir / "host_error.log"

    def test_success_branch_captures_evidence_too(self):
        # errors ABSORBED by opencode's internal retry still leave evidence (N4 sample:
        # 2 stream errors, branch converged 4/4) — extraction runs on success as well
        code, out, err = self._launch_branch(error_in_window=True)
        self.assertEqual(code, 0, err)
        ev = self._ev_file()
        self.assertTrue(ev.is_file())
        body = ev.read_text(encoding="utf-8")
        self.assertIn("AI_APICallError", body)
        self.assertIn("# source:", body)
        self.assertIn("host error evidence", err)
        self.assertIn("1 ERROR line(s)", err)

    def test_failure_envelope_and_summary_carry_evidence_pointer(self):
        code, out, err = self._launch_branch(spawn_code=3, error_in_window=True)
        self.assertEqual(code, 1, out)
        self.assertIn("host CLI exited 3 for feature-pay (host error evidence: ", err)
        self.assertIn(str(self._ev_file()), err)
        self.assertIn("FAILED BRANCHES (1)", err)

    def test_zero_capture_failure_recipe_names_global_log(self):
        # evidence file extracted but header-only => the failure reason must point at
        # the global log (the only place a root cause could still live)
        self._write_log("timestamp=2020-01-01T00:00:00.000Z level=ERROR ancient\n")
        code, out, err = self._launch_branch(spawn_code=3)
        self.assertEqual(code, 1, out)
        self.assertIn("no host error line captured", err)
        self.assertIn(str(self.glog), err)

    def test_claude_host_skips_extraction(self):
        code, out, err = self._launch_branch(error_in_window=True, host="claude")
        self.assertEqual(code, 0, err)
        self.assertFalse(self._ev_file().exists(),
                         "claude takes no log flags and has no extraction face")
        self.assertNotIn("host error evidence", err)

    def test_missing_global_log_is_fail_soft(self):
        # diagnosability tooling must NEVER become a new failure source: the branch
        # stays ok, the note names the assumed path (self-exposure on routing drift)
        code, out, err = self._launch_branch(error_in_window=False)
        self.assertEqual(code, 0, err)
        self.assertFalse(self._ev_file().exists())
        self.assertIn("not extracted", err)
        self.assertIn(str(self.glog), err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
