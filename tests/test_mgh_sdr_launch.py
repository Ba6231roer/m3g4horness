#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Launcher self-test for mgh_sdr_launch.py (add-mgh-sdr task 5.2).

Builds a TEMP git pair (main repo with a feature branch + a fake external frontend repo),
runs the launcher with --dry-run (ZERO host-CLI spawn), and asserts the artifacts:
gates pass, sdr_context artifacts (baseline/external conclusions/context.json) exist,
the sentinel is written with read_roots[] = the searched external root, the orchestrator
prompt file carries the verbatim absolute paths, and --dry-run KEEPS the sentinel.
Also covers misuse gates: missing --repo (2), non-git repo (2), unknown --host (2),
missing multi-branch file (2).

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

        def fake_context(repo, run_dir, base, branch, dims, read_roots,
                         no_codegraph=False):
            self.run_dirs.append(Path(run_dir))
            return {"external_repos": [], "external_skipped": [],
                    "pending_approval": [],
                    "baseline_path": str(self.repo / "baseline.md"),
                    "baseline_truncated": False,
                    "sensitive_catalog_source": "default-template",
                    "sensitive_catalog": {}}

        def fake_spawn(host, repo, prompt, model=None):
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
        def fake_spawn_broken(host, repo, prompt, model=None):
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
        self.assertEqual(cmd[2:5], ["--print-logs", "--log-level", "ERROR"])
        self.m._spawn_host("claude", self.repo, "p")
        cmd, _ = self._last()
        self.assertNotIn("--print-logs", cmd)
        self.assertNotIn("--log-level", cmd)

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

        def fake_spawn(host, repo, prompt, model=None):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
