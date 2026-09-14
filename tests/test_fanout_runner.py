#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for fanout_runner.py (tier-aware slot-backfill dispatcher:
scout/t1/t2/t3/sdr).

Covers: template fill (per-tier placeholder sets / residual assertion /
anchor-tree path-drift interception, incl. t3 rule_path both formats), state
machine (.done/.failed/crash-stays-pending/--resume idempotence/soft-deadline
early exit), CLI contract (exit codes, stdout-stderr split, --help flag
presence, required tier-flag validation, list exit-2 gate pass-through,
four-level timeout invariant spawn-time rejection), slot-backfill dispatch
(a hung unit occupies only its own slot; marker lazy-skip; stall re-dispatch
self-heal), per-unit stall/tree-kill + run.log evidence, zero-progress
breaker dispatch-window re-anchor (stalled exit 2), sidecar per-tier naming,
marker body tier values, spawn command per tier. Spawns are faked at the
module boundary (_run_unit) except TestRunUnitTreeKill, which runs real
`sys.executable -c` children.
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
SCRIPT = SCRIPTS / "fanout_runner.py"
FANOUT_DIR = HERE.parent / "core" / "prompts" / "fragments" / "fanout"
TEMPLATES = {
    "scout": FANOUT_DIR / "scout-task.md",
    "t1": FANOUT_DIR / "t1-task.md",
    "t2": FANOUT_DIR / "t2-task.md",
    "t3": FANOUT_DIR / "t3-task.md",
    "sdr": FANOUT_DIR / "sdr-task.md",
}


