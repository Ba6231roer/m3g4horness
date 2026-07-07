#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""R2 zero-runtime-dependency AST scan for core/scripts/*.py (R5.8 regression).

Every shipped script MUST import only the Python stdlib or a sibling module that
lives in the same scripts/ dir (e.g. merge_scout imports discover_controls). Fails
on any third-party import. Covers assemble_rules.py. Run: py -3 tests/test_zero_deps.py
"""
import ast, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"


class TestZeroRuntimeDeps(unittest.TestCase):
    def test_scripts_import_only_stdlib_or_siblings(self):
        siblings = {p.stem for p in SCRIPTS.glob("*.py")}
        stdlib = set(sys.stdlib_module_names)
        violations = []
        for py in sorted(SCRIPTS.glob("*.py")):
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        top = n.name.split(".")[0]
                        if top not in stdlib and top not in siblings:
                            violations.append(f"{py.name}: import {n.name}")
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    top = node.module.split(".")[0]
                    if top not in stdlib and top not in siblings:
                        violations.append(f"{py.name}: from {node.module} import ...")
        self.assertFalse(
            violations,
            "third-party imports found (R2 violation):\n  " + "\n  ".join(violations))

    def test_assemble_rules_is_scanned(self):
        # explicit guard: the new script exists and is therefore covered by the glob
        self.assertTrue((SCRIPTS / "assemble_rules.py").is_file())

    def test_new_init_scripts_are_scanned(self):
        # harden-mgh-init-orchestration-discipline additions exist + are glob-scanned
        for s in ("list_scout_batches", "list_rule_jobs", "describe_artifact",
                  "validate_inventory"):
            self.assertTrue((SCRIPTS / f"{s}.py").is_file(),
                            f"{s}.py missing — not covered by the zero-dep scan")

    def test_new_sast_scripts_are_scanned(self):
        # harden-mgh-sast-orchestration-discipline + add-mgh-sast-design-controls
        # additions exist + are glob-scanned
        for s in ("list_chunks", "list_verify_jobs", "load_controls"):
            self.assertTrue((SCRIPTS / f"{s}.py").is_file(),
                            f"{s}.py missing — not covered by the zero-dep scan")


if __name__ == "__main__":
    unittest.main(verbosity=2)
