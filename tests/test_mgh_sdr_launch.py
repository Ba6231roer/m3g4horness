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


import shutil  # noqa: E402  (tearDown uses it; placed here to keep the header import list stdlib-honest)

if __name__ == "__main__":
    unittest.main(verbosity=2)