def _load(name="fanout_runner_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _unit(tmp: Path, bid="scout-001", tier="scout") -> dict:
    """In-tree pending[] unit under a synthetic <repo>/.mgh-init layout."""
    repo = tmp / "repo"
    init = repo / ".mgh-init"
    if tier == "t3":
        return {
            "category": bid,
            "format": "opencode",
            "input_path": str(init / "inputs" / "t3" / f"{bid}.input.json"),
            "rule_path": str(repo / "docs" / "security-controls" / f"{bid}.md"),
            "done_marker": str(init / "checkpoints" / "t3" / f"{bid}.opencode.json.done"),
            "failed_marker": str(init / "checkpoints" / "t3" / f"{bid}.opencode.json.failed"),
            "bytes": 10,
        }
    if tier == "t2":
        # plan_aggregate t2 shard shape (shard_id + categories list + checkpoint
        # under checkpoints/t2/shards/; mirror of the enumerator's pending item).
        return {
            "shard_id": bid,
            "categories": ["authorization"],
            "input_path": str(init / "inputs" / "t2" / f"{bid}.input.json"),
            "checkpoint_path": str(init / "checkpoints" / "t2" / "shards" / f"{bid}.json"),
            "done_marker": str(init / "checkpoints" / "t2" / "shards" / f"{bid}.json.done"),
            "failed_marker": str(init / "checkpoints" / "t2" / "shards" / f".{bid}.json.failed"),
            "bytes": 10,
        }
    cp = init / "checkpoints" / tier / f"{bid}.json"
    id_field = "batch_id" if tier == "scout" else "cluster_id"
    return {
        id_field: bid,
        "input_path": str(init / "inputs" / tier / f"{bid}.input.json"),
        "checkpoint_path": str(cp),
        "done_marker": str(Path(str(cp) + ".done")),
        "failed_marker": str(Path(str(cp) + ".failed")),
        "slice_dir": str(init / "slices" / tier / bid),
        "targets_count": 1,
        "bytes": 10,
    }


def _listing(tmp: Path, units, done=0, failed=0):
    return {"repo": str(tmp / "repo"), "total": len(units) + done + failed,
            "done": done, "failed": failed, "pending": units}


def _setup_repo(tmp: Path, units, tier="scout"):
    repo = tmp / "repo"
    (repo / ".mgh-init" / "checkpoints" / tier).mkdir(parents=True, exist_ok=True)
    (repo / ".mgh-init" / "inputs" / tier).mkdir(parents=True, exist_ok=True)
    plan_names = {"scout": "scout_plan.json", "t1": "clusters.json",
                  "t2": "run_config.json", "t3": "controls_inventory.json"}
    (repo / ".mgh-init" / plan_names[tier]).write_text("{}", encoding="utf-8")
    for u in units:
        Path(u["input_path"]).write_text("{}", encoding="utf-8")
    return repo


def _run_cli(tmp: Path, listing_path: Path, *extra):
    repo = tmp / "repo"
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--scout-plan", str(repo / ".mgh-init" / "scout_plan.json"),
         "--checkpoints", str(repo / ".mgh-init" / "checkpoints" / "scout"),
         "--inputs-dir", str(repo / ".mgh-init" / "inputs" / "scout"),
         "--pending-file", str(listing_path), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _run_cli_tier(tier: str, tmp: Path, listing_path: Path, *extra):
    """Tier-shaped CLI invocation (t1/t3 carry --tier + their plan flags)."""
    repo = tmp / "repo"
    init = repo / ".mgh-init"
    base = [sys.executable, str(SCRIPT), "--tier", tier,
            "--checkpoints", str(init / "checkpoints" / tier),
            "--inputs-dir", str(init / "inputs" / tier),
            "--pending-file", str(listing_path)]
    if tier == "t1":
        base += ["--clusters", str(init / "clusters.json"),
                 "--candidates", str(init / "controls_candidates.json")]
    elif tier == "t2":
        base += ["--init-dir", str(init)]
    elif tier == "t3":
        base += ["--inventory", str(init / "controls_inventory.json"),
                 "--format", "opencode",
                 "--rules-dir", str(repo / "docs" / "security-controls"),
                 "--target", str(repo)]
    return subprocess.run(base + list(extra), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


class TestTemplateFill(unittest.TestCase):
    def setUp(self):
        self.fr = _load()
        self.tmp = Path(__file__).parent / "_tmp_fanout_fill"
        _setup_repo(self.tmp, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_placeholder_set_filled_scout(self):
        unit = _unit(self.tmp)
        msg = self.fr._fill_template(self.fr.TIERS["scout"],
                                     TEMPLATES["scout"].read_text(encoding="utf-8"),
                                     unit, str(self.tmp / "repo"), "on")
        self.assertNotIn("{{", msg)
        for v in unit.values():
            if isinstance(v, str):
                self.assertIn(v, msg)
        self.assertIn("codegraph=on", msg)

    def test_repo_and_chunk_sources_abs(self):
        unit = _unit(self.tmp)
        msg = self.fr._fill_template(self.fr.TIERS["scout"],
                                     TEMPLATES["scout"].read_text(encoding="utf-8"),
                                     unit, "C:/some/repo", "off")
        self.assertIn("C:/some/repo", msg)
        self.assertIn("chunk_sources.py", msg)
        self.assertIn("codegraph=off", msg)

    def test_t1_template_fill(self):
        unit = _unit(self.tmp, "clst-aa::shard-0", tier="t1")
        msg = self.fr._fill_template(self.fr.TIERS["t1"],
                                     TEMPLATES["t1"].read_text(encoding="utf-8"),
                                     unit, str(self.tmp / "repo"), "on")
        self.assertNotIn("{{", msg)
        self.assertIn("clst-aa::shard-0", msg)
        self.assertIn(unit["checkpoint_path"], msg)
        self.assertIn(unit["slice_dir"], msg)
        self.assertIn("chunk_sources.py", msg)

    def test_t3_template_fill(self):
        unit = _unit(self.tmp, "authn", tier="t3")
        msg = self.fr._fill_template(self.fr.TIERS["t3"],
                                     TEMPLATES["t3"].read_text(encoding="utf-8"),
                                     unit, str(self.tmp / "repo"), "off")
        self.assertNotIn("{{", msg)
        self.assertIn("authn", msg)
        self.assertIn("format", msg)
        self.assertIn("opencode", msg)
        self.assertIn(unit["rule_path"], msg)
        # t3 carries no checkpoint/slice/chunk_sources input fields (the HTML
        # header comment documents the absence — strip it before asserting)
        body = msg.split("-->", 1)[1]
        self.assertNotIn("checkpoint_path:", body)
        self.assertNotIn("slice_dir:", body)
        self.assertNotIn("chunk_sources.py", body)

    def test_t2_template_fill(self):
        unit = _unit(self.tmp, "t2-authz", tier="t2")
        msg = self.fr._fill_template(self.fr.TIERS["t2"],
                                     TEMPLATES["t2"].read_text(encoding="utf-8"),
                                     unit, str(self.tmp / "repo"), "off")
        self.assertNotIn("{{", msg)
        self.assertIn("t2-authz", msg)
        self.assertIn("authorization", msg)          # categories list stringified
        self.assertIn(str(self.tmp / "repo"), msg)   # repo anchor
        self.assertIn(unit["input_path"], msg)
        self.assertIn(unit["checkpoint_path"], msg)
        self.assertIn(unit["done_marker"], msg)
        self.assertIn(unit["failed_marker"], msg)
        self.assertIn("init-synthesis-partial.md", msg)  # load instruction
        # partial-synthesis reads bounded shard records → no chunk_sources/codegraph/rule_path
        body = msg.split("-->", 1)[1]
        self.assertNotIn("chunk_sources.py", body)
        self.assertNotIn("codegraph", body)
        self.assertNotIn("rule_path:", body)

    def test_template_placeholder_set_matches_tiers_mapping(self):
        """On-disk template placeholders ⊆ TIERS[tier] placeholders (template/
        mapping drift = unfilled {{...}} at dispatch time → asserted here)."""
        import re
        for tier, cfg in self.fr.TIERS.items():
            text = TEMPLATES[tier].read_text(encoding="utf-8")
            used = set(re.findall(r"\{\{(\w+)\}\}", text))
            unknown = used - set(cfg["placeholders"])
            self.assertFalse(unknown, f"{tier} template uses unmapped placeholders: {unknown}")


class TestAnchorCheck(unittest.TestCase):
    def setUp(self):
        self.fr = _load()
        self.tmp = Path(__file__).parent / "_tmp_fanout_anchor"
        _setup_repo(self.tmp, [])

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_in_tree_unit_passes(self):
        unit = _unit(self.tmp)
        self.assertIsNone(self.fr._anchor_check(self.fr.TIERS["scout"], unit,
                                                self.tmp / "repo"))

    def test_drive_root_drift_intercepted(self):
        bad = dict(_unit(self.tmp), checkpoint_path="D:/.mgh-init/checkpoints/scout/scout-001.json")
        reason = self.fr._anchor_check(self.fr.TIERS["scout"], bad, self.tmp / "repo")
        self.assertIsNotNone(reason)
        self.assertIn("path-drift", reason)
        self.assertIn("checkpoint_path", reason)

    def test_dotdot_chain_escape_intercepted(self):
        # a `..` chain collapsing outside the repo anchor must be intercepted
        # (in-tree hallucinations like acme_wing→acme\wing are prevented by
        # verbatim substitution instead — the anchor check guards tree escape)
        bad = dict(_unit(self.tmp), input_path=str(self.tmp / "repo" / ".." / "escape.json"))
        reason = self.fr._anchor_check(self.fr.TIERS["scout"], bad, self.tmp / "repo")
        self.assertIsNotNone(reason)

    def test_missing_field_intercepted(self):
        bad = dict(_unit(self.tmp))
        bad.pop("input_path")
        self.assertIsNotNone(self.fr._anchor_check(self.fr.TIERS["scout"], bad,
                                                   self.tmp / "repo"))

    def test_t3_rule_path_drift_intercepted(self):
        # t3 anchor set = input_path/rule_path/done_marker/failed_marker
        bad = dict(_unit(self.tmp, "authn", tier="t3"),
                   rule_path="D:/docs/security-controls/authn.md")
        reason = self.fr._anchor_check(self.fr.TIERS["t3"], bad, self.tmp / "repo")
        self.assertIsNotNone(reason)
        self.assertIn("rule_path", reason)

    def test_t3_rule_path_claude_format_in_tree_passes(self):
        # claude-format rule_path (.claude/rules/security-<cat>.md) is also in-tree
        repo = self.tmp / "repo"
        unit = _unit(self.tmp, "authn", tier="t3")
        unit["format"] = "claude"
        unit["rule_path"] = str(repo / ".claude" / "rules" / "security-authn.md")
        self.assertIsNone(self.fr._anchor_check(self.fr.TIERS["t3"], unit, repo))


class TestAckParsing(unittest.TestCase):
    def setUp(self):
        self.fr = _load()

    def test_ok_ack(self):
        self.assertEqual(self.fr._parse_ack("junk\nok C:/a/b.json 3\n"), "ok")

    def test_ok_no_args(self):
        self.assertEqual(self.fr._parse_ack("ok"), "ok")

    def test_oversize_ack(self):
        self.assertEqual(self.fr._parse_ack("oversize C:/big.json"), "oversize")

    def test_failed_ack_carries_reason(self):
        ack = self.fr._parse_ack("failed suspected path drift: checkpoint_path")
        self.assertTrue(ack.startswith("failed:"))
        self.assertIn("path drift", ack)

    def test_unparsable_returns_none(self):
        self.assertIsNone(self.fr._parse_ack("The batch contained 3 controls."))
        self.assertIsNone(self.fr._parse_ack(""))


class TestStateMachineCli(unittest.TestCase):
    """CLI-level state machine via --pending-file (no real spawn)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_cli_"))
        self.units = [_unit(self.tmp, f"scout-{i:03d}") for i in range(1, 4)]
        _setup_repo(self.tmp, self.units)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_listing(self, listing):
        p = self.tmp / "pending.json"
        p.write_text(json.dumps(listing), encoding="utf-8")
        return p

    def test_exit_zero_stdout_json_stderr_split(self):
        lp = self._write_listing(_listing(self.tmp, []))
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["runner"], "fanout_runner")
        self.assertEqual(out["host"], "test")
        self.assertEqual(out["tier"], "scout")
        self.assertFalse(out["partial"])
        self.assertTrue(r.stderr)  # progress went to stderr

    def test_path_drift_unit_failed_marker_written(self):
        bad = dict(self.units[0], checkpoint_path="D:/.mgh-init/x.json")
        lp = self._write_listing(_listing(self.tmp, [bad]))
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0)
        fm = Path(bad["failed_marker"])
        self.assertTrue(fm.exists(), "path-drift unit must get a .failed marker")
        body = json.loads(fm.read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], bad["batch_id"])
        self.assertEqual(body["tier"], "scout")
        self.assertIn("path-drift", body["reason"])
        out = json.loads(r.stdout)
        self.assertEqual(out["failed"], 1)

    def test_purge_audit_dry_run_lists_and_guard_blocks_bare(self):
        audit = self.tmp / "repo" / ".mgh-init" / "inputs" / "scout" / "scout-001.task.md"
        audit.write_text("msg", encoding="utf-8")
        repo = self.tmp / "repo"
        base = [sys.executable, str(SCRIPT),
                "--scout-plan", str(repo / ".mgh-init" / "scout_plan.json"),
                "--checkpoints", str(repo / ".mgh-init" / "checkpoints" / "scout"),
                "--inputs-dir", str(repo / ".mgh-init" / "inputs" / "scout")]
        r = subprocess.run(base + ["--purge-audit", "--dry-run"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0)
        self.assertIn("scout-001.task.md", json.loads(r.stdout)["files"])
        self.assertTrue(audit.exists(), "dry-run must not delete")
        r2 = subprocess.run(base + ["--purge-audit"], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r2.returncode, 2, "bare --purge-audit must fail loud (guard)")
        self.assertTrue(audit.exists(), "guard must not delete either")

    def test_bad_wave_and_budget_exit_2(self):
        lp = self._write_listing(_listing(self.tmp, []))
        for bad in (["--wave", "0"], ["--time-budget-ms", "-1"], ["--call-timeout-s", "0"]):
            r = _run_cli(self.tmp, lp, *bad)
            self.assertEqual(r.returncode, 2, bad)

    def test_missing_scout_plan_exit_1(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--scout-plan", str(self.tmp / "nope.json"),
             "--checkpoints", "x", "--inputs-dir", "y"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 1)

    def test_help_contract_flags_present(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0)
        for flag in ("--tier", "--scout-plan", "--clusters", "--candidates",
                     "--init-dir", "--budget", "--inventory", "--format",
                     "--rules-dir", "--target",
                     "--checkpoints", "--inputs-dir", "--host", "--wave",
                     "--time-budget-ms", "--call-timeout-s", "--stall-timeout-s",
                     "--hb-interval-s", "--stall-waves",
                     "--resume", "--pending-file",
                     "--purge-audit", "--dry-run", "--template"):
            self.assertIn(flag, r.stdout, flag)

    def test_call_timeout_default_7200_and_invariant_documented(self):
        # Defaults calibrated for out-of-host manual runs (slow intranet LLM
        # endpoints; better-slow-than-killed); --help must carry the 4-level
        # invariant chain (stall < call < budget x 0.8 < host per-call).
        fr = _load()
        self.assertEqual(fr.DEFAULT_CALL_TIMEOUT_S, 7200)
        self.assertEqual(fr.DEFAULT_STALL_TIMEOUT_S, 900)
        self.assertEqual(fr.DEFAULT_HB_INTERVAL_S, 60)
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0)
        self.assertIn("7200", r.stdout)
        self.assertIn("900", r.stdout)
        self.assertIn("call-timeout-s", r.stdout)
        self.assertIn("stall-timeout-s", r.stdout)
        self.assertIn("time-budget-ms", r.stdout)
        self.assertIn("host per-call timeout", r.stdout)
        # the four-level invariant chain must be stated (inner < outer ordering);
        # argparse wraps help text, so collapse whitespace before matching
        flat = " ".join(r.stdout.split())
        self.assertRegex(
            flat,
            r"stall-timeout-s.*<.*call-timeout-s.*<.*time-budget-ms.*<.*host per-call timeout")

    def test_time_budget_help_carries_recommendation(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        # recommended = host per-call timeout x 0.8, with both host examples
        self.assertIn("0.8", r.stdout)
        self.assertIn("720000", r.stdout)
        self.assertIn("480000", r.stdout)

    def test_resume_skips_done_units(self):
        # mark unit 1 done on disk; listing still carries all 3 (stale) — but the
        # list CLI is bypassed by --pending-file, so instead verify idempotence:
        # re-running with an identical listing yields identical summary shape.
        lp = self._write_listing(_listing(self.tmp, []))
        r1 = _run_cli(self.tmp, lp, "--resume")
        r2 = _run_cli(self.tmp, lp, "--resume")
        self.assertEqual(r1.returncode, 0)
        self.assertEqual(r2.returncode, 0)
        self.assertEqual(json.loads(r1.stdout), json.loads(r2.stdout))

    def test_done_marker_short_circuits_listing_done_count(self):
        # a .done marker on disk + fresh listing input still processes remaining
        done_m = Path(self.units[0]["done_marker"])
        done_m.parent.mkdir(parents=True, exist_ok=True)
        done_m.write_text("", encoding="utf-8")
        lp = self._write_listing(_listing(self.tmp, self.units[1:], done=1))
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["done"], 1)
        self.assertEqual(out["total"], 3)


class TestTierCli(unittest.TestCase):
    """Tier-parameterized CLI: required-flag validation, exit-2 gate
    pass-through shape, marker body tier values, sidecar per-tier naming."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_tier_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _listing_file(self, tier, units, done=0, failed=0):
        _setup_repo(self.tmp, units, tier=tier)
        p = self.tmp / f"pending_{tier}.json"
        p.write_text(json.dumps(_listing(self.tmp, units, done, failed)),
                     encoding="utf-8")
        return p

    def test_missing_required_tier_flags_exit_2(self):
        # t1 without --clusters/--candidates; t3 without --inventory/--format/...
        repo = self.tmp / "repo"
        init = repo / ".mgh-init"
        init.mkdir(parents=True, exist_ok=True)
        for tier in ("t1", "t2", "t3"):
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--tier", tier,
                 "--checkpoints", str(init / "checkpoints" / tier),
                 "--inputs-dir", str(init / "inputs" / tier)],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(r.returncode, 2, f"{tier} missing flags must exit 2")
            self.assertIn("--tier", r.stderr)
            self.assertIn("requires", r.stderr)

    def test_t2_exit_zero_and_stdout_tier_field(self):
        units = [_unit(self.tmp, f"t2-{c}", tier="t2")
                 for c in ("authorization", "crypto")]
        lp = self._listing_file("t2", units)
        r = _run_cli_tier("t2", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tier"], "t2")
        self.assertEqual(out["total"], 2)
        self.assertFalse(out["partial"])
        self.assertFalse(out["stalled"])
        # audit copies filled (test hook = fill without spawn)
        for u in units:
            audit = self.tmp / "repo" / ".mgh-init" / "inputs" / "t2" / \
                f"{u['shard_id']}.task.md"
            self.assertTrue(audit.is_file(), audit)
            self.assertNotIn("{{", audit.read_text(encoding="utf-8"))

    def test_t2_empty_pending_idempotent_no_op(self):
        # needs_reduce=false equivalent: a listing with empty pending (marker-aware
        # enumerator after every shard is terminal) must cleanly no-op — 0 units,
        # partial:false, NEVER a false stalled trip.
        lp = self._listing_file("t2", [], done=0, failed=0)
        r = _run_cli_tier("t2", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["total"], 0)
        self.assertEqual(out["pending"], 0)
        self.assertFalse(out["partial"])
        self.assertFalse(out["stalled"])
        self.assertNotIn("stalled_pending", out)

    def test_t2_path_drift_marker_tier_value(self):
        bad = dict(_unit(self.tmp, "t2-crypto", tier="t2"),
                   checkpoint_path="D:/.mgh-init/checkpoints/t2/shards/t2-crypto.json")
        lp = self._listing_file("t2", [bad])
        r = _run_cli_tier("t2", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(Path(bad["failed_marker"]).read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "t2-crypto")
        self.assertEqual(body["tier"], "t2")
        self.assertIn("path-drift", body["reason"])
        out = json.loads(r.stdout)
        self.assertEqual(out["failed"], 1)

    def test_t2_list_args_forward_to_plan_aggregate(self):
        fr = _load()
        cfg = fr.TIERS["t2"]
        args = type("A", (), {"init_dir": "C:/t/.mgh-init", "budget": 262144,
                              "inputs_dir": "C:/t/.mgh-init/inputs/t2"})()
        argv = cfg["list_args"](args)
        self.assertEqual(argv[:4], ["--node", "t2", "--init-dir", "C:/t/.mgh-init"])
        self.assertEqual(argv[4:], ["--budget", "262144", "--materialize",
                                    "C:/t/.mgh-init/inputs/t2"])
        # budget not set → NOT forwarded (plan_aggregate DEFAULT_BUDGET applies)
        args2 = type("A", (), {"init_dir": "C:/t/.mgh-init", "budget": None,
                               "inputs_dir": "C:/t/.mgh-init/inputs/t2"})()
        argv2 = cfg["list_args"](args2)
        self.assertEqual(argv2, ["--node", "t2", "--init-dir", "C:/t/.mgh-init",
                                 "--materialize", "C:/t/.mgh-init/inputs/t2"])

    def test_t2_run_config_missing_exit_1(self):
        # t2 plan_path = <init-dir>/run_config.json (sidecar/liveness home anchor);
        # missing → exit 1 (plan artifact not found), not a crash.
        init = self.tmp / "repo" / ".mgh-init"
        (init / "checkpoints" / "t2").mkdir(parents=True, exist_ok=True)
        (init / "inputs" / "t2").mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--tier", "t2", "--init-dir", str(init),
             "--checkpoints", str(init / "checkpoints" / "t2"),
             "--inputs-dir", str(init / "inputs" / "t2"),
             "--pending-file", "x"],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_t1_exit_zero_and_stdout_tier_field(self):
        units = [_unit(self.tmp, f"clst-{i}", tier="t1") for i in range(2)]
        lp = self._listing_file("t1", units)
        r = _run_cli_tier("t1", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tier"], "t1")
        self.assertEqual(out["total"], 2)
        self.assertFalse(out["partial"])

    def test_t3_exit_zero_and_stdout_tier_field(self):
        units = [_unit(self.tmp, "authn", tier="t3"), _unit(self.tmp, "crypto", tier="t3")]
        lp = self._listing_file("t3", units)
        r = _run_cli_tier("t3", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tier"], "t3")
        self.assertEqual(out["total"], 2)

    def test_t1_path_drift_marker_tier_value(self):
        bad = dict(_unit(self.tmp, "clst-x", tier="t1"),
                   checkpoint_path="D:/.mgh-init/x.json")
        lp = self._listing_file("t1", [bad])
        r = _run_cli_tier("t1", self.tmp, lp)
        self.assertEqual(r.returncode, 0)
        body = json.loads(Path(bad["failed_marker"]).read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "clst-x")
        self.assertEqual(body["tier"], "t1")
        self.assertIn("path-drift", body["reason"])

    def test_t3_path_drift_marker_tier_value(self):
        bad = dict(_unit(self.tmp, "authn", tier="t3"),
                   rule_path="D:/docs/authn.md")
        lp = self._listing_file("t3", [bad])
        r = _run_cli_tier("t3", self.tmp, lp)
        self.assertEqual(r.returncode, 0)
        body = json.loads(Path(bad["failed_marker"]).read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "authn")
        self.assertEqual(body["tier"], "t3")

    def test_sidecar_per_tier_naming(self):
        for tier, uid in (("scout", "scout-001"), ("t1", "clst-a"),
                          ("t2", "t2-authz"), ("t3", "authn")):
            units = [_unit(self.tmp, uid, tier=tier)]
            lp = self._listing_file(tier, units, done=1)
            r = _run_cli_tier(tier, self.tmp, lp) if tier != "scout" \
                else _run_cli(self.tmp, lp)
            self.assertEqual(r.returncode, 0, r.stderr)
            # t2's sidecar/liveness home = plan_path.parent = <init-dir> (D5)
            sc = self.tmp / "repo" / ".mgh-init" / f"fanout_progress.{tier}.json"
            self.assertTrue(sc.exists(), f"sidecar {sc.name} must exist for tier {tier}")
            body = json.loads(sc.read_text(encoding="utf-8"))
            self.assertEqual(body["tier"], tier)
            out = json.loads(r.stdout)
            for k in ("host", "total", "done", "failed", "pending", "wave", "waves_run"):
                self.assertEqual(body[k], out[k], f"sidecar/{k} must equal stdout/{k}")

    def test_scout_soft_deadline_partial_sidecar(self):
        units = [_unit(self.tmp, "scout-001")]
        lp = self._listing_file("scout", units)
        r = _run_cli(self.tmp, lp, "--time-budget-ms", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["partial"])
        sc = json.loads((self.tmp / "repo" / ".mgh-init" /
                         "fanout_progress.scout.json").read_text(encoding="utf-8"))
        self.assertEqual(sc["state"], "exited-partial")
        self.assertEqual(sc["pending"], out["pending"])


class _FakeDispatchBase(unittest.TestCase):
    """Shared harness for breaker/backfill tests: a REAL list invocation via an
    absolute-path stub enumerator (pathlib join semantics keep absolute
    list_script) that derives pending from disk markers (markers = only truth),
    plus a module-boundary _run_unit fake whose per-unit call script decides
    status/ack — an ok ack writes the .done marker, simulating the subagent's
    terminal write. Default wave=1 keeps every interleaving deterministic."""

    N_UNITS = 2

    def setUp(self):
        import tempfile
        self.fr = _load("fanout_runner_fake")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_fake_"))
        self.repo = self.tmp / "repo"
        self.init = self.repo / ".mgh-init"
        (self.init / "checkpoints" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "inputs" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "scout_plan.json").write_text("{}", encoding="utf-8")
        self.units = [_unit(self.tmp, f"scout-{i:03d}")
                      for i in range(1, self.N_UNITS + 1)]
        for u in self.units:
            Path(u["input_path"]).write_text("{}", encoding="utf-8")
        self.calls = []  # (uid, status, ack) per fake _run_unit invocation

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_run(self, behavior):
        """behavior(uid, nth_call) -> (status, ack); ok acks write .done."""
        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            nth = fake.state.get(uid, 0) + 1
            fake.state[uid] = nth
            status, ack = behavior(uid, nth)
            self.calls.append((uid, status, ack))
            if ack == "ok":
                unit = next(u for u in self.units if u.get("batch_id") == uid)
                Path(unit["done_marker"]).write_text("done", encoding="utf-8")
            pid = 700000 + len(self.calls)
            if on_spawn is not None:
                on_spawn(pid)
            return (status, ack if status == "spawn-ok" else None, status,
                    pid, status == "stall")
        fake.state = {}
        return fake

    def _disk_stub(self):
        stub = self.tmp / "stub_disk_enum.py"
        body = f"""
import json, sys
from pathlib import Path
UNITS = json.loads({json.dumps(self.units)!r})
pending = [u for u in UNITS if not Path(u['done_marker']).is_file()]
print(json.dumps({{'repo': {str(self.repo)!r}, 'total': len(UNITS),
                   'done': len(UNITS) - len(pending), 'failed': 0,
                   'pending': pending}}))
"""
        stub.write_text(body, encoding="utf-8")
        return stub

    def _run_main(self, behavior, *extra, wave="1", stub=None):
        stub = stub or self._disk_stub()
        saved_list = dict(self.fr.TIERS["scout"])
        saved_run = self.fr._run_unit
        self.fr.TIERS["scout"]["list_script"] = str(stub)  # absolute → join keeps it
        self.fr._run_unit = self._fake_run(behavior)
        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout"),
                "--host", "claude", "--wave", wave, *extra]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.fr.main()
        finally:
            sys.argv = old
            self.fr._run_unit = saved_run
            self.fr.TIERS["scout"].update(saved_list)
        return code, out.getvalue(), err.getvalue()


class TestStallCircuitBreaker(_FakeDispatchBase):
    """Zero-progress convergence breaker, BOTH observation points (design D7):
    (a) every K = --stall-waves x --wave dispatched units → disk re-derivation;
    (b) queue-drained re-list. --stall-waves consecutive zero-growth
    observations with units still to dispatch → stop dispatching, exit 2,
    stdout stalled:true + stalled_pending[] (per-unit marker existence). A
    stalled unit re-enqueues itself (stays pending), so an always-stall unit
    keeps the queue fed and the trip comes via the (a) dispatch windows; the
    (b) drain-relist trip covers the consumed-without-marker tail (units the
    dispatcher took as terminal but whose disk marker never appeared) —
    exercised by TestSlotBackfillDispatch.test_lazy_skip_marker_terminal_never_spawns.
    A stall whose re-dispatch succeeds resets the window."""

    def test_always_stall_trips_via_dispatch_windows(self):
        # wave=1, --stall-waves 2 (K=2), 2 units, every attempt stalls (each
        # stall re-enqueues the unit): obs(a)#1 baselines (first observation),
        # obs(a)#2 and obs(a)#3 are the 2 consecutive zero-growth windows →
        # trip at (stall_waves + 1) x K = 6 dispatches. The deterministically
        # hung pair is truncated IN-RUN instead of looping forever.
        code, out, err = self._run_main(lambda uid, nth: ("stall", None))
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["stalled"])
        self.assertEqual(data["waves_run"], 6)
        self.assertEqual(data["pending"], 2)
        self.assertEqual(len(data["stalled_pending"]), 2)
        entry = data["stalled_pending"][0]
        self.assertEqual(entry["id"], "scout-001")
        self.assertFalse(entry["done_marker_exists"])     # diagnostic: disk truth
        self.assertFalse(entry["failed_marker_exists"])
        self.assertEqual(data["stall_killed"],
                         ["scout-001", "scout-002"] * 3)
        self.assertIn("STALLED", err)
        self.assertIn("resume_state", err)                # diagnosis recipe on stderr
        self.assertIn("stalled_pending", err)

    def test_stall_then_redispatch_success_resets_window(self):
        # scout-001 stalls once, completes on re-dispatch (marker written):
        # disk grows → window resets → clean exit 0 (self-heal, no trip);
        # the non-ok terminal discloses the unit's run.log path on stderr.
        seq = {"scout-001": [("stall", None), ("spawn-ok", "ok")],
               "scout-002": [("spawn-ok", "ok")]}

        def behavior(uid, nth):
            script = seq[uid]
            return script[nth - 1] if nth <= len(script) else ("spawn-ok", "ok")
        code, out, err = self._run_main(behavior)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["stalled"])
        self.assertNotIn("stalled_pending", data)
        self.assertEqual(data["waves_run"], 3)  # stall, ok, re-dispatch ok
        self.assertEqual(data["done"], 2)
        self.assertEqual(data["stall_killed"], ["scout-001"])
        self.assertIn("scout-001.run.log", err)

    def test_stall_waves_flag_widens_window(self):
        # --stall-waves 3 (K=3, wave=1): trip moves from 6 dispatches
        # (default) to (3 + 1) x 3 = 12 — wider window, bounded but later.
        code, out, err = self._run_main(lambda uid, nth: ("stall", None),
                                        "--stall-waves", "3")
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["waves_run"], 12)

    def test_stall_waves_validation_and_help(self):
        code, _, err = self._run_main(lambda uid, nth: ("stall", None),
                                      "--stall-waves", "0")
        self.assertEqual(code, 2)
        self.assertIn("--stall-waves must be >= 1", err)
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--stall-waves", r.stdout)
        flat = " ".join(r.stdout.split())
        self.assertIn("zero-growth", flat)
        self.assertIn("resume_state.py --check", flat)
        self.assertIn("stalled_pending", flat)
        self.assertEqual(self.fr.DEFAULT_STALL_WAVES, 2)


class TestSlotBackfillDispatch(_FakeDispatchBase):
    N_UNITS = 3

    def test_backfill_frees_slot_while_unit_in_flight(self):
        # wave=2: scout-001 hangs until scout-003 has STARTED; scout-002's
        # immediate completion frees the slot scout-003 backfills — a hung
        # unit blocks only its own slot, never the whole run.
        u3_started = threading.Event()
        state = {"u1_returned": False, "proof": None}

        def behavior(uid, nth):
            if uid == "scout-001" and nth == 1:
                self.assertTrue(u3_started.wait(timeout=30),
                                "scout-003 never backfilled while scout-001 hung")
                state["u1_returned"] = True
                return ("spawn-ok", "ok")
            if uid == "scout-003" and nth == 1:
                state["proof"] = not state["u1_returned"]
                u3_started.set()
                return ("spawn-ok", "ok")
            return ("spawn-ok", "ok")
        code, out, err = self._run_main(behavior, wave="2")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(state["proof"],
                        "scout-003 must dispatch while scout-001 still in flight")
        self.assertEqual(data["waves_run"], 3)
        self.assertEqual(data["done"], 3)

    def test_lazy_skip_marker_terminal_never_spawns(self):
        # a unit whose .done marker already exists is NEVER spawned: the queue
        # lazy-check skips it before every dispatch round. A static (lying)
        # lister keeps reporting all units pending → the units consumed as ok
        # get their markers, every later re-fill lazy-skips the whole queue,
        # and the breaker's (b) drain re-lists count the zero growth → drift
        # trip with done_marker_exists=true evidence instead of spawn loops.
        Path(self.units[0]["done_marker"]).write_text("done", encoding="utf-8")
        listing = {"repo": str(self.repo), "total": 3, "done": 0, "failed": 0,
                   "pending": self.units}
        stub = self.tmp / "stub_static_enum.py"
        stub.write_text(f"print({json.dumps(listing)!r})\n", encoding="utf-8")
        code, out, err = self._run_main(lambda uid, nth: ("spawn-ok", "ok"),
                                        stub=stub)
        self.assertEqual(code, 2, err)
        # first round only: u1 skipped pre-spawn (marker), u2/u3 dispatched
        # once each (ok → markers); every re-fill round lazy-skips them all
        self.assertEqual([c[0] for c in self.calls], ["scout-002", "scout-003"],
                         "marker-terminal units must never re-spawn")
        self.assertIn("marker already terminal on disk", err)
        data = json.loads(out)
        dp = {e["id"]: e for e in data["stalled_pending"]}
        self.assertEqual(len(dp), 3)
        self.assertTrue(all(e["done_marker_exists"] for e in dp.values()),
                        "drift diagnostic: disk markers all exist")


class TestContextOverflowClassification(_FakeDispatchBase):
    """P2 overflow-signature diagnosis at the dispatch-loop boundary: a crash
    whose detail carries the reason:context-overflow mark (set by _run_unit)
    surfaces context_overflow[] in the stdout summary + the narrow---budget
    recipe on stderr, WITHOUT changing crash semantics (unit still re-enqueues;
    the zero-progress breaker still bounds the loop). No mark → stdout stays
    byte-identical to the pre-classification release (no key, no recipe line)."""

    N_UNITS = 1

    def _fake_run_detail(self, detail):
        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            self.calls.append((uid, "crash", None))
            pid = 700000 + len(self.calls)
            if on_spawn is not None:
                on_spawn(pid)
            return ("crash", None, detail, pid, False)
        return fake

    def _run(self, detail):
        saved_list = dict(self.fr.TIERS["scout"])
        saved_run = self.fr._run_unit
        self.fr.TIERS["scout"]["list_script"] = str(self._disk_stub())
        self.fr._run_unit = self._fake_run_detail(detail)
        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout"),
                "--host", "claude", "--wave", "1"]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.fr.main()
        finally:
            sys.argv = old
            self.fr._run_unit = saved_run
            self.fr.TIERS["scout"].update(saved_list)
        return code, out.getvalue(), err.getvalue()

    def test_crash_with_signature_reports_context_overflow(self):
        code, out, err = self._run(
            "reason:context-overflow (narrow --budget and re-run); exit=1; "
            "stderr tail: prompt is too long")
        data = json.loads(out)
        self.assertEqual(data["context_overflow"], ["scout-001"])
        self.assertIn("reason:context-overflow", err)
        self.assertIn("narrow --budget", err)
        # outcome semantics unchanged: the crash loop is breaker-truncated
        self.assertEqual(code, 2)
        self.assertTrue(data["stalled"])

    def test_crash_without_signature_keeps_stdout_unchanged(self):
        code, out, err = self._run("crash")
        data = json.loads(out)
        self.assertNotIn("context_overflow", data)
        self.assertNotIn("reason:context-overflow", err)
        self.assertEqual(code, 2)  # same breaker truncation, no diagnosis


