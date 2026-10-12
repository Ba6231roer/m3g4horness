#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Real-machine /mgh-sdr failure chain,固化 as an end-to-end counterexample set.

The transcript being replayed: the orchestrator (1) invented an approval flag on
sdr_context.py, then in the trial-and-error window that followed (the guard was
dormant back then: the sentinel only existed as a step-1 success side effect) it
(2) fed inline code to the interpreter via a stdin heredoc, (3) redirected step-1
stdout to a /tmp file and read it back, and (4) processed the产物 with `py -c`.
All three later actions actually SUCCEEDED on the real machine.

After the hardening: step 0 pre-arms the sentinel (`resume_sdr_state.py
--arm-sentinel`), the invented flag fails with a copy-pasteable recipe that points
at the now-real `--approve-external` closure, and actions 2-4 are blocked
(exit code 2 + recipe) by the awake guard. This file wires those pieces into ONE
chain per file, driving the real scripts as subprocesses and the real guard hook
as a subprocess with a stdin payload (no in-process shortcuts).

Run: py tests/test_sdr_failure_chain.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTEXT = ROOT / "core" / "scripts" / "sdr_context.py"
RESUME = ROOT / "core" / "scripts" / "resume_sdr_state.py"
GUARD = ROOT / "releases" / "claude-code" / "hooks" / "block_adhoc_scripts.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


class SdrFailureChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_sdrchain_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "AGENTS.md").write_text(
            "# 项目\n## 安全设计\n- 横向越权:查询须带 brch_no + UserInfo 校验。\n"
            "- SQL 注入:MyBatis 一律 #{} 预编译。\n",
            encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "init")
        _git(self.repo, "checkout", "-qb", "feature-pay")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "PayController.java").write_text(
            '@RestController\npublic class PayController {\n'
            '    @PostMapping("/pay/quick")\n    public String q() { return "ok"; }\n}\n',
            encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "feat")
        self.run_dir = self.repo / ".mgh-sdr" / "runs" / "t1"
        # the shell's step 0 creates the run dir (mkdir -p) before pre-arming
        self.run_dir.mkdir(parents=True)
        # declared-but-unapproved external front repo (the real-machine shape)
        self.front = self.tmp / "front"
        self.front.mkdir()
        (self.repo / "docs" / "security-controls").mkdir(parents=True)
        (self.repo / "docs" / "security-controls" / "ext-front.md").write_text(
            f"本地前端项目地址 {self.front.as_posix()},前端分支名与本项目一致;\n"
            "垂直越权以 buttonAuth.properties 配置为准。\n",
            encoding="utf-8")
        _git(self.front, "init", "-q")
        _git(self.front, "config", "user.email", "t@t")
        _git(self.front, "config", "user.name", "t")
        (self.front / "config").mkdir()
        (self.front / "config" / "buttonAuth.properties").write_text("x=1\n",
                                                                     encoding="utf-8")
        (self.front / "src").mkdir()
        (self.front / "src" / "pay.vue").write_text("axios.post('/pay/quick')\n",
                                                    encoding="utf-8")
        _git(self.front, "add", "-A")
        _git(self.front, "commit", "-qm", "init")
        _git(self.front, "checkout", "-qb", "feature-pay")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- drivers -----------------------------------------------------------

    def _context(self, *extra):
        p = subprocess.run([sys.executable, str(CONTEXT),
                            "--repo", str(self.repo), "--run-dir", str(self.run_dir),
                            "--base", "master", "--branch", "feature-pay", *extra],
                           capture_output=True, cwd=str(self.repo))
        return p.returncode, p.stdout.decode("utf-8", "replace"), \
            p.stderr.decode("utf-8", "replace")

    def _arm(self):
        p = subprocess.run([sys.executable, str(RESUME),
                            "--run-dir", str(self.run_dir), "--repo", str(self.repo),
                            "--arm-sentinel"],
                           capture_output=True, cwd=str(self.repo))
        return p.returncode, p.stdout.decode("utf-8", "replace"), \
            p.stderr.decode("utf-8", "replace")

    def _guard(self, command, env):
        """Run the real guard hook with a stdin payload; stderr is decoded leniently
        (the recipe's Chinese lines are emitted in the host console codepage)."""
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
        p = subprocess.run([sys.executable, str(GUARD)],
                           input=payload.encode("utf-8"), capture_output=True,
                           env=env, cwd=str(self.repo))
        return p.returncode, p.stderr.decode("utf-8", "replace")

    def _guard_bash(self, command):
        """Run the REAL guard hook as a subprocess (stdin payload) inside the sdr
        run-domain; returns (exit_code, stderr)."""
        env = dict(os.environ)
        for k in list(env):
            if k.startswith("MGH_"):
                env.pop(k, None)
        env["MGH_SDR_ACTIVE"] = "1"
        return self._guard(command, env)

    # --- the chain ----------------------------------------------------------

    def test_failure_chain_replayed_blocked_or_guided(self):
        # ACTION 0 (the window fix): step 0 pre-arms the sentinel BEFORE step 1 can
        # fail — from here on the guard is awake for every later Bash call.
        code, out, err = self._arm()
        self.assertEqual(code, 0, err)
        armed = json.loads(out)
        self.assertTrue(armed["armed"])
        sentinel = self.repo / ".mgh-sdr" / ".active"
        self.assertTrue(sentinel.is_file())

        # ACTION 1 (invented approval flag): fails loud, but the error carries a
        # copy-pasteable recipe pointing at the sanctioned closure.
        code, out, err = self._context("--approve-external-repo", str(self.front))
        self.assertEqual(code, 2)
        self.assertIn("unrecognized arguments", err)
        self.assertIn("recipe", err)
        m = re.search(r"^\s+py \S*sdr_context\.py --repo <abs> --run-dir <abs> "
                      r"--approve-external <abs-dir>", err, re.M)
        self.assertIsNotNone(m, "recipe line for --approve-external must be copy-pasteable")

        # GUIDED PATH: the recipe line, transcribed verbatim with the real dirs
        # filled in, closes approval + retrieval in ONE run.
        code, out, err = self._context("--approve-external", str(self.front))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["pending_approval"], [])
        self.assertEqual([e["path"] for e in d["external_repos"]], [str(self.front)])
        cfg = json.loads((self.repo / ".mgh" / "read-roots.json").read_text(encoding="utf-8"))
        self.assertEqual([str(Path(x).resolve()) for x in cfg["read_roots"]],
                         [str(self.front.resolve())])

        # ACTION 2 (heredoc inline): blocked by SHAPE alone, recipe names the
        # sanctioned inspection primitive.
        code, err = self._guard_bash(
            "py sdr_context.py --repo . --run-dir . | "
            "python3 - <<'EOF'\nimport sys, json\nprint(json.load(sys.stdin))\nEOF")
        self.assertEqual(code, 2)
        self.assertIn("inline interpreter code", err)
        self.assertIn("describe_artifact.py", err)

        # ACTION 3 (> /tmp file intermediary + read-back): blocked.
        code, err = self._guard_bash(
            "py sdr_context.py --repo . --run-dir . > /tmp/sdr_out.json; "
            "cat /tmp/sdr_out.json | head -c 400")
        self.assertEqual(code, 2)
        self.assertIn("temp-dir write + read-back", err)
        self.assertIn("describe_artifact.py", err)

        # ACTION 4 (py -c processing the产物): blocked.
        code, err = self._guard_bash(
            "py -c \"import json;d=json.load(open('.mgh-sdr/runs/t1/context.json'));"
            "print(list(d))\"")
        self.assertEqual(code, 2)
        self.assertIn("py -c", err)
        self.assertIn("describe_artifact.py", err)

    def test_guard_awake_after_step1_failure_via_sentinel_only(self):
        # opencode boundary: the plugin process never inherits the bash-exported
        # MGH_*_ACTIVE env. Activation must come from the step-0 sentinel on disk,
        # so a step-1 argparse failure (script exits BEFORE its co-write) leaves
        # the guard AWAKE for the trial-and-error window that follows.
        code, out, err = self._arm()
        self.assertEqual(code, 0, err)
        code, _, _ = self._context("--approve-external-repo", str(self.front))
        self.assertEqual(code, 2)  # step 1 died pre-write: sentinel is still the armed one
        self.assertTrue((self.repo / ".mgh-sdr" / ".active").is_file())

        env = dict(os.environ)
        for k in list(env):
            if k.startswith("MGH_"):
                env.pop(k, None)  # NO env activation (mid-session opencode)
        code, err = self._guard("py - <<< \"print(1)\"", env)
        self.assertEqual(code, 2)
        self.assertIn("inline interpreter code", err)

        # baseline sanity: without the sentinel (never armed) the same command passes
        (self.repo / ".mgh-sdr" / ".active").unlink()
        code, _ = self._guard("py - <<< \"print(1)\"", env)
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
