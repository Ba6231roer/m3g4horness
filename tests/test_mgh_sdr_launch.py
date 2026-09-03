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

    def test_dry_run_artifacts_complete(self):
        code, out, err = self._launch(["--repo", str(self.repo),
                                       "--branch", "feature-pay", "--dry-run"])
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(payload["branches"], ["feature-pay"])
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
