#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Init-shell flag-table reconciliation (fix-mgh-init-distribution-links 1.3).

The three mgh-init shells' argument tables are a CLOSED SET that must reconcile
against real consumption points (control-discovery: "参数闭集对账消费点"):
  1. no dead flags — a table entry whose shell-level semantics no script/orchestrator
     consumes is a lie to the agent (`--out <path>` claimed per-face rules defaults
     that nothing consumes; `--config <profile>` no script declares at all);
  2. three faces advertise the SAME flag set (non-whitelist mirror drift — the
     claude face lacked `--rules-dir` while opencode/dsh had it);
  3. every non-exempt entry resolves in some init consumer script's `--help` union
     (exempt closed set: shell-level flags documented in the tool).

Red-first: 1+2 fail on the pre-fix shells. Run: py tests/test_init_flag_table_contract.py
"""
import importlib.util, subprocess, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LINT = ROOT / "tools" / "check_contracts.py"

spec = importlib.util.spec_from_file_location("_contracts_under_test", LINT)
CC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CC)


class TestInitFlagTableReconciliation(unittest.TestCase):
    def _tables(self):
        return {name: CC.init_flag_table_flags(path)
                for name, path in CC.INIT_FLAG_TABLE_FACES.items()}

    def test_no_dead_flags_in_any_face(self):
        for name, flags in self._tables().items():
            dead = sorted(flags & CC.INIT_FLAG_TABLE_FORBIDDEN)
            self.assertFalse(
                dead,
                f"{name}: flag table lists dead flag(s) {dead} — no consumer with "
                f"this semantics; remove the row (control-discovery 死旗移除)")

    def test_three_faces_advertise_the_same_set(self):
        tables = self._tables()
        claude, opencode, dsh = (tables["claude"], tables["opencode"], tables["dsh"])
        self.assertEqual(claude - opencode, set(),
                         f"claude-only rows: {sorted(claude - opencode)}")
        self.assertEqual(opencode - claude, set(),
                         f"opencode-only rows: {sorted(opencode - claude)}")
        self.assertEqual(claude - dsh, set(),
                         f"claude-only rows vs dsh: {sorted(claude - dsh)}")
        self.assertEqual(dsh - claude, set(),
                         f"dsh-only rows vs claude: {sorted(dsh - claude)}")

    def test_rules_dir_row_on_every_face(self):
        for name, flags in self._tables().items():
            self.assertIn("--rules-dir", flags,
                          f"{name}: flag table missing --rules-dir (T3 rules dir, "
                          f"consumed by list_rule_jobs/assemble_rules)")

    def test_every_entry_reconciles_to_a_consumer_or_exempt(self):
        union = CC.init_consumer_help_union()
        self.assertTrue(union, "consumer --help union is empty (wiring broken?)")
        for name, flags in self._tables().items():
            unreconciled = sorted(
                f for f in flags - CC.INIT_FLAG_TABLE_EXEMPT if f not in union)
            self.assertFalse(
                unreconciled,
                f"{name}: flag(s) {unreconciled} not declared by any init consumer "
                f"script --help nor exempt — dead table row")

    def test_tool_main_exits_zero(self):
        # CI gate: the wired check inside check_contracts.py passes.
        r = subprocess.run([sys.executable, str(LINT)], capture_output=True)
        self.assertEqual(r.returncode, 0,
                         f"check_contracts failed:\n{r.stderr.decode('utf-8', 'replace')}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
