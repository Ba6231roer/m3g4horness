#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Recipe-visibility lint (tools/check_contracts.py, design D6) regression tests.

Forward: the CURRENT repo state must pass (every script the guard's block-time recipe
names is literally reachable in its domain's shells ∪ the shared discipline fragment).
Reverse (the task-6.3 shape): strip the `describe_artifact.py` literal from the sdr
instruction surface -> the check MUST fail naming (mgh-sdr, describe_artifact.py);
restore -> pass. The pure-function core is driven with synthetic guard text as well so
the region parsing itself (_WORKLIST block + _recipe body, nothing past `def`) is pinned.

Run: py tests/test_recipe_visibility.py
"""
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))

import check_contracts as cc  # noqa: E402

# Synthetic guard slice with the same shapes as the real file.
_GUARD_SNIPPET = '''
_SOMETHING = 1
_WORKLIST = {
    "mgh-sdr": "diff_group.py --materialize / render_sdr_report.py stdout",
    "mgh-init": "list_clusters.py",
}
def _recipe(domain: str) -> str:
    return ("  work-list -> {_WORKLIST.get(domain)}\\n"
            "  structure -> describe_artifact.py --keys/--field\\n")
def _read_recipe(domain: str) -> str:
    return "noise mentioning chunk_sources.py must NOT leak into _recipe"
'''
_SDR_SHELL = "run py <mgh-core>/scripts/diff_group.py ... then render_sdr_report.py --check"
_INIT_SHELL = "py list_clusters.py --target <abs>"
_FRAGMENT_OK = "**瞄一眼结构** → `describe_artifact.py`（`--keys/--sample/--shape/--field`）"
_FRAGMENT_ABSTRACT = "artifact-inspect 脚本（各壳 stage 流给确切名）"


class RecipeVisibilityTest(unittest.TestCase):
    def _violations(self, fragment, sdr_shell=_SDR_SHELL):
        return cc.recipe_visibility_violations(
            _GUARD_SNIPPET,
            {"mgh-sdr": sdr_shell, "mgh-init": _INIT_SHELL},
            fragment)

    def test_region_parsing_is_exact(self):
        scripts = cc.guard_recipe_scripts(_GUARD_SNIPPET)
        self.assertEqual(scripts["mgh-sdr"],
                         {"diff_group.py", "render_sdr_report.py", "describe_artifact.py"})
        self.assertEqual(scripts["mgh-init"], {"list_clusters.py", "describe_artifact.py"})
        # nothing past `def _read_recipe` leaks in
        self.assertNotIn("chunk_sources.py", scripts["mgh-sdr"])

    def test_pass_when_surface_carries_every_recipe_script(self):
        self.assertEqual(self._violations(_FRAGMENT_OK), [])

    def test_reverse_missing_describe_artifact_literal_fails(self):
        # abstract wording in the fragment (pre-6.2 shape) => lint MUST flag it
        v = self._violations(_FRAGMENT_ABSTRACT)
        self.assertIn(("mgh-sdr", "describe_artifact.py"), v)
        self.assertIn(("mgh-init", "describe_artifact.py"), v)

    def test_restore_passes_again(self):
        self.assertEqual(self._violations(_FRAGMENT_OK), [])

    def test_missing_worklist_script_flagged_per_domain_only(self):
        v = self._violations(_FRAGMENT_OK, sdr_shell="render_sdr_report.py only")
        self.assertEqual(v, [("mgh-sdr", "diff_group.py")])

    # --- live repo integration: the shipped state is green -------------------

    def test_real_repo_has_zero_violations(self):
        self.assertEqual(cc.check_recipe_visibility(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