class TestRunUnitTreeKill(unittest.TestCase):
    """_run_unit against REAL `sys.executable -c` children: byte-silence stall
    kill, call-timeout kill, clean completion, crash, and the run.log evidence
    block (tail cap keeps the END). No fakes — the kill paths and the evidence
    file are the unit under test."""

    def setUp(self):
        import tempfile
        self.fr = _load("fanout_runner_kill")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_kill_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_stall_silence_kills_child_and_writes_run_log(self):
        cmd = [sys.executable, "-c",
               "import time; print('hello', flush=True); time.sleep(300)"]
        t0 = time.monotonic()
        status, ack, detail, pid, was_stalled = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 300, 2, self.tmp / "u1.run.log", "u1")
        elapsed = time.monotonic() - t0
        self.assertEqual(status, "stall")
        self.assertTrue(was_stalled)
        self.assertIsNone(ack)
        self.assertGreaterEqual(elapsed, 2)
        self.assertLess(elapsed, 30)  # 2s silence threshold + kill/reap slack
        self.assertFalse(self.fr._pid_alive(pid), "child must be dead (tree kill)")
        log = (self.tmp / "u1.run.log").read_text(encoding="utf-8")
        self.assertIn("status: stall", log)
        self.assertIn("hello", log)

    def test_call_timeout_kills_child(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(300)"]
        status, ack, _, pid, was_stalled = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 2, 0, self.tmp / "u2.run.log", "u2")
        self.assertEqual(status, "timeout")
        self.assertFalse(was_stalled)
        self.assertIsNone(ack)
        self.assertFalse(self.fr._pid_alive(pid))
        self.assertIn("status: timeout",
                      (self.tmp / "u2.run.log").read_text(encoding="utf-8"))

    def test_clean_completion_writes_ok_evidence(self):
        cmd = [sys.executable, "-c", "print('hello')"]
        status, _, detail, _, was_stalled = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u3.run.log", "u3")
        self.assertEqual(status, "spawn-ok")
        self.assertFalse(was_stalled)
        self.assertEqual(detail, "hello")
        log = (self.tmp / "u3.run.log").read_text(encoding="utf-8")
        self.assertIn("status: spawn-ok", log)
        self.assertIn("hello", log)

    def test_crash_nonzero_exit_no_ack(self):
        cmd = [sys.executable, "-c",
               "import sys; sys.stderr.write('boom'); sys.exit(3)"]
        status, ack, detail, _, was_stalled = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u4.run.log", "u4")
        self.assertEqual(status, "crash")
        self.assertIsNone(ack)
        self.assertFalse(was_stalled)
        self.assertIn("exit=3", detail)
        self.assertIn("boom", detail)
        self.assertIn("status: crash",
                      (self.tmp / "u4.run.log").read_text(encoding="utf-8"))

    def test_crash_with_overflow_signature_marks_reason(self):
        # P2 diagnosis (tier-agnostic): an overflow-shaped crash carries
        # reason:context-overflow + the narrow---budget recipe on the unit's
        # detail (→ run.log unit line) without changing the crash outcome.
        cmd = [sys.executable, "-c",
               "import sys; sys.stderr.write('request failed: prompt is too "
               "long: 512000 tokens > 200000 maximum'); sys.exit(1)"]
        status, ack, detail, _, was_stalled = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u6.run.log", "u6")
        self.assertEqual(status, "crash")
        self.assertIsNone(ack)
        self.assertFalse(was_stalled)
        self.assertTrue(detail.startswith("reason:context-overflow"), detail)
        self.assertIn("--budget", detail)
        log = (self.tmp / "u6.run.log").read_text(encoding="utf-8")
        self.assertIn("status: crash", log)
        self.assertIn("reason:context-overflow", log)

    def test_crash_without_signature_stays_generic(self):
        cmd = [sys.executable, "-c",
               "import sys; sys.stderr.write('boom: prompt is too spicy'); sys.exit(1)"]
        status, _, detail, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u7.run.log", "u7")
        self.assertEqual(status, "crash")
        self.assertNotIn("reason:context-overflow", detail)

    def test_tail_cap_bounds_evidence_keeps_end(self):
        filler = "x" * 20000  # well over the 8192 tail cap, under argv limits
        cmd = [sys.executable, "-c",
               f"print({filler!r}); print('END-MARK')"]
        status, _, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u5.run.log", "u5")
        self.assertEqual(status, "spawn-ok")
        log = (self.tmp / "u5.run.log").read_text(encoding="utf-8")
        block = log.split("----- stdout tail (last 8192 chars) -----")[1]
        block = block.split("----- stderr tail", 1)[0]
        self.assertLessEqual(len(block), 8192 + 2)  # cap + trailing newline
        self.assertIn("END-MARK", block)


