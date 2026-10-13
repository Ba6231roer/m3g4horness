#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""dsh shim parity (add-mgh-dsh-host-foundation tasks 4.1-4.3) — the THIRD wiring face.

Invariants (mirrors test_opencode_hook_parity's posture, extended to three faces):
  (A) Guard byte-parity — ALL THREE mirrored guard copies (claude canonical, opencode twin,
      core/scripts canonical, and the dsh sibling landing copy is produced by install from
      core/scripts) must be byte-identical: releases/claude-code/hooks ==
      releases/opencode/hooks == core/scripts/block_adhoc_scripts.py. Single decision
      source, CI fail on drift (R5.8).
  (B) Normalization parity — the dsh `tools/pre-execute` event, normalized by the shim's
      TOOL_MAP + arg renaming (mirrored in Python below as the contract under test), yields
      the SAME guard decision AND the same stderr recipe text as the claude and opencode
      faces for one violation fixture fed three ways.
  (C) Shim is glue-only — the dsh .ts carries the tool table + spawn + exit-code
      translation, and NEVER a decision regex / allowlist / subtree list.

Run: py tests/test_dsh_hook_parity.py
"""
import contextlib, importlib.util, io, json, os, re, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CC_GUARD = ROOT / "releases" / "claude-code" / "hooks" / "block_adhoc_scripts.py"
OC_GUARD = ROOT / "releases" / "opencode" / "hooks" / "block_adhoc_scripts.py"
CORE_GUARD = ROOT / "core" / "scripts" / "block_adhoc_scripts.py"
DSH_SHIM = ROOT / "releases" / "dsh" / "plugins" / "mgh-guard.ts"


def _load_guard(path, name="block_adhoc_scripts_dsh"):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- dsh shim mirror (contract under test; MUST stay in lockstep with mgh-guard.ts) ------
# TOOL_MAP is statically parsed from the .ts (no TS execution — same convention as the
# opencode HANDLED parse). normalize() below mirrors the shim's arg renaming ONLY.
def _dsh_tool_map():
    src = DSH_SHIM.read_text(encoding="utf-8")
    m = re.search(r'export const TOOL_MAP = \{(.*?)\} as const', src, re.DOTALL)
    assert m, "TOOL_MAP not found in mgh-guard.ts"
    body = re.sub(r'//[^\n]*', '', m.group(1))
    return dict(re.findall(r'(\w+)\s*:\s*"([A-Za-z_]+)"', body))


def dsh_normalize(tool, args):
    """Mirror of mgh-guard.ts normalize(): dsh tool ids/fields -> guard payload."""
    name = _dsh_tool_map().get(tool)
    if not name:
        return None
    a = args or {}
    if name == "Bash":
        return {"tool_name": "Bash", "tool_input": {"command": str(a.get("command", ""))}}
    if name == "Glob":
        return {"tool_name": "Glob", "tool_input": {"pattern": str(a.get("pattern", "")),
                                                    "path": str(a.get("path", ""))}}
    if name == "Grep":
        return {"tool_name": "Grep", "tool_input": {
            "pattern": str(a.get("pattern", "")), "path": str(a.get("path", "")),
            "glob": str(a.get("include") or a.get("glob") or "")}}
    if name == "ApplyPatch":
        cmd, path = str(a.get("command", "")), str(a.get("path", ""))
        paths, ops = [], []
        if path and cmd == "create":
            paths, ops = [path], ["add"]
        elif path and cmd in ("str_replace", "insert"):
            paths, ops = [path], ["update"]
        return {"tool_name": "ApplyPatch", "tool_input": {"paths": paths, "operations": ops}}
    if name in ("RunCode", "TerminalIO", "JobCtl"):
        return {"tool_name": name, "tool_input": {}}
    return {"tool_name": name, "tool_input": {
        "file_path": str(a.get("file_path") or a.get("path") or "")}}


def _run_guard(mod, payload, domain_env="MGH_INIT_ACTIVE", target=None):
    keys = ("MGH_INIT_ACTIVE", "MGH_SAST_ACTIVE", "MGH_SRA_ACTIVE", "MGH_SRR_ACTIVE",
            "MGH_SDR_ACTIVE", "MGH_UT_INIT_ACTIVE")
    old = {k: os.environ.pop(k, None) for k in keys}
    old_target = os.environ.pop("MGH_TARGET", None)
    if domain_env:
        os.environ[domain_env] = "1"
    if target:
        os.environ["MGH_TARGET"] = target
    old_stdin, sys.stdin = sys.stdin, io.StringIO(json.dumps(payload))
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.stdin = old_stdin
        for k, v in old.items():
            if v is not None:
                os.environ[k] = v
        if old_target is not None:
            os.environ["MGH_TARGET"] = old_target
    return code, err.getvalue()


class TestGuardByteParityThreeWay(unittest.TestCase):
    """(A) all mirrored guard copies byte-identical — one decision source across faces."""

    def test_core_canonical_matches_claude_twin(self):
        self.assertEqual(CORE_GUARD.read_bytes(), CC_GUARD.read_bytes(),
                         "core/scripts vs releases/claude-code guard drift")

    def test_opencode_twin_matches_claude_canonical(self):
        self.assertEqual(OC_GUARD.read_bytes(), CC_GUARD.read_bytes(),
                         "opencode vs claude guard drift (byte-parity, R5.8)")


class TestThreeFaceFixture(unittest.TestCase):
    """(B) one violation, three faces: claude `Write` / opencode `write` / dsh `write` ->
    same exit code AND same stderr recipe text (guard is the single decision source)."""

    def setUp(self):
        self.m = _load_guard(CORE_GUARD)
        self.out_path = "D:\\mgh-parity\\evil.txt"

    def _claude_payload(self):
        return {"tool_name": "Write", "tool_input": {"file_path": self.out_path}}

    def test_three_faces_same_verdict_and_recipe(self):
        cc = self._claude_payload()                             # claude face: native payload
        oc = dsh_normalize("write", {"file_path": self.out_path})  # dsh face: normalized
        # opencode face: its shim maps `write` -> Write/file_path too (same normalized shape,
        # proven in test_opencode_hook_parity; here the shared normalized payload stands in).
        oc_event = {"tool_name": "Write", "tool_input": {"file_path": self.out_path}}
        results = [_run_guard(self.m, p, target="D:\\mgh-parity\\target")
                   for p in (cc, oc_event, oc)]
        codes = [c for c, _ in results]
        self.assertEqual(codes, [2, 2, 2], "three-face out-of-tree write must all block")
        self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(results[0][1], results[2][1])  # recipe text identical (single source)

    def test_dsh_run_code_denied_in_domain(self):
        code, err = _run_guard(self.m, dsh_normalize("run_code", {"code": "print(1)"}))
        self.assertEqual(code, 2)
        self.assertIn("bundled code-runner", err)

    def test_dsh_job_kill_denied_in_domain(self):
        code, err = _run_guard(self.m, dsh_normalize("job_kill", {"job_id": "j1"}))
        self.assertEqual(code, 2)
        self.assertIn("background-job", err)

    def test_dsh_pwsh_out_of_tree_write_denied(self):
        code, err = _run_guard(self.m,
                               dsh_normalize("pwsh", {"command": f'Set-Content {self.out_path} x'}),
                               target="D:\\mgh-parity\\target")
        self.assertEqual(code, 2)
        self.assertIn("out-of-tree write", err)

    def test_dsh_bash_legit_leaf_passes(self):
        code, _ = _run_guard(self.m,
                             dsh_normalize("bash", {"command":
                                 "py .claude/mgh-core/scripts/discover_controls.py --repo . --out .mgh-init"}))
        self.assertEqual(code, 0)

    def test_dsh_str_replace_editor_out_of_tree_denied(self):
        code, err = _run_guard(self.m,
                               dsh_normalize("str_replace_editor",
                                             {"command": "str_replace", "path": self.out_path,
                                              "old_str": "a", "new_str": "b"}),
                               target="D:\\mgh-parity\\target")
        self.assertEqual(code, 2)
        self.assertIn("ApplyPatch", err)

    def test_unmapped_dsh_id_not_normalized(self):
        self.assertIsNone(dsh_normalize("web_fetch", {"url": "https://x"}))


class TestShimIsGlueOnly(unittest.TestCase):
    """(C) the dsh .ts must never grow decision logic (single-source guard contract)."""

    def test_shim_has_no_decision_constants(self):
        text = DSH_SHIM.read_text(encoding="utf-8")
        # no allowlist / regex decision shapes may leak into the shim
        self.assertNotIn("_ALLOWLIST_SUBTREES", text)
        self.assertNotIn("MGH_TARGET tree", text)  # confinement wording belongs to the guard
        self.assertNotIn("sanctioned subtree", text)

    def test_shim_feeds_guard_via_buffer_and_py_fallback(self):
        text = DSH_SHIM.read_text(encoding="utf-8")
        self.assertIn('["py", "python3", "python"]', text)  # spike-verified fallback order
        self.assertIn("Buffer.from(", text)                 # one-shot buffer write
        self.assertIn("block_adhoc_scripts.py", text)      # spawns the shared guard

    def test_shim_fails_soft_on_missing_guard_file(self):
        """python exits 2 (`can't open file ...`) for a MISSING guard script — the same exit
        code as a deny. The shim MUST pre-check the guard file (node:fs existsSync) before
        spawning and treat a can't-open-file exit 2 as fail-soft pass + one diagnostic,
        NEVER as a deny (a skewed/missing install used to deny every handled call)."""
        text = DSH_SHIM.read_text(encoding="utf-8")
        self.assertIn("existsSync", text)         # spawn-time existence pre-check
        self.assertIn("node:fs", text)            # stdlib import (Bun-compatible)
        self.assertIn("can't open file", text)    # exit-2 signature fallback (fail-soft)

    def test_deny_shape_matches_host_contract(self):
        text = DSH_SHIM.read_text(encoding="utf-8")
        self.assertIn('kind: "deny"', text)
        self.assertIn("tools/pre-execute", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
