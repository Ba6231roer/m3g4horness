#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_distributed_purity.py regression (R5.10 / R5.8).

Subprocess-runs the lint and asserts: (1) the real shipped-md set is clean
(CI gate — a leaked `R5.2` / `(D12)` MUST fail CI); (2) reverse cases — planting
each prohibited class into a fixture yields exit 2; (3) operational paths /
stage labels are NOT false positives (exit 0); (4) `--allowlist` suppresses a
known false positive; (5) the lint itself is zero-runtime-dep + `--help` works.
Run: py tests/test_distributed_md_purity.py
"""
import ast, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE.parent / "tools" / "check_distributed_purity.py"
PY = sys.executable


def run_lint(*extra):
    # lint emits utf-8 (it reconfigures its streams); decode the same way so the
    # host locale (e.g. cp936/gbk on Chinese Windows) never corrupts tokens like
    # 范式锚点 or the ✗/✓ glyphs in diagnostics.
    r = subprocess.run([PY, str(LINT), *extra], capture_output=True)
    r.stdout = r.stdout.decode("utf-8", "replace")
    r.stderr = r.stderr.decode("utf-8", "replace")
    return r


class TestDistributedPurity(unittest.TestCase):
    # --- forward: the real shipped set MUST be clean (CI gate) ---
    def test_default_scope_clean(self):
        r = run_lint()
        self.assertEqual(r.returncode, 0,
                         f"shipped md has dev-only provenance (R5.10):\n{r.stderr}")
        d = json.loads(r.stdout)
        self.assertGreater(d["scanned"], 80)          # ~91 shipped md files
        self.assertEqual(d["violations"], [])

    # --- add-mgh-sast-design-controls: new fragment + contract are distributed → scanned + clean
    def test_new_controls_artifacts_scanned_and_clean(self):
        root = HERE.parent
        files = [root / "core" / "prompts" / "fragments" / "controls-context.md",
                 root / "core" / "contracts" / "sast" / "controls-intake.md"]
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- improve-mgh-init-codegraph-enrichment: new codegraph artifacts are distributed → scanned + clean
    def test_new_codegraph_artifacts_scanned_and_clean(self):
        root = HERE.parent
        files = [root / "core" / "prompts" / "fragments" / "codegraph-hint.md",
                 root / "core" / "prompts" / "stages" / "init-resolve.md",
                 root / "core" / "contracts" / "init" / "resolved.md",
                 root / "releases" / "claude-code" / "agents" / "init-resolve.md",
                 root / "releases" / "opencode" / "agent" / "init-resolve.md"]
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- improve-mgh-sra-codegraph-enrichment: edited SRA codegraph artifacts are distributed → scanned + clean
    def test_sra_codegraph_artifacts_scanned_and_clean(self):
        root = HERE.parent
        files = [root / "core" / "prompts" / "stages" / "sra-augment.md",
                 root / "core" / "prompts" / "stages" / "sra-clarify.md",
                 root / "core" / "prompts" / "stages" / "sra-consistency.md",
                 root / "core" / "contracts" / "sra" / "augmentation.md",
                 root / "releases" / "claude-code" / "agents" / "sra-augment.md",
                 root / "releases" / "claude-code" / "agents" / "sra-clarify.md",
                 root / "releases" / "claude-code" / "agents" / "sra-consistency.md",
                 root / "releases" / "opencode" / "agent" / "sra-augment.md",
                 root / "releases" / "opencode" / "agent" / "sra-clarify.md",
                 root / "releases" / "opencode" / "agent" / "sra-consistency.md"]
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- add-mgh-srr: new SRR command shells + contract are distributed → scanned + clean.
    #     SRR reuses the sra stage prompts (no new prompts), so only the two shells + the
    #     intake/report contract are new distributed md.
    def test_srr_artifacts_scanned_and_clean(self):
        root = HERE.parent
        files = [root / "releases" / "claude-code" / "commands" / "mgh-srr.md",
                 root / "releases" / "opencode" / "command" / "mgh-srr.md",
                 root / "core" / "contracts" / "srr" / "intake-report.md"]
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- codegraph as an operational external-tool reference is NOT a dev-meta violation
    def test_codegraph_reference_not_flagged(self):
        body = ("When codegraph=on, call codegraph_explore or `codegraph explore` (Bash);\n"
                "emit source:\"codegraph\" candidates with a resolved_path[].\n")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- contract surface ---
    def test_help_exits_zero(self):
        self.assertEqual(run_lint("--help").returncode, 0)

    # --- reverse: each prohibited class is caught (exit 2) ---
    def _assert_caught(self, body):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 2, f"expected violation for: {body!r}")
            d = json.loads(r.stdout)
            self.assertEqual(len(d["violations"]), 1)
            return d

    def test_catches_rule_id(self):
        self._assert_caught("see rule R5.2 for details\n")

    def test_catches_failure_id(self):
        self._assert_caught("closes the FD8 gap\n")

    def test_catches_decision_id(self):
        d = self._assert_caught("isolated context for ONE cluster (D12)\n")
        self.assertEqual(d["violations"][0]["hits"][0]["pattern"], "decision_id")

    def test_catches_dev_manual_xref(self):
        self._assert_caught("See AGENTS.md R1–R4 for the rules\n")

    def test_catches_change_folder(self):
        self._assert_caught("Part of improve-mgh-init-llm-discovery\n")

    def test_catches_upstream_doc(self):
        self._assert_caught("concept (glasswing_docs/09 §1.1)\n")

    def test_catches_dev_file_ptr(self):
        self._assert_caught("see task.260630.md for the plan\n")

    def test_catches_dev_meta(self):
        self._assert_caught("assemble_rules.py --check 为范式锚点\n")

    # --- preserve: operational paths / stage labels are NOT flagged ---
    def test_preserves_operational_paths_and_labels(self):
        body = ("py .claude/mgh-core/scripts/list_clusters.py --check\n"   # runtime path
                "T1 per-cluster, T2 synthesis, s1..s9 stages\n"            # stage labels
                "write to <target>/AGENTS.md, never directly\n")           # output dest
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- allowlist suppresses a known false positive ---
    def test_allowlist_suppresses(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "f.md"
            f.write_text("leaked R5.2 here\n", encoding="utf-8")
            al = root / "fp.txt"
            al.write_text("f.md:1\n", encoding="utf-8")
            r = run_lint("--files", str(f), "--allowlist", str(al), "--root", str(root))
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["violations"], [])
            self.assertEqual(d["allowlisted"], 1)

    # --- self-contained & offline (R5.3a / R2) ---
    def test_lint_is_zero_runtime_deps(self):
        siblings = {p.stem for p in (HERE.parent / "tools").glob("*.py")}
        stdlib = set(sys.stdlib_module_names)
        violations = []
        tree = ast.parse(LINT.read_text(encoding="utf-8"), filename=str(LINT))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    top = n.name.split(".")[0]
                    if top not in stdlib and top not in siblings:
                        violations.append(f"import {n.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                if top not in stdlib and top not in siblings:
                    violations.append(f"from {node.module} import ...")
        self.assertFalse(violations, "third-party imports in lint:\n  " +
                         "\n  ".join(violations))


if __name__ == "__main__":
    unittest.main(verbosity=2)