class TestTimeoutInvariantCli(unittest.TestCase):
    """Four-level timeout invariant, spawn-time fail-loud (design D5):
    --time-budget-ms > 0 ⇒ explicit --call-timeout-s < budget x 0.8;
    --stall-timeout-s < --call-timeout-s always; stall floor 60. Exit 2 fires
    BEFORE any dispatch side effect (no audit copies, no sidecar)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_inv_"))
        self.units = [_unit(self.tmp, f"scout-{i:03d}") for i in range(1, 3)]
        _setup_repo(self.tmp, self.units)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _listing_file(self):
        p = self.tmp / "pending.json"
        p.write_text(json.dumps(_listing(self.tmp, self.units)), encoding="utf-8")
        return p

    def _assert_no_side_effects(self):
        audits = list((self.tmp / "repo" / ".mgh-init" / "inputs" / "scout"
                       ).glob("*.task.md"))
        self.assertEqual(audits, [])
        sc = self.tmp / "repo" / ".mgh-init" / "fanout_progress.scout.json"
        self.assertFalse(sc.exists())

    def test_budget_without_explicit_call_timeout_rejected(self):
        r = _run_cli(self.tmp, self._listing_file(), "--time-budget-ms", "720000")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("without an explicit --call-timeout-s", r.stderr)
        self.assertIn("--call-timeout-s 540", r.stderr)  # compliant recipe
        self._assert_no_side_effects()

    def test_call_timeout_ge_budget_headroom_rejected(self):
        r = _run_cli(self.tmp, self._listing_file(), "--time-budget-ms", "720000",
                     "--call-timeout-s", "7200")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("must be < time-budget-ms x 0.8", r.stderr)
        self._assert_no_side_effects()

    def test_stall_ge_call_rejected(self):
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "9999")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("must be < --call-timeout-s", r.stderr)

    def test_stall_below_floor_rejected(self):
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "30",
                     "--call-timeout-s", "3600")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--stall-timeout-s must be >= 60", r.stderr)

    def test_compliant_combination_passes(self):
        r = _run_cli(self.tmp, self._listing_file(), "--time-budget-ms", "720000",
                     "--call-timeout-s", "540", "--stall-timeout-s", "300")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertFalse(data["stalled"])

    def test_no_budget_hint_and_defaults_pass(self):
        r = _run_cli(self.tmp, self._listing_file())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("hint: no --time-budget-ms", r.stderr)


class TestListGatePassthrough(unittest.TestCase):
    """_list_pending exit-code semantics (design D4): the enumerator's exit 2
    (t1 scout-incomplete-gate / CLI misuse) passes through as exit 2 with the
    stderr recipe forwarded; exit 1 stays exit 1."""

    def setUp(self):
        self.fr = _load()
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_gate_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_list_pending(self, tier, script_name, exit_code, stderr_text):
        """Fake the tier enumerator with a stub script exiting `exit_code`."""
        stub = self.tmp / f"{script_name}"
        stub.write_text(
            f"import sys\n"
            f"sys.stderr.write({stderr_text!r})\n"
            f"sys.exit({exit_code})\n", encoding="utf-8")
        # Point the tier mapping's list_script at the stub dir
        cfg = dict(self.fr.TIERS[tier])
        cfg["list_script"] = str(stub)
        args = type("A", (), {"scout_plan": "sp.json", "clusters": "c.json",
                              "candidates": "cd.json", "inventory": "i.json",
                              "fmt": "opencode", "rules_dir": "r", "target": ".",
                              "checkpoints": "cp", "inputs_dir": "in"})()
        return cfg, args

    def test_t1_gate_exit_2_passed_through(self):
        cfg, args = self._run_list_pending("t1", "list_clusters.py", 2,
                                           "error: scout tier incomplete ...")
        with self.assertRaises(SystemExit) as cm:
            self.fr._list_pending(cfg, args)
        self.assertEqual(cm.exception.code, 2)

    def test_t1_generic_error_exit_1_stays(self):
        cfg, args = self._run_list_pending("t1", "list_clusters.py", 1,
                                           "error: malformed clusters.json")
        with self.assertRaises(SystemExit) as cm:
            self.fr._list_pending(cfg, args)
        self.assertEqual(cm.exception.code, 1)


class TestProgressSidecar(unittest.TestCase):
    """Human-facing fanout_progress.<tier>.json: exists after a run, terminal
    state, counts agree with the stdout summary (same-source derivation),
    atomic write leaves valid JSON."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_sidecar_"))
        self.units = [_unit(self.tmp, f"scout-{i:03d}") for i in range(1, 4)]
        _setup_repo(self.tmp, self.units)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sidecar_path(self) -> Path:
        return self.tmp / "repo" / ".mgh-init" / "fanout_progress.scout.json"

    def test_sidecar_terminal_state_and_counts_match_stdout(self):
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, [])), encoding="utf-8")
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        sc_path = self._sidecar_path()
        self.assertTrue(sc_path.exists(), "sidecar must exist after a run")
        sc = json.loads(sc_path.read_text(encoding="utf-8"))
        out = json.loads(r.stdout)
        self.assertEqual(sc["state"], "exited-clean")
        for k in ("host", "total", "done", "failed", "pending", "wave", "waves_run"):
            self.assertEqual(sc[k], out[k], f"sidecar/{k} must equal stdout/{k}")
        self.assertIn(sc["state"], ("running", "exited-partial", "exited-clean"))
        self.assertIn("ts", sc)
        self.assertIn("wave_done_avg_s", sc)
        self.assertIn("eta_batches", sc)
        self.assertEqual(sc["tier"], "scout")

    def test_sidecar_partial_state_after_soft_deadline(self):
        # pending units + a zero time budget → immediate clean early-exit with
        # partial:true; sidecar must record exited-partial with matching counts
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, self.units)), encoding="utf-8")
        r = _run_cli(self.tmp, lp, "--time-budget-ms", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["partial"])
        sc = json.loads(self._sidecar_path().read_text(encoding="utf-8"))
        self.assertEqual(sc["state"], "exited-partial")
        for k in ("total", "done", "failed", "pending"):
            self.assertEqual(sc[k], out[k], f"sidecar/{k} must equal stdout/{k}")

    def test_sidecar_counts_match_stdout_with_failures(self):
        # a path-drift unit produces a .failed marker → failed count must agree
        bad = dict(self.units[0], checkpoint_path="D:/.mgh-init/x.json")
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, [bad] + self.units[1:])),
                      encoding="utf-8")
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["failed"], 1)
        sc = json.loads(self._sidecar_path().read_text(encoding="utf-8"))
        self.assertEqual(sc["failed"], out["failed"])
        self.assertEqual(sc["total"], out["total"])

    def test_sidecar_valid_json_after_multi_wave_run(self):
        # one wave of two test-hook units (the --pending-file hook is single
        # pass: waves_run stays 1) → atomic writes never leave a half file;
        # the final sidecar parses and reflects the run
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, self.units[:2])), encoding="utf-8")
        r = _run_cli(self.tmp, lp, "--wave", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        sc = json.loads(self._sidecar_path().read_text(encoding="utf-8"))
        self.assertEqual(sc["waves_run"], out["waves_run"])
        self.assertEqual(sc["state"], "exited-clean")
        self.assertEqual(sc["wave"], 1)


class TestTimeoutWiringDocs(unittest.TestCase):
    """Fragment invocation-line timeout relation: the exemplified
    --time-budget-ms values must sit below the corresponding host per-call
    timeout examples (soft deadline fires BEFORE the host hard kill)."""

    FRAGMENTS = {
        "scout": HERE.parent / "core" / "prompts" / "fragments" / "init-stage" / "scout.md",
        "t1": HERE.parent / "core" / "prompts" / "fragments" / "init-stage" / "t1.md",
        "t2": HERE.parent / "core" / "prompts" / "fragments" / "init-stage" / "t2.md",
        "t3": HERE.parent / "core" / "prompts" / "fragments" / "init-stage" / "t3.md",
    }

    def test_fragment_budget_examples_below_host_timeouts(self):
        for tier, frag in self.FRAGMENTS.items():
            text = frag.read_text(encoding="utf-8")
            # opencode example: host 900000ms -> budget 720000; claude: 600000 -> 480000
            self.assertIn("720000", text, f"{tier}: opencode budget example")
            self.assertIn("480000", text, f"{tier}: claude budget example")
            self.assertIn("× 0.8", text, f"{tier}: 0.8 recommendation")
            self.assertIn("MUST < 宿主 per-call", text, f"{tier}: below-host invariant")
            # dispatcher-first: scout keeps the legacy call shape (--tier
            # defaults to scout, zero call-surface change); t1/t3 name --tier
            if tier == "scout":
                self.assertIn("--scout-plan", text, "scout: legacy call shape")
            else:
                self.assertIn(f"--tier {tier}", text, f"{tier}: dispatcher call line")
            self.assertIn("手派路径", text, f"{tier}: manual fallback preserved")
            self.assertIn("手动直跑", text, f"{tier}: out-of-host escape hatch")
            self.assertIn("--resume", text, f"{tier}: resume continuation")
            # per-tier sidecar name
            self.assertIn(f"fanout_progress.{tier}.json", text,
                          f"{tier}: per-tier sidecar name")
        self.assertLess(720000, 900000)
        self.assertLess(480000, 600000)

    def test_t1_fragment_distinguishes_exit2_forms(self):
        text = self.FRAGMENTS["t1"].read_text(encoding="utf-8")
        # exit 2 splits: host-CLI unavailable → manual fallback; scout gate →
        # finish scout first
        self.assertIn("宿主 CLI 不可用", text)
        self.assertIn("scout 闸门", text)
        self.assertIn("先完成 scout", text)
        # T1→T2 validate gate untouched
        self.assertIn("validate_t1_records", text)
        self.assertIn("--strip-bom", text)

    def test_t3_fragment_keeps_assemble_reference(self):
        text = self.FRAGMENTS["t3"].read_text(encoding="utf-8")
        self.assertIn("assemble", text)

    def test_discipline_recipe_carries_re_dispatch_timeout_rule(self):
        spec = importlib.util.spec_from_file_location(
            "discipline_core_test", SCRIPTS / "discipline_core.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for step, recipe_id in (("scout", "scout-fanout-dispatcher"),
                                ("t1", "t1-fanout-dispatcher"),
                                ("t2", "t2-fanout-dispatcher"),
                                ("t3", "t3-fanout-dispatcher")):
            d = mod.get_discipline(step)
            dispatcher = [p for p in d["path_recipes"] if p["id"] == recipe_id]
            self.assertTrue(dispatcher, f"{recipe_id} recipe must exist")
            desc = dispatcher[0]["desc"]
            self.assertIn("--time-budget-ms", desc, recipe_id)
            self.assertIn("per-call timeout > --time-budget-ms", desc, recipe_id)
            self.assertIn("软时限先于宿主硬杀", desc, recipe_id)
            if step == "scout":
                self.assertIn("fanout_runner.py", desc, "scout: legacy call shape")
            else:
                self.assertIn(f"--tier {step}", desc, recipe_id)
        # t1 recipe additionally carries the two exit-2 forms
        d1 = mod.get_discipline("t1")
        desc1 = [p for p in d1["path_recipes"]
                 if p["id"] == "t1-fanout-dispatcher"][0]["desc"]
        self.assertIn("scout 闸门", desc1)


class TestSpawnCommand(unittest.TestCase):
    def setUp(self):
        self.fr = _load()

    def test_opencode_shape_per_tier(self):
        for tier, agent in (("scout", "init-scout-fanout"),
                            ("t1", "init-induct-fanout"),
                            ("t2", "init-synthesis-fanout"),
                            ("t3", "init-rulewriter-fanout")):
            cmd = self.fr._spawn_cmd(self.fr.TIERS[tier], "opencode")
            # argv[0] = which()-resolved host exe (Windows .cmd shim) or bare name;
            # task travels via stdin, never argv
            self.assertEqual(cmd[1:4], ["run", "--agent", agent], tier)
            self.assertNotIn("TASK", cmd)

    def test_claude_shape_per_tier(self):
        for tier, agent in (("scout", "init-scout-fanout"),
                            ("t1", "init-induct-fanout"),
                            ("t2", "init-synthesis-fanout"),
                            ("t3", "init-rulewriter-fanout")):
            cmd = self.fr._spawn_cmd(self.fr.TIERS[tier], "claude")
            self.assertEqual(cmd[1], "-p", tier)
            self.assertIn("--agents", cmd, tier)
            agents = json.loads(cmd[cmd.index("--agents") + 1])
            self.assertIn(agent, agents, tier)
            self.assertIn("--allowedTools", cmd, tier)
            tools = cmd[cmd.index("--allowedTools") + 1]
            for t in ("Read", "Glob", "Grep", "Bash", "Write"):
                self.assertIn(t, tools, f"{tier}:{t}")
        # t3 rulewriter edits rule files → Edit in its whitelist
        cmd3 = self.fr._spawn_cmd(self.fr.TIERS["t3"], "claude")
        self.assertIn("Edit", cmd3[cmd3.index("--allowedTools") + 1])

    def test_host_exe_resolves_or_falls_back(self):
        exe = self.fr._host_exe("definitely-not-a-real-host-xyz")
        self.assertEqual(exe, "definitely-not-a-real-host-xyz")  # bare-name fallback


class TestAgentCloneParity(unittest.TestCase):
    """opencode fanout agent clones: body sections OTHER than the Input
    section (whose dispatch-context wording legitimately differs — same shape
    as the init-scout-fanout precedent) stay a verbatim clone of the
    non-fanout agent definition (drift = two-place maintenance bug)."""

    AGENT_DIR = HERE.parent / "releases" / "opencode" / "agent"

    def _body(self, name):
        text = (self.AGENT_DIR / f"{name}.md").read_text(encoding="utf-8")
        after = text.split("---", 2)[2]
        # normalize the dispatcher/orchestrator wording that legitimately
        # differs between dispatch contexts (fanout twin speaks of the
        # dispatcher; the interactive twin of the orchestrator)
        for a, b in (("from dispatcher", "from orchestrator"),
                     ("(from dispatcher)", "(from orchestrator)"),
                     ("dispatcher-given", "orchestrator-given"),
                     ("the dispatcher writes", "the orchestrator writes"),
                     ("dispatcher 据此写", "编排器据此 `Write` "),
                     ("dispatcher 据此", "编排器据此"),
                     ("dispatcher 据此", "编排器据此"),
                     ("dispatcher 无 marker", "编排器无 marker"),
                     ("是 dispatcher 逐字给定的", "是编排器逐字给定的")):
            after = after.replace(a, b)
        return "\n".join(ln for ln in after.splitlines() if ln.strip())

    def _sections(self, name):
        """Split body into {heading: text} keyed by ## heading. The Input
        heading legitimately varies by dispatch context (`## Input (from
        orchestrator)` vs `## Input (from dispatcher)` → normalized to `Input`;
        the base rulewriter uses bare `## Input`) — normalized so section
        identity is shared while the Input CONTENT is intentionally excluded
        from the parity assertion."""
        parts = {}
        heading = "_preamble"
        for ln in self._body(name).splitlines():
            if ln.startswith("## "):
                heading = ln[3:].strip()
                if heading.startswith("Input"):
                    heading = "Input"
                parts[heading] = []
            parts.setdefault(heading, []).append(ln)
        return {k: "\n".join(v).strip() for k, v in parts.items()}

    def test_all_three_fanout_clones_exist(self):
        for name in ("init-scout-fanout", "init-induct-fanout",
                     "init-rulewriter-fanout"):
            self.assertTrue((self.AGENT_DIR / f"{name}.md").is_file(), name)

    def test_clone_hard_constraints_and_output_match_base(self):
        pairs = [("init-scout-fanout", "init-scout"),
                 ("init-induct-fanout", "init-induct"),
                 ("init-rulewriter-fanout", "init-rulewriter")]
        for fanout, base in pairs:
            fs, bs = self._sections(fanout), self._sections(base)
            self.assertEqual(set(fs), set(bs), f"{fanout}: section headings drifted")
            for section in ("Hard constraints", "Output"):
                self.assertEqual(fs[section], bs[section],
                                 f"{fanout}: section '{section}' drifted from {base}")

    def test_clone_input_section_carries_dispatcher_fields(self):
        for fanout, fields in (
                ("init-scout-fanout", ("input_path", "checkpoint_path", "slice_dir")),
                ("init-induct-fanout", ("input_path", "checkpoint_path", "slice_dir")),
                ("init-rulewriter-fanout", ("input_path", "rule_path", "format"))):
            text = (self.AGENT_DIR / f"{fanout}.md").read_text(encoding="utf-8")
            self.assertIn("## Input (from dispatcher)", text, fanout)
            for f in fields:
                self.assertIn(f, text, f"{fanout}:{f}")


class TestSdrTier(unittest.TestCase):
    """sdr tier (add-mgh-sdr): TIERS row drives the shared wave machine unchanged —
    template fill + closed placeholder set, path-drift interception, --pending-file
    dispatch of the sdr listing shape (unit_id/kind/route + draft_path markers)."""

    def setUp(self):
        self.fr = _load("fanout_runner_sdr_test")
        self.tmp = Path(tempfile.gettempdir()) / f"mgh_fanout_sdr_{id(self)}"
        repo = self.tmp / "repo"
        run_dir = repo / ".mgh-sdr" / "runs" / "t1"
        (run_dir / "markers").mkdir(parents=True, exist_ok=True)
        (run_dir / "slices").mkdir(parents=True, exist_ok=True)
        (run_dir / "grouping.json").write_text("{}", encoding="utf-8")
        self.repo = repo
        self.run_dir = run_dir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sdr_unit(self, uid="UserController___user_detail", kind="interface",
                  route="/user/detail") -> dict:
        return {
            "unit_id": uid, "kind": kind, "route": route,
            "input_path": str(self.run_dir / "slices" / f"{uid}.slice.md"),
            "draft_path": str(self.run_dir / "drafts" / f"{uid}.json"),
            "done_marker": str(self.run_dir / "markers" / f"{uid}.done"),
            "failed_marker": str(self.run_dir / "markers" / f"{uid}.failed"),
            "baseline_path": str(self.run_dir / "baseline.md"),
            "external_dir": str(self.run_dir / "external"),
            "unit_bytes": 100,
        }

    def _listing(self, units, done=0, failed=0):
        return {"repo": str(self.repo), "base": "master", "branch": "feature-pay",
                "empty": False, "total": len(units) + done + failed,
                "done": done, "failed": failed,
                "counts": {"interface": len(units), "standalone": 0},
                "pending": units}

    def _write_listing(self, listing) -> Path:
        p = self.run_dir / "pending_test.json"
        p.write_text(json.dumps(listing), encoding="utf-8")
        return p

    def _run_cli(self, listing_path: Path, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--tier", "sdr",
             "--repo", str(self.repo), "--base", "master",
             "--checkpoints", str(self.run_dir / "markers"),
             "--inputs-dir", str(self.run_dir / "slices"),
             "--pending-file", str(listing_path), *extra],
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def test_template_fill_sdr(self):
        unit = self._sdr_unit()
        msg = self.fr._fill_template(self.fr.TIERS["sdr"],
                                     TEMPLATES["sdr"].read_text(encoding="utf-8"),
                                     unit, str(self.repo), "off")
        self.assertIn("UserController___user_detail", msg)
        self.assertIn("kind: interface", msg)
        self.assertIn("/user/detail", msg)
        self.assertIn(str(unit["input_path"]), msg)
        self.assertIn(str(unit["draft_path"]), msg)
        self.assertIn(str(unit["baseline_path"]), msg)
        self.assertIn("codegraph=off", msg)
        self.assertNotIn("{{", msg)

    def test_template_placeholder_set_closed(self):
        # every {{...}} placeholder in the template is in the TIERS["sdr"] set
        import re
        text = TEMPLATES["sdr"].read_text(encoding="utf-8")
        used = set(re.findall(r"\{\{(\w+)\}\}", text))
        declared = set(self.fr.TIERS["sdr"]["placeholders"])
        self.assertEqual(used, declared,
                         f"template placeholders {sorted(used)} != TIERS set "
                         f"{sorted(declared)}")

    def test_sdr_path_drift_intercepted(self):
        bad = self._sdr_unit()
        bad["draft_path"] = str(Path(self.tmp) / "outside" / "draft.json")
        reason = self.fr._anchor_check(self.fr.TIERS["sdr"], bad, self.repo)
        self.assertIsNotNone(reason)
        self.assertIn("draft_path", reason)
        # baseline_path/external_dir are NOT path_fields (read-side info, not write
        # anchors): drift there does not fail the anchor check
        odd = self._sdr_unit()
        odd["external_dir"] = "Z:/elsewhere"
        self.assertIsNone(self.fr._anchor_check(self.fr.TIERS["sdr"], odd, self.repo))

    def test_pending_file_dispatch_sdr_shape(self):
        units = [self._sdr_unit("uA", "interface", "/user/detail"),
                 self._sdr_unit("uB", "standalone", "")]
        for u in units:
            Path(u["input_path"]).write_text("slice", encoding="utf-8")
        r = self._run_cli(self._write_listing(self._listing(units)))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["tier"], "sdr")
        self.assertEqual(d["total"], 2)
        # audit copies filled (test hook = fill without spawn)
        for u in units:
            audit = self.run_dir / "slices" / f"{u['unit_id']}.task.md"
            self.assertTrue(audit.is_file(), audit)
            self.assertNotIn("{{", audit.read_text(encoding="utf-8"))

    def test_sdr_codegraph_signal_off_in_dispatcher(self):
        # the sdr tier derives codegraph=off in the dispatcher (the shell decides the
        # real signal); this is the documented divergence from init tiers
        self.assertEqual(self.fr._codegraph_signal(self.run_dir / "grouping.json", "sdr"),
                         "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
