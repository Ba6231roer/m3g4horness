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
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
SCRIPT = SCRIPTS / "fanout_runner.py"
FANOUT_DIR = HERE.parent / "core" / "prompts" / "fragments" / "fanout"
TEMPLATES = {
    "scout": FANOUT_DIR / "scout-task.md",
    "t1": FANOUT_DIR / "t1-task.md",
    "t2": FANOUT_DIR / "t2-task.md",
    "scout-merge": FANOUT_DIR / "scout-merge-task.md",
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
    if tier == "scout-merge":
        # plan_aggregate scout-merge shard shape (shard_id + batches list +
        # checkpoint under checkpoints/scout/shards/).
        return {
            "shard_id": bid,
            "batches": ["scout-000", "scout-001"],
            "input_path": str(init / "inputs" / "scout-merge" / f"{bid}.input.json"),
            "checkpoint_path": str(init / "checkpoints" / "scout" / "shards" / f"{bid}.json"),
            "done_marker": str(init / "checkpoints" / "scout" / "shards" / f"{bid}.json.done"),
            "failed_marker": str(init / "checkpoints" / "scout" / "shards" / f".{bid}.json.failed"),
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
    cp_dir = tier if tier != "scout-merge" else "scout"
    (repo / ".mgh-init" / "checkpoints" / cp_dir).mkdir(parents=True, exist_ok=True)
    (repo / ".mgh-init" / "inputs" / tier).mkdir(parents=True, exist_ok=True)
    plan_names = {"scout": "scout_plan.json", "t1": "clusters.json",
                  "t2": "run_config.json", "scout-merge": "run_config.json",
                  "t3": "controls_inventory.json"}
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
    cp_tier = tier if tier != "scout-merge" else "scout"
    base = [sys.executable, str(SCRIPT), "--tier", tier,
            "--checkpoints", str(init / "checkpoints" / cp_tier),
            "--inputs-dir", str(init / "inputs" / tier),
            "--pending-file", str(listing_path)]
    if tier == "t1":
        base += ["--clusters", str(init / "clusters.json"),
                 "--candidates", str(init / "controls_candidates.json")]
    elif tier in ("t2", "scout-merge"):
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

    def test_scout_merge_template_fill(self):
        unit = _unit(self.tmp, "scout-merge-0", tier="scout-merge")
        msg = self.fr._fill_template(self.fr.TIERS["scout-merge"],
                                     TEMPLATES["scout-merge"].read_text(encoding="utf-8"),
                                     unit, str(self.tmp / "repo"), "off")
        self.assertNotIn("{{", msg)
        self.assertIn("scout-merge-0", msg)
        self.assertIn("scout-000", msg)              # batches list stringified
        self.assertIn(str(self.tmp / "repo"), msg)   # repo anchor
        self.assertIn(unit["input_path"], msg)
        self.assertIn(unit["checkpoint_path"], msg)
        self.assertIn(unit["done_marker"], msg)
        self.assertIn(unit["failed_marker"], msg)
        self.assertIn("init-scout-merge-partial.md", msg)  # load instruction
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


class TestWriteFailedMarkerAnchor(unittest.TestCase):
    """The `.failed` marker write is repo-anchored: the response to a DETECTED
    poisoned path must never be to materialize it. Out-of-tree marker →
    refuse (no mkdir, no write, False return, stderr recipe — the caller must
    not count the unit failed-written, a count without disk evidence would be
    a fabrication); in-tree marker → written (or already present) exactly as
    before. The guard lives in the single write point both entries share
    (path-drift interception + explicit failed ack)."""

    def setUp(self):
        import tempfile
        self.fr = _load("fanout_runner_marker")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_marker_"))
        self.repo = self.tmp / "repo"
        (self.repo / ".mgh-init").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_out_of_tree_marker_refused_never_materialized(self):
        outside = self.tmp / "outside" / "poison" / "u.json.failed"
        unit = {"batch_id": "scout-001", "failed_marker": str(outside)}
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ok = self.fr._write_failed_marker(self.fr.TIERS["scout"], unit,
                                              "path-drift: x", self.repo)
        self.assertFalse(ok, "out-of-tree marker must be refused")
        self.assertFalse(outside.parent.exists(), "NEVER mkdir the poisoned path")
        self.assertFalse(outside.exists(), "NEVER write the poisoned path")
        self.assertIn("outside repo anchor", err.getvalue())
        self.assertIn("recipe", err.getvalue().lower())

    def test_in_tree_marker_written_and_reported(self):
        fm = self.repo / ".mgh-init" / "checkpoints" / "u2.json.failed"
        unit = {"batch_id": "scout-002", "failed_marker": str(fm)}
        ok = self.fr._write_failed_marker(self.fr.TIERS["scout"], unit,
                                          "failed: boom", self.repo)
        self.assertTrue(ok)
        body = json.loads(fm.read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "scout-002")
        self.assertEqual(body["tier"], "scout")
        # idempotent second write: still True, existing body untouched
        ok2 = self.fr._write_failed_marker(self.fr.TIERS["scout"], unit,
                                           "failed: again", self.repo)
        self.assertTrue(ok2)
        self.assertEqual(json.loads(fm.read_text(encoding="utf-8"))["reason"],
                         "failed: boom")


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

    def test_path_drift_out_of_tree_marker_never_materialized(self):
        # poisoned listing: the unit's failed_marker points OUTSIDE the repo
        # anchor — the path-drift interception must refuse to mkdir/write it
        # (pre-fix the response to a detected poisoned path was to execute it:
        # mkdir parents + write the marker at the very path flagged as drift)
        outside = self.tmp / "outside" / "poison" / "u.json.failed"
        bad = dict(self.units[0], checkpoint_path="D:/.mgh-init/x.json",
                   failed_marker=str(outside))
        lp = self._write_listing(_listing(self.tmp, [bad]))
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(outside.parent.exists(), "NEVER mkdir the poisoned dir")
        self.assertFalse(outside.exists(), "NEVER write the poisoned marker")
        self.assertIn("outside repo anchor", r.stderr)
        self.assertEqual(json.loads(r.stdout)["failed"], 0,
                         "refused marker must not inflate the failed count")

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
                     "--purge-audit", "--dry-run", "--template",
                     "--cooldown-s", "--no-rate-limit-stop", "--retry-failed"):
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
        for tier in ("t1", "t2", "scout-merge", "t3"):
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

    def test_scout_merge_exit_zero_and_stdout_tier_field(self):
        units = [_unit(self.tmp, f"scout-merge-{i}", tier="scout-merge")
                 for i in range(2)]
        lp = self._listing_file("scout-merge", units)
        r = _run_cli_tier("scout-merge", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tier"], "scout-merge")
        self.assertEqual(out["total"], 2)
        self.assertFalse(out["partial"])
        for u in units:
            audit = self.tmp / "repo" / ".mgh-init" / "inputs" / "scout-merge" / \
                f"{u['shard_id']}.task.md"
            self.assertTrue(audit.is_file(), audit)
            self.assertNotIn("{{", audit.read_text(encoding="utf-8"))

    def test_scout_merge_path_drift_marker_tier_value(self):
        bad = dict(_unit(self.tmp, "scout-merge-0", tier="scout-merge"),
                   checkpoint_path="D:/.mgh-init/x.json")
        lp = self._listing_file("scout-merge", [bad])
        r = _run_cli_tier("scout-merge", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = json.loads(Path(bad["failed_marker"]).read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "scout-merge-0")
        self.assertEqual(body["tier"], "scout-merge")
        self.assertIn("path-drift", body["reason"])
        out = json.loads(r.stdout)
        self.assertEqual(out["failed"], 1)

    def test_scout_merge_lazy_marker_skip(self):
        # a shard whose .done marker already exists on disk is NOT spawned
        # (lazy pre-spawn check) — same convergence machinery as t2.
        units = [_unit(self.tmp, f"scout-merge-{i}", tier="scout-merge")
                 for i in range(2)]
        done = Path(units[0]["done_marker"])
        done.parent.mkdir(parents=True, exist_ok=True)
        done.write_text("{}", encoding="utf-8")
        lp = self._listing_file("scout-merge", units)
        r = _run_cli_tier("scout-merge", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["waves_run"], 1)     # only the non-terminal unit dispatched
        self.assertFalse(Path(units[1]["failed_marker"]).exists())

    def test_scout_merge_needs_reduce_false_idempotent_no_op(self):
        # REAL enumerator path: scout checkpoints under budget → plan_aggregate
        # needs_reduce=false (no repo field, empty pending) → dispatcher exits 0
        # with 0 units / partial:false (NEVER the missing-repo error, NEVER
        # STALLED).
        import tempfile
        init = Path(tempfile.mkdtemp(prefix="fanout_sm_nr_"))
        try:
            (init / "checkpoints" / "scout").mkdir(parents=True, exist_ok=True)
            (init / "checkpoints" / "scout" / "scout-000.json").write_text(
                json.dumps({"batch_id": "scout-000",
                            "candidates": [{"pad": "y" * 10}]}), encoding="utf-8")
            (init / "run_config.json").write_text("{}", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(SCRIPT), "--tier", "scout-merge",
                 "--init-dir", str(init), "--budget", "100000",
                 "--checkpoints", str(init / "checkpoints" / "scout"),
                 "--inputs-dir", str(init / "inputs" / "scout-merge")],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["tier"], "scout-merge")
            self.assertEqual((out["total"], out["done"], out["failed"],
                              out["pending"]), (0, 0, 0, 0))
            self.assertFalse(out["partial"])
            self.assertFalse(out["stalled"])
        finally:
            import shutil
            shutil.rmtree(init, ignore_errors=True)

    def test_scout_merge_list_args_forward_to_plan_aggregate(self):
        fr = _load()
        cfg = fr.TIERS["scout-merge"]
        args = type("A", (), {"init_dir": "C:/t/.mgh-init", "budget": 98304,
                              "inputs_dir": "C:/t/.mgh-init/inputs/scout-merge"})()
        argv = cfg["list_args"](args)
        self.assertEqual(argv[:4], ["--node", "scout-merge", "--init-dir",
                                    "C:/t/.mgh-init"])
        self.assertEqual(argv[4:], ["--budget", "98304", "--materialize",
                                     "C:/t/.mgh-init/inputs/scout-merge"])
        # budget not set → NOT forwarded (plan_aggregate DEFAULT_BUDGET applies)
        args2 = type("A", (), {"init_dir": "C:/t/.mgh-init", "budget": None,
                               "inputs_dir": "C:/t/.mgh-init/inputs/scout-merge"})()
        self.assertEqual(cfg["list_args"](args2),
                         ["--node", "scout-merge", "--init-dir", "C:/t/.mgh-init",
                          "--materialize", "C:/t/.mgh-init/inputs/scout-merge"])

    def test_tier_choices_closed_set_contains_scout_merge(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("{scout,scout-merge,t1,t2,t3,sdr}", r.stdout)

    def test_sidecar_per_tier_naming(self):
        for tier, uid in (("scout", "scout-001"), ("t1", "clst-a"),
                          ("t2", "t2-authz"), ("scout-merge", "scout-merge-0"),
                          ("t3", "authn")):
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
        self.calls = []    # (uid, status, ack) per fake _run_unit invocation
        self.windows = []  # the silence window _run_unit was handed, per call

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_run(self, behavior):
        """behavior(uid, nth) -> (status, ack); ok acks write .done.

        Arity-adaptive: the fixed module's _run_unit returns a 6th kill_ok
        element (kill-failure disclosure, TestKillFailureDisposition), the
        pre-fix module returns 5. Adapting keeps the red-first tests running
        each version's REAL dispatch flow — a fixed 6-tuple fake would crash
        the pre-fix dispatch thread with an unpack error and route the run
        through states the fix never exercised."""
        arity6 = hasattr(self.fr, "_KILL_TREE_GRACE_S")

        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            nth = fake.state.get(uid, 0) + 1
            fake.state[uid] = nth
            status, ack = behavior(uid, nth)
            self.calls.append((uid, status, ack))
            # the EFFECTIVE silence window this attempt was judged against
            self.windows.append(stall_timeout_s)
            if ack == "ok":
                unit = next(u for u in self.units if u.get("batch_id") == uid)
                Path(unit["done_marker"]).write_text("done", encoding="utf-8")
            pid = 700000 + len(self.calls)
            if on_spawn is not None:
                on_spawn(pid)
            tail = (status, ack if status == "spawn-ok" else None, status,
                    pid, status == "stall")
            return tail + (True,) if arity6 else tail
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

    def _run_main(self, behavior, *extra, wave="1", stub=None, fake=None):
        stub = stub or self._disk_stub()
        saved_list = dict(self.fr.TIERS["scout"])
        saved_run = self.fr._run_unit
        self.fr.TIERS["scout"]["list_script"] = str(stub)  # absolute → join keeps it
        self.fr._run_unit = (fake or self._fake_run)(behavior)
        # --cooldown-s 0 harness default: the storm-resilience cooldown/backoff
        # layer stays OFF unless a test opts in explicitly (its default 300s
        # gate would stall every breaker test); cooldown tests pass their own
        # --cooldown-s after these.
        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout"),
                "--host", "claude", "--wave", wave, "--cooldown-s", "0", *extra]
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


class TestCooldownWaitCoversDrainedBackoff(_FakeDispatchBase):
    """The cooldown wait gate must cover the DRAINED state: queue empty +
    in-flight zero + cooldown still active. The pre-breaker backoff arms at
    exactly such a point (its trip observation fires right after the queue's
    last requeue was re-dispatched), so the old gate condition —
    `(queue or inflight) and not inflight`, i.e. "queue non-empty" — skipped
    the sleep and the loop spun with ZERO time.sleep calls until the cooldown
    expired (default: 300s of one core).

    Construction (single unit, wave=1, K=--stall-waves x --wave=1): the unit
    crashes twice — each requeue feeds the next dispatch and the K=1 window
    observes at every pop — so the SECOND zero-growth observation trips with
    the just-re-dispatched attempt in flight and an EMPTY queue (two requeues
    stay below the storm threshold, so only the pre-breaker backoff cooldown
    arms). The third attempt completes mid-cooldown without a marker
    (consumed, never requeued), leaving exactly the drained backoff state.
    Assertion is call-counting, never wall-clock: time.sleep must be called
    at least once during that window (pre-fix: zero calls). ~4s wall clock
    (real cooldown slice, sleep-capped at 50ms per call)."""

    N_UNITS = 1

    def test_drained_backoff_cooldown_sleeps_instead_of_spinning(self):
        e_mid = threading.Event()   # releases the post-trip attempt mid-cooldown
        timer = threading.Timer(0.9, e_mid.set)
        sleeps = []
        real_sleep = time.sleep
        script_file = str(SCRIPT)

        def counting_sleep(s):
            # count only sleeps issued by fanout_runner's own code: subprocess
            # wait internals and stdlib polling also call time.sleep and would
            # fake a pass on the pre-fix build
            if sys._getframe(1).f_code.co_filename != script_file:
                return real_sleep(s)
            sleeps.append(s)
            real_sleep(min(s, 0.05))  # cap: keep the test fast, count stays honest

        def behavior(uid, nth):
            if nth <= 2:
                return ("crash", None)      # requeue → feeds the K=1 windows
            e_mid.wait(30)
            return ("spawn-ok", None)       # consumed mid-cooldown, NO marker

        timer.start()
        try:
            with mock.patch("time.sleep", counting_sleep):
                code, out, err = self._run_main(
                    behavior, "--stall-waves", "1", "--cooldown-s", "4")
        finally:
            timer.join()
        # the scenario shape must hold: only the pre-breaker backoff armed
        # (two requeues stay below the storm threshold of three)
        self.assertIn("cooldown #1 (pre-breaker backoff", err)
        self.assertEqual(code, 2, err)          # breaker truncates the stuck tail
        self.assertTrue(json.loads(out)["stalled"])
        self.assertGreaterEqual(
            len(sleeps), 1,
            "cooldown wait with an empty queue and no in-flight units must "
            "sleep, never zero-sleep spin (pre-fix: 0 sleep calls while the "
            "backoff cooldown burned CPU)")


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


class TestKillFailureDisposition(_FakeDispatchBase):
    """Kill-failed disposition — the survivor OWNS the unit: when _kill_tree
    reports False on the stall/timeout path, the unit must NOT re-enter the
    queue (a re-dispatch would run concurrently with the process the kill
    failed on and race its checkpoint), its pid must STAY in the liveness
    children[] (--kill-stale must still find it — pre-fix the terminal path
    unconditionally removed it, minting an untrackable orphan), stderr must
    fail loud with the recovery recipe, and the summary must disclose
    kill_failed[]. The disk-pending-but-never-queueable tail is bounded by
    the zero-progress breaker (stuck-pending operand)."""

    N_UNITS = 2

    def _fake_run6(self, behavior):
        """Like _fake_run but behavior returns (status, ack, kill_ok)."""
        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            nth = fake.state.get(uid, 0) + 1
            fake.state[uid] = nth
            status, ack, kill_ok = behavior(uid, nth)
            self.calls.append((uid, status, ack))
            if ack == "ok":
                unit = next(u for u in self.units if u.get("batch_id") == uid)
                Path(unit["done_marker"]).write_text("done", encoding="utf-8")
            pid = 700000 + len(self.calls)
            if on_spawn is not None:
                on_spawn(pid)
            return (status, ack if status == "spawn-ok" else None, status,
                    pid, status == "stall", kill_ok)
        fake.state = {}
        return fake

    def test_kill_failed_not_redispatched_pid_kept_and_disclosed(self):
        def behavior(uid, nth):
            if uid == "scout-001":
                return ("timeout", None, False)   # kill FAILS every attempt
            return ("spawn-ok", "ok", True)       # scout-002 completes normally

        liveness_writes = []
        real_update = self.fr._update_liveness_children

        def spy_update(path, body, children):
            liveness_writes.append([dict(c) for c in children])
            real_update(path, body, children)

        saved_update = self.fr._update_liveness_children
        self.fr._update_liveness_children = spy_update
        try:
            code, out, err = self._run_main(behavior, fake=self._fake_run6)
        finally:
            self.fr._update_liveness_children = saved_update
        data = json.loads(out)
        self.assertEqual(data["kill_failed"], ["scout-001"],
                         "kill-failed unit must be disclosed (optional key)")
        u1_calls = [c for c in self.calls if c[0] == "scout-001"]
        self.assertEqual(len(u1_calls), 1,
                         "kill-failed unit must NOT be re-dispatched in-run")
        self.assertEqual(code, 2)
        self.assertTrue(data["stalled"],
                        "stuck disk-pending tail is bounded by the breaker")
        self.assertTrue(any(e["id"] == "scout-001"
                            for e in data.get("stalled_pending", [])),
                        "stuck unit must appear in stalled_pending[]")
        # writes: [u1 spawn], [u1+u2 spawn], [u2 terminal removal], [exit clear].
        # The third write must STILL hold scout-001's pid — its kill-failed
        # terminal must not run _terminal_children_rm
        self.assertEqual([c["pid"] for c in liveness_writes[2]], [700001],
                         "kill-failed pid must stay in liveness children[]")
        self.assertIn("TREE-KILL FAILED", err)
        self.assertIn("--kill-stale", err)   # recipe names the recovery path

    def test_kill_failed_key_absent_when_kills_succeed(self):
        # optional-key discipline: no kill failure → the key is absent, not []
        code, out, err = self._run_main(lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("kill_failed", json.loads(out))


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
            return ("crash", None, detail, pid, False, True)
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
                "--host", "claude", "--wave", "1",
                "--cooldown-s", "0"]  # storm layer off: pure breaker semantics
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
        status, ack, detail, pid, was_stalled, kill_ok = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 300, 2, self.tmp / "u1.run.log", "u1")
        elapsed = time.monotonic() - t0
        self.assertEqual(status, "stall")
        self.assertTrue(was_stalled)
        self.assertTrue(kill_ok, "kill success path must report kill_ok=True")
        self.assertIsNone(ack)
        self.assertGreaterEqual(elapsed, 2)
        self.assertLess(elapsed, 30)  # 2s silence threshold + kill/reap slack
        self.assertFalse(self.fr._pid_alive(pid), "child must be dead (tree kill)")
        log = (self.tmp / "u1.run.log").read_text(encoding="utf-8")
        self.assertIn("status: stall", log)
        self.assertIn("hello", log)

    def test_call_timeout_kills_child(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(300)"]
        status, ack, _, pid, was_stalled, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 2, 0, self.tmp / "u2.run.log", "u2")
        self.assertEqual(status, "timeout")
        self.assertFalse(was_stalled)
        self.assertIsNone(ack)
        self.assertFalse(self.fr._pid_alive(pid))
        self.assertIn("status: timeout",
                      (self.tmp / "u2.run.log").read_text(encoding="utf-8"))

    def test_clean_completion_writes_ok_evidence(self):
        cmd = [sys.executable, "-c", "print('hello')"]
        status, _, detail, _, was_stalled, _ = self.fr._run_unit(
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
        status, ack, detail, _, was_stalled, _ = self.fr._run_unit(
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
        status, ack, detail, _, was_stalled, _ = self.fr._run_unit(
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
        status, _, detail, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u7.run.log", "u7")
        self.assertEqual(status, "crash")
        self.assertNotIn("reason:context-overflow", detail)

    def test_tail_cap_bounds_evidence_keeps_end(self):
        filler = "x" * 20000  # well over the 8192 tail cap, under argv limits
        cmd = [sys.executable, "-c",
               f"print({filler!r}); print('END-MARK')"]
        status, _, _, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u5.run.log", "u5")
        self.assertEqual(status, "spawn-ok")
        log = (self.tmp / "u5.run.log").read_text(encoding="utf-8")
        block = log.split("----- stdout tail (last 8192 chars) -----")[1]
        block = block.split("----- stderr tail", 1)[0]
        self.assertLessEqual(len(block), 8192 + 2)  # cap + trailing newline
        self.assertIn("END-MARK", block)

    def test_single_stream_silence_does_not_stall_kill(self):
        """Stall = BOTH streams silent (design D3). A child that keeps writing
        stdout while stderr NEVER emits a byte must survive well past
        --stall-timeout-s; under the old `min` criterion it was killed at
        spawn + threshold (the exact field shape: healthy units dying at 600s)."""
        cmd = [sys.executable, "-c",
               "import time\n"
               "for _ in range(10):\n"
               "    print('tick', flush=True)\n"
               "    time.sleep(0.5)\n"]
        t0 = time.monotonic()
        status, _, _, pid, was_stalled, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 2, self.tmp / "u8.run.log", "u8")
        elapsed = time.monotonic() - t0
        self.assertFalse(was_stalled, "one idle stream must not read as a stall")
        self.assertNotEqual(status, "stall")
        self.assertGreaterEqual(elapsed, 3.5,
                                "child outlived the 2s stall threshold")
        self.assertFalse(self.fr._pid_alive(pid))
        self.assertNotIn("status: stall",
                         (self.tmp / "u8.run.log").read_text(encoding="utf-8"))

    def test_both_streams_silent_still_stall_kills(self):
        """The relaxed criterion MUST NOT become 'never stall': a child that
        emits nothing at all on either stream from spawn is still tree-killed."""
        cmd = [sys.executable, "-c", "import time; time.sleep(300)"]
        t0 = time.monotonic()
        status, ack, _, pid, was_stalled, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 300, 2, self.tmp / "u9.run.log", "u9")
        self.assertEqual(status, "stall")
        self.assertTrue(was_stalled)
        self.assertIsNone(ack)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertFalse(self.fr._pid_alive(pid))
        self.assertIn("status: stall",
                      (self.tmp / "u9.run.log").read_text(encoding="utf-8"))

    def test_zero_window_disables_the_silence_criterion(self):
        """`--stall-timeout-s 0` (task 1.3) is an OFF-SWITCH, not a very large
        number: the SAME silent child is stall-killed at window 2 and left
        alone at window 0, where --call-timeout-s alone bounds convergence.
        The window is the only difference between the two legs — which is what
        makes the disabled mode a real mode."""
        cmd = [sys.executable, "-c", "import time; time.sleep(300)"]
        s1, _, _, pid1, killed1, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 2, None, "u11a")
        self.assertEqual((s1, killed1), ("stall", True))
        self.assertFalse(self.fr._pid_alive(pid1))
        t0 = time.monotonic()
        s2, ack2, _, pid2, killed2, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 2, 0, None, "u11b")
        self.assertEqual((s2, killed2), ("timeout", False))
        self.assertIsNone(ack2)
        self.assertGreaterEqual(time.monotonic() - t0, 2.0)
        self.assertFalse(self.fr._pid_alive(pid2))

    @unittest.skipIf(os.name == "nt",
                     "POSIX session isolation: Windows has no setsid")
    def test_unit_child_leads_its_own_session(self):
        """The POSIX fix in one assertion: the unit child is a session leader
        (sid == its own pid) leading its own process group, and NOT a member of
        the dispatcher's session — that isolation is what scopes _kill_tree's
        killpg to the unit's own tree instead of the caller's."""
        cmd = [sys.executable, "-c",
               "import os; print(os.getsid(0), os.getpid(), os.getpgrp())"]
        status, _, detail, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, None, "u10")
        self.assertEqual(status, "spawn-ok", detail)
        sid, pid, pgid = (int(x) for x in detail.split())
        self.assertEqual(sid, pid, "child must be a session leader (setsid)")
        self.assertEqual(pgid, pid, "child must lead its own process group")
        self.assertNotEqual(sid, os.getsid(0),
                            "child must not share the dispatcher's session")

    def test_kill_tree_does_not_terminate_caller(self):
        """The dispatcher tree-kills a stalled unit from inside its own process.
        POSIX units run in their OWN session (start_new_session), so killpg
        scopes to that unit alone — before the fix the child shared the
        caller's process group and the kill took the caller down with it
        (no stall log, no stdout summary: the field-death shape).

        The probe runs in a CHILD process so a regression surfaces as an exit
        code / missing marker, instead of silently killing the test runner.
        Windows never had this defect (taskkill /T is tree-scoped) — there the
        probe is a liveness smoke check, never a false red."""
        probe = self.tmp / "probe_kill_tree.py"
        probe.write_text(
            "import importlib.util, os, subprocess, sys, time\n"
            f"spec = importlib.util.spec_from_file_location('fr_probe', "
            f"{str(SCRIPT)!r})\n"
            "fr = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(fr)\n"
            "p = subprocess.Popen([sys.executable, '-c',\n"
            "                      'import time; time.sleep(300)'],\n"
            "                     start_new_session=(os.name != 'nt'))\n"
            "time.sleep(1.0)\n"
            "fr._kill_tree(p.pid)\n"
            "time.sleep(1.0)\n"
            "print('alive')\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(probe)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alive", r.stdout,
                      "the caller of _kill_tree MUST survive (POSIX session "
                      "isolation); stderr: " + r.stderr)


class TestKillTreeEscalation(unittest.TestCase):
    """Kill-failure detection needs a real escalation ladder: POSIX SIGTERM
    alone is advisory — a wedged group must be re-checked inside a short
    grace window and escalated to SIGKILL; Windows taskkill retries once.
    The signal layer is monkeypatched — no real process is touched; the
    monkeypatched os.name also lets the POSIX ladder run on Windows
    (signal constants ride module-level getattr fallbacks)."""

    def setUp(self):
        self.fr = _load("fanout_runner_killtree")

    def _posix(self, killpg, kill=None):
        return (
            mock.patch.object(self.fr.os, "name", "posix"),
            # create=True: os.getpgid/killpg don't exist on Windows — the
            # patched-in stand-ins ARE the POSIX surface under test
            mock.patch.object(self.fr.os, "getpgid",
                              lambda pid: pid + 1000, create=True),
            mock.patch.object(self.fr.os, "killpg", killpg, create=True),
            mock.patch.object(self.fr.os, "kill", kill or (lambda p, s: None)),
        )

    def test_posix_escalates_to_sigkill_when_group_survives_sigterm(self):
        calls = []

        def killpg(pgid, sig):
            calls.append(("killpg", pgid, sig))  # sig-0 probe never raises: alive

        ctx = self._posix(killpg)
        with ctx[0], ctx[1], ctx[2], ctx[3], \
                mock.patch.object(self.fr.time, "sleep", lambda s: None), \
                mock.patch.object(self.fr, "_KILL_TREE_GRACE_S", 0.01), \
                mock.patch.object(self.fr, "_KILL_TREE_POLL_S", 0.001):
            ok = self.fr._kill_tree(4242)
        self.assertTrue(ok, "SIGKILL delivered → True")
        sigs = [c[2] for c in calls]
        self.assertEqual(sigs[0], self.fr._SIGTERM, "ladder starts with SIGTERM")
        self.assertIn(0, sigs, "grace window must re-check group liveness")
        self.assertEqual(sigs[-1], self.fr._SIGKILL,
                         "surviving group must be escalated to SIGKILL")
        self.assertEqual(calls[-1][0], "killpg", "escalation hits the GROUP")

    def test_posix_group_gone_after_sigterm_needs_no_sigkill(self):
        calls = []

        def killpg(pgid, sig):
            calls.append(("killpg", pgid, sig))
            if sig == 0:
                raise ProcessLookupError()       # group confirmed gone

        ctx = self._posix(killpg)
        with ctx[0], ctx[1], ctx[2], ctx[3], \
                mock.patch.object(self.fr.time, "sleep", lambda s: None):
            ok = self.fr._kill_tree(4242)
        self.assertTrue(ok)
        self.assertNotIn(self.fr._SIGKILL, [c[2] for c in calls],
                         "confirmed-gone group must not be blind-fired")

    def test_posix_escalation_failure_reports_kill_failed(self):
        def killpg(pgid, sig):
            if sig == 0:
                return                           # still alive through the grace
            raise PermissionError(13, "Operation not permitted")

        def kill(pid, sig):
            raise PermissionError(13, "Operation not permitted")

        ctx = self._posix(killpg, kill)
        with ctx[0], ctx[1], ctx[2], ctx[3], \
                mock.patch.object(self.fr.time, "sleep", lambda s: None), \
                mock.patch.object(self.fr, "_KILL_TREE_GRACE_S", 0.01), \
                mock.patch.object(self.fr, "_KILL_TREE_POLL_S", 0.001):
            ok = self.fr._kill_tree(4242)
        self.assertFalse(ok, "surviving every attempt must report kill-failure")

    def test_windows_taskkill_retries_once_then_reports(self):
        runs = []

        class _R:
            def __init__(self, code):
                self.returncode = code

        def fake_run(argv, **kw):
            runs.append(argv)
            return _R(1)                          # taskkill keeps failing

        with mock.patch.object(self.fr.os, "name", "nt"), \
                mock.patch.object(self.fr.subprocess, "run", fake_run):
            self.assertFalse(self.fr._kill_tree(999))
        self.assertEqual(len(runs), 2, "taskkill failure must retry exactly once")
        runs.clear()

        def fake_run_retry_ok(argv, **kw):
            runs.append(argv)
            return _R(0 if len(runs) == 2 else 1)  # retry succeeds

        with mock.patch.object(self.fr.os, "name", "nt"), \
                mock.patch.object(self.fr.subprocess, "run", fake_run_retry_ok):
            self.assertTrue(self.fr._kill_tree(999))
        self.assertEqual(len(runs), 2)


class TestExitPathChildCleanup(_FakeDispatchBase):
    """main()'s finally tree-kills children STILL registered at exit (design
    D2). Units now run in their own session, so an interrupt (Ctrl-C) no
    longer reaches them through the tty's process group — and clearing
    children_now / deleting the liveness file is precisely what would turn a
    live child into an untrackable orphan (invisible to --kill-stale)."""

    N_UNITS = 1

    def setUp(self):
        super().setUp()
        self.procs = []

    def tearDown(self):
        for p in self.procs:  # never leave a probe child behind on failure
            try:
                p.kill()
            except OSError:
                pass
            try:
                p.wait(timeout=10)
            except Exception:
                pass
        super().tearDown()

    def _fake_run(self, behavior):
        """Registers a REAL non-converging child at spawn, then returns
        child_pid=None so the terminal branch's _terminal_children_rm(None) is
        a no-op — the registration deliberately LEAKS, which is the in-flight
        shape an interrupt leaves behind."""
        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            p = subprocess.Popen([sys.executable, "-c",
                                  "import time; time.sleep(300)"],
                                 start_new_session=(os.name != "nt"))
            self.procs.append(p)
            if on_spawn is not None:
                on_spawn(p.pid)
            unit = next(u for u in self.units if u["batch_id"] == uid)
            Path(unit["done_marker"]).write_text("done", encoding="utf-8")
            self.calls.append((uid, "spawn-ok", "ok"))
            return ("spawn-ok", "ok", "ok", None, False, True)
        return fake

    def test_exit_path_tree_kills_still_registered_children(self):
        code, out, err = self._run_main(lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.procs), 1)
        for p in self.procs:
            p.wait(timeout=30)
            self.assertFalse(self.fr._pid_alive(p.pid),
                             "child still registered at exit must be tree-killed")
        self.assertFalse((self.init / "fanout_runner.scout.pid").exists(),
                         "liveness file must be removed on the normal exit path")


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
        # 1..59 is the typo'd-calibration band (below the floor the false-kill
        # rate dominates). The recipe must name BOTH legal exits: the >= 60
        # compliant minimum AND the 0 off-switch — the off-switch is the whole
        # point of widening the value domain (it used to be hidden behind the
        # `--call-timeout-s - 1` hack).
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "30",
                     "--call-timeout-s", "3600")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("below the floor", r.stderr)
        self.assertIn(">= 60", r.stderr)                 # compliant minimum
        self.assertIn("--stall-timeout-s 0", r.stderr)   # off-switch exit
        self._assert_no_side_effects()

    def test_stall_zero_disables_and_drops_the_ordering_constraint(self):
        # --stall-timeout-s 0 = explicit off. It deliberately violates
        # `stall < call`, so that check MUST be skipped for it (otherwise the
        # only legal off-switch would be rejected by the invariant).
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "0",
                     "--call-timeout-s", "300")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["stall_killed"], [])
        self.assertFalse(data["stalled"])

    def test_stall_negative_rejected(self):
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "-1")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--stall-timeout-s must be >= 0", r.stderr)

    def test_invariant_recipe_offers_the_off_switch(self):
        # The compliant-values recipe accompanies every invariant violation and
        # must disclose the alternative exit (0), not just "raise it".
        r = _run_cli(self.tmp, self._listing_file(), "--stall-timeout-s", "9999")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--stall-timeout-s 300", r.stderr)  # compliant example
        self.assertIn("--stall-timeout-s 0", r.stderr)    # off-switch example

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

    def test_omitted_stall_on_host_driven_run_rejected_with_recipe(self):
        """A host-driven call that omits --stall-timeout-s silently takes the
        out-of-host default (900), which is >= the host-driven --call-timeout-s —
        so it MUST be refused at spawn time, and the recipe MUST carry all three
        exits: pass it explicitly, a compliant pair, and the off-switch. This
        pins the contract against the tempting "just drop the flag" edit, which
        would make every host-driven tier unstartable (exit 2)."""
        r = _run_cli(self.tmp, self._listing_file(), "--time-budget-ms", "480000",
                     "--call-timeout-s", "360")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("--stall-timeout-s 900 must be < --call-timeout-s 360", r.stderr)
        self.assertIn("explicitly", r.stderr)             # pass it explicitly
        self.assertIn("--stall-timeout-s 300", r.stderr)  # compliant example
        self.assertIn("--stall-timeout-s 0", r.stderr)    # off-switch exit
        self._assert_no_side_effects()

    def test_omitted_stall_still_works_out_of_host(self):
        # ...and the same omission is CORRECT when there is no host clamp: the
        # default 900 sits below the out-of-host --call-timeout-s 7200.
        r = _run_cli(self.tmp, self._listing_file())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--stall-timeout-s 900s apply", r.stderr)


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

    def test_sdr_gate_refusal_passes_through_and_dispatches_nothing(self):
        """The slice byte gate refusing (exit 2) IS "do not enter this tier": the real
        diff_group.py runs against a real repo whose single changed file's diff body
        exceeds the standalone cap, and the dispatcher must pass 2 through with ZERO
        side effects — no slice, no grouping.json, hence nothing any subagent could be
        handed. This is the end-to-end half of "fail-loud 零派发"."""
        import subprocess as sp
        repo = self.tmp / "sdrrepo"
        repo.mkdir(parents=True, exist_ok=True)

        def git(*a):
            return sp.run(["git", "-C", str(repo), *a], capture_output=True, text=True)

        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        (repo / "big.sql").write_text("CREATE TABLE t(id INT);\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "init")
        git("checkout", "-qb", "feat")
        # one file whose own diff body alone blows the 64KB default standalone cap: no
        # context block can give that budget back, so level 3 is the only disposition
        (repo / "big.sql").write_text(
            "CREATE TABLE t(id INT, x VARCHAR(9));\n-- " + "z" * (70 * 1024) + "\n",
            encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "feat")

        run_dir = repo / ".mgh-sdr" / "runs" / "gate"
        cfg = dict(self.fr.TIERS["sdr"])
        args = type("A", (), {"repo": str(repo), "base": "master", "branch": "feat",
                              "checkpoints": str(run_dir / "markers"),
                              "inputs_dir": str(run_dir / "slices"),
                              "retry_failed": False})()
        with self.assertRaises(SystemExit) as cm:
            self.fr._list_pending(cfg, args)
        self.assertEqual(cm.exception.code, 2)
        self.assertEqual(list(run_dir.glob("**/*.slice.md")), [])
        self.assertFalse((run_dir / "grouping.json").exists())


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

    def test_sidecar_carries_the_cost_visibility_fields(self):
        # design D4: the second-terminal watcher sees exactly the cost figures
        # the exit summary reports — both written from one computed dict, so
        # the live-elapsed-time denominator cannot make them drift apart.
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, [])), encoding="utf-8")
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        sc = json.loads(self._sidecar_path().read_text(encoding="utf-8"))
        out = json.loads(r.stdout)
        for k in ("stall_killed_slots_s", "stall_killed_slot_pct"):
            self.assertIn(k, sc)
            self.assertEqual(sc[k], out[k], f"sidecar/{k} must equal stdout/{k}")

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


class TestDshHost(unittest.TestCase):
    """dsh as the third peer host (add-mgh-dsh-subagent-fanout). Three spec
    surfaces: spawn-command shape (env task channel → argv carries only the
    inert `-` placeholder), probe chain (dsh appended LAST — dual-host
    machines keep their behavior), and the pre-spawn gate (tier mount /
    mgh profile missing → exit 2 + recipe, zero spawns). Real children are
    `sys.executable -c` probes (same style as TestRunUnitTreeKill): they read
    MGH_TASK_TEXT / stdin back, so no dsh binary is needed to pin the
    delivery channel itself."""

    def setUp(self):
        self.fr = _load("fanout_runner_dsh")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_dsh_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _which(self, present):
        return lambda name: f"C:/fake/bin/{name}.cmd" if name in present else None

    def test_dsh_spawn_shape_snapshot_per_tier(self):
        for tier in ("scout", "t1", "t2", "t3", "sdr"):
            cmd = self.fr._spawn_cmd(self.fr.TIERS[tier], "dsh")
            self.assertEqual(cmd[1:3], ["--profile", "mgh"], tier)
            self.assertEqual(cmd[3], "--patch", tier)
            mount = Path(cmd[4])
            self.assertEqual(mount.name, f"{tier}.yml", tier)
            self.assertEqual(mount.parent.name, "tiers", tier)
            self.assertEqual(mount.parent.parent.name, "dsh", tier)
            # mount root = the mgh-core install root = dispatcher's own
            # parent.parent (scripts/.. — `.claude/mgh-core`, `.opencode/
            # mgh-core`, or dsh's root-level `mgh-core` on a target project)
            self.assertEqual(mount.parent.parent.parent,
                             self.fr.Path(self.fr.__file__).resolve().parent.parent,
                             tier)
            self.assertEqual(cmd[5], "-", tier)
            self.assertEqual(len(cmd), 6, f"{tier}: task NEVER enters argv")

    def test_probe_chain_appends_dsh_last(self):
        # 双端既有次序不受 dsh 加入影响: all three installed → opencode;
        # claude+dsh → claude; only dsh → dsh (仅 dsh 机器可派发).
        for present, expected in (({"opencode", "claude", "dsh"}, "opencode"),
                                  ({"claude", "dsh"}, "claude"),
                                  ({"dsh"}, "dsh")):
            with mock.patch.object(self.fr.shutil, "which", self._which(present)):
                self.assertEqual(self.fr._detect_host(None, self.fr.TIERS["scout"]),
                                 expected)

    def test_all_three_clis_absent_exits_2_with_recipe(self):
        buf = io.StringIO()
        with mock.patch.object(self.fr.shutil, "which", self._which(set())), \
                contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                self.fr._detect_host(None, self.fr.TIERS["scout"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("fallback recipe", buf.getvalue())

    def test_explicit_host_dsh_always_wins(self):
        # 显式 --host 恒优先 over the probe chain's opencode-first default
        with mock.patch.object(self.fr.shutil, "which",
                               self._which({"opencode", "claude", "dsh"})):
            self.assertEqual(self.fr._detect_host("dsh", self.fr.TIERS["scout"]),
                             "dsh")

    def test_explicit_host_dsh_not_installed_exits_2(self):
        with mock.patch.object(self.fr.shutil, "which",
                               self._which({"opencode"})):
            with self.assertRaises(SystemExit) as cm:
                self.fr._detect_host("dsh", self.fr.TIERS["scout"])
        self.assertEqual(cm.exception.code, 2)

    def test_run_unit_delivers_task_via_env_for_dsh(self):
        # byte fidelity across the env channel: multi-line + quotes + non-ascii
        task = "line one\nline two “” — 中文 \"q\" 'a'"
        probe = ("import os\n"
                 "print('ok', len(os.environ['MGH_TASK_TEXT']))\n")
        status, ack, detail, _, _, _ = self.fr._run_unit(
            "dsh", [sys.executable, "-c", probe], task, self.tmp, 60, 0)
        self.assertEqual(status, "spawn-ok")
        self.assertEqual(ack, "ok")
        self.assertEqual(detail, f"ok {len(task)}")

    def test_run_unit_stdin_channel_unchanged_for_stdin_hosts(self):
        # the dsh env branch must NOT touch opencode/claude's stdin delivery
        task = "piped task\nsecond line"
        probe = ("import sys\n"
                 "print('ok', len(sys.stdin.read()))\n")
        tmp = Path(tempfile.mkdtemp(prefix="fanout_dsh_stdin_"))
        try:
            status, ack, detail, _, _, _ = self.fr._run_unit(
                "opencode", [sys.executable, "-c", probe], task, tmp, 60, 0)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertEqual(status, "spawn-ok")
        self.assertEqual(detail, f"ok {len(task)}")

    def test_precheck_reports_mount_and_profile_gaps(self):
        tmp = Path(tempfile.mkdtemp(prefix="fanout_dsh_gate_"))
        try:
            mount = tmp / "mgh-core" / "dsh" / "tiers" / "scout.yml"
            with mock.patch.object(self.fr, "_dsh_tier_mount",
                                   lambda tid: mount):
                # mount missing → exit-worthy message + regenerate recipe
                msg = self.fr._dsh_precheck("scout")
                self.assertIn("mount file missing", msg)
                self.assertIn("install.sh --dsh", msg)
                # mount present, profile missing → profile message
                mount.parent.mkdir(parents=True)
                mount.write_text("[]\n", encoding="utf-8")
                home = tmp / "dshhome"
                home.mkdir()
                with mock.patch.dict(os.environ, {"DSH_HOME": str(home)}):
                    msg = self.fr._dsh_precheck("scout")
                    self.assertIn("profile 'mgh'", msg)
                    # both present → gate passes (None)
                    (home / "profiles" / "mgh").mkdir(parents=True)
                    self.assertIsNone(self.fr._dsh_precheck("scout"))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_gate_blocks_before_any_spawn_in_main(self):
        """Spec scenario 装载缺件: a real main() run on a dsh host with the
        tier mount absent exits 2 with the recipe and spawns NOTHING (never a
        wave of host-error crashes)."""
        tmp = Path(tempfile.mkdtemp(prefix="fanout_dsh_main_"))
        try:
            repo = _setup_repo(tmp, [])
            units = [_unit(tmp, "scout-001")]
            for u in units:
                Path(u["input_path"]).write_text("{}", encoding="utf-8")
            spawns = []
            self.fr._run_unit = lambda *a, **k: spawns.append(a)
            # dsh resolves in PATH, but the repo-root mount never exists here
            with mock.patch.object(self.fr.shutil, "which",
                                   self._which({"dsh"})):
                saved_list = self.fr._list_pending
                self.fr._list_pending = lambda tier, args: _listing(tmp, units)
                argv = ["fanout_runner.py",
                        "--scout-plan", str(repo / ".mgh-init" / "scout_plan.json"),
                        "--checkpoints", str(repo / ".mgh-init" / "checkpoints" / "scout"),
                        "--inputs-dir", str(repo / ".mgh-init" / "inputs" / "scout"),
                        "--host", "dsh", "--cooldown-s", "0"]
                old, sys.argv = sys.argv, argv
                err = io.StringIO()
                try:
                    with contextlib.redirect_stderr(err), \
                            contextlib.redirect_stdout(io.StringIO()):
                        code = self.fr.main()
                finally:
                    sys.argv = old
                    self.fr._list_pending = saved_list
            self.assertEqual(code, 2, err.getvalue())
            self.assertIn("mount file missing", err.getvalue())
            self.assertIn("recipe", err.getvalue().lower())
            self.assertEqual(spawns, [], "gate must spawn ZERO units")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_kill_stale_markers_include_dsh(self):
        # --kill-stale cmdline 标记集含 dsh (fan-out runtime contract row)
        self.assertEqual(self.fr._HOST_CLIS, ("opencode", "claude", "dsh"))


class TestSpawnEnvStripsPwd(unittest.TestCase):
    """The spawned host CLI's env must NOT carry the inherited PWD: opencode
    resolves project identity as PWD ?? cwd, so a runner launched from another
    directory's shell (Git Bash always exports PWD) made the child treat THAT
    directory as the project despite cwd=repo. All three host forms strip it;
    the dsh form still adds MGH_TASK_TEXT (claude/dsh don't read PWD —
    stripping is side-effect-free for them). Popen is wrapped and the child is
    a trivial `python -c pass`."""

    def setUp(self):
        self.fr = _load("fanout_runner_pwd")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_pwd_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_host_forms_strip_pwd_dsh_keeps_task_env(self):
        captured = []
        real_popen = subprocess.Popen

        def spy_popen(cmd, **kw):
            captured.append(dict(kw["env"]) if kw.get("env") is not None
                            else None)
            kw = dict(kw)
            kw.pop("env", None)
            return real_popen([sys.executable, "-c", "pass"], **kw)

        with mock.patch.dict(os.environ, {"PWD": "C:/definitely/not/the/repo"}), \
                mock.patch.object(self.fr.subprocess, "Popen", spy_popen):
            for host in ("opencode", "claude", "dsh"):
                status, _, _, _, _, _ = self.fr._run_unit(
                    host, ["host-cli", "run"], "TASK-TEXT", self.tmp, 30, 0)
                self.assertEqual(status, "spawn-ok", host)
        self.assertEqual(len(captured), 3)
        for host, env in zip(("opencode", "claude", "dsh"), captured):
            self.assertIsNotNone(
                env, f"{host}: env must be an explicit dict "
                     f"(pre-fix: None for opencode/claude = full inheritance)")
            self.assertNotIn("PWD", env, f"{host}: inherited PWD must be stripped")
        self.assertEqual(captured[2].get("MGH_TASK_TEXT"), "TASK-TEXT",
                         "dsh env task channel unchanged")


class TestSafeNameEncoding(unittest.TestCase):
    """_safe_name must BE the enumerator's encoding
    (init_tier.safe_unit_filename — 200-stem cap with a discriminant tail):
    audit .task.md copies and run.log evidence files then stay name-identical
    to the marker paths and writable for ids of any length. Pre-fix private
    copy (only / \\ : replaced, no cap) produced >255-char filenames that
    failed on NTFS with just a warn."""

    def setUp(self):
        self.fr = _load("fanout_runner_safename")
        sys.path.insert(0, str(SCRIPTS))
        import init_tier
        self.encoding = init_tier.safe_unit_filename

    def test_parity_with_init_tier_and_short_ids_byte_identical(self):
        cases = ["scout-001", "a/b:c\\d", "x" * 250, "pre::" + "y" * 250,
                 "A" * 140 + "-MID-" + "x" * 106, ""]
        for c in cases:
            self.assertEqual(self.fr._safe_name(c), self.encoding(c),
                             f"parity broken for id of len={len(c)}")
        # short ids: byte-identical to the pre-fix encoding
        self.assertEqual(self.fr._safe_name("a/b:c\\d"), "a_b_c_d")
        # overlong: capped at the shared stem limit
        self.assertLessEqual(len(self.fr._safe_name("x" * 250)), 200)
        # discriminant tail: ids sharing the head but differing in the tail
        # must not collide after truncation
        a = "A" * 140 + "-MID1-" + "x" * 115
        b = "A" * 140 + "-MID2-" + "y" * 115
        self.assertNotEqual(self.fr._safe_name(a), self.fr._safe_name(b))

    def test_overlong_id_audit_copy_lands_on_disk(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="fanout_safename_"))
        try:
            repo = tmp / "repo"
            init = repo / ".mgh-init"
            (init / "checkpoints" / "scout").mkdir(parents=True)
            (init / "inputs" / "scout").mkdir(parents=True)
            (init / "scout_plan.json").write_text("{}", encoding="utf-8")
            long_id = "scout-" + "z" * 244
            unit = {
                "batch_id": long_id,
                "input_path": str(init / "inputs" / "scout" / "u.input.json"),
                "checkpoint_path": str(init / "checkpoints" / "scout" / "u.json"),
                "done_marker": str(init / "checkpoints" / "scout" / "u.json.done"),
                "failed_marker": str(init / "checkpoints" / "scout" / "u.json.failed"),
                "slice_dir": str(init / "slices"),
            }
            Path(unit["input_path"]).write_text("{}", encoding="utf-8")
            lp = tmp / "pending.json"
            lp.write_text(json.dumps({"repo": str(repo), "total": 1, "done": 0,
                                      "failed": 0, "pending": [unit]}),
                          encoding="utf-8")
            saved_list = dict(self.fr.TIERS["scout"])
            old_argv = sys.argv
            sys.argv = ["fanout_runner.py",
                        "--scout-plan", str(init / "scout_plan.json"),
                        "--checkpoints", str(init / "checkpoints" / "scout"),
                        "--inputs-dir", str(init / "inputs" / "scout"),
                        "--pending-file", str(lp), "--cooldown-s", "0"]
            try:
                with contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    code = self.fr.main()
            finally:
                sys.argv = old_argv
                self.fr.TIERS["scout"].update(saved_list)
            self.assertEqual(code, 0)
            audit = init / "inputs" / "scout" / \
                f"{self.fr._safe_name(long_id)}.task.md"
            self.assertTrue(audit.is_file(),
                            "audit copy must land for an overlong id "
                            "(pre-fix: write failed with only a warn)")
            self.assertLessEqual(len(audit.name), 255)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_overlong_id_run_log_lands(self):
        # the run.log path is built with the same encoding — a direct _run_unit
        # call with a real trivial child proves the evidence file lands
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="fanout_safename_log_"))
        try:
            long_id = "scout-" + "z" * 244
            run_log = (tmp / "cp" / "scout"
                       / f"{self.fr._safe_name(long_id)}.run.log")
            status, _, _, _, _, _ = self.fr._run_unit(
                "claude", [sys.executable, "-c", "print('hello')"], "", tmp,
                30, 0, run_log, long_id)
            self.assertEqual(status, "spawn-ok")
            self.assertTrue(run_log.is_file())
            self.assertIn("hello", run_log.read_text(encoding="utf-8"))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


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

    def _write_run_config(self, **fields) -> Path:
        p = self.run_dir / "run_config.json"
        p.write_text(json.dumps(fields), encoding="utf-8")
        return p

    def test_sdr_codegraph_signal_three_states(self):
        """sdr reads the run dir's run_config.json like every other tier: no
        `no_codegraph` → on; `no_codegraph: true` → off; missing/unparseable → off
        (legacy) with zero stderr noise."""
        plan = self.run_dir / "grouping.json"
        self._write_run_config(base="master", branch="feature-pay")
        self.assertEqual(self.fr._codegraph_signal(plan, "sdr"), "on")

        self._write_run_config(no_codegraph=True)
        self.assertEqual(self.fr._codegraph_signal(plan, "sdr"), "off")

        (self.run_dir / "run_config.json").unlink()
        self.assertEqual(self.fr._codegraph_signal(plan, "sdr"), "off")

        (self.run_dir / "run_config.json").write_text("{not json", encoding="utf-8")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(self.fr._codegraph_signal(plan, "sdr"), "off")
        self.assertEqual(err.getvalue(), "")

    def test_sdr_task_message_codegraph_follows_run_config(self):
        """End-to-end through the CLI: the `{{codegraph}}` placeholder is filled from
        the SAME fact the grouping stage uses. The plan anchor is
        `<run-dir>/grouping.json`, whose parent IS the run dir — so the read lands on
        `<run-dir>/run_config.json` with zero path change."""
        unit = self._sdr_unit()
        Path(unit["input_path"]).write_text("slice", encoding="utf-8")
        audit = self.run_dir / "slices" / f"{unit['unit_id']}.task.md"

        self._write_run_config(base="master", branch="feature-pay")
        r = self._run_cli(self._write_listing(self._listing([unit])))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("codegraph=on", audit.read_text(encoding="utf-8"))

        self._write_run_config(no_codegraph=True)
        r = self._run_cli(self._write_listing(self._listing([unit])))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("codegraph=off", audit.read_text(encoding="utf-8"))

    def test_sdr_codegraph_signal_spares_init_run_config(self):
        """The sdr run dir's own config decides, not a neighbouring init run: an
        unrelated `<init-dir>/run_config.json` is never consulted for sdr."""
        self._write_run_config(base="master")
        elsewhere = self.repo / ".mgh-init" / "run_config.json"
        elsewhere.parent.mkdir(parents=True, exist_ok=True)
        elsewhere.write_text(json.dumps({"no_codegraph": True}), encoding="utf-8")
        self.assertEqual(
            self.fr._codegraph_signal(self.run_dir / "grouping.json", "sdr"), "on")


class TestInitTierCodegraphSignalUnchanged(unittest.TestCase):
    """Guard against drift: sharing the run_config.json read across all tiers MUST NOT
    change the four init tiers, which already read it. Every init tier's plan artifact
    (or t2's re-anchor) is a file whose parent is the init dir — the same neighbour the
    sdr tier now resolves to."""

    PLAN_NAME = {"scout": "scout_plan.json", "t1": "clusters.json",
                 "t2": "run_config.json", "t3": "controls_inventory.json"}

    def setUp(self):
        self.fr = _load("fanout_runner_codegraph_init_test")
        self.tmp = Path(tempfile.gettempdir()) / f"mgh_fanout_cg_{id(self)}"
        self.init = self.tmp / "repo" / ".mgh-init"
        self.init.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _plan(self, tier: str) -> Path:
        p = self.init / self.PLAN_NAME[tier]
        p.write_text("{}", encoding="utf-8")
        return p

    def test_init_tiers_read_the_same_carrier(self):
        for tier, name in self.PLAN_NAME.items():
            plan = self._plan(tier)
            (self.init / "run_config.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self.fr._codegraph_signal(plan, tier), "on", tier)
            (self.init / "run_config.json").write_text(
                json.dumps({"no_codegraph": True}), encoding="utf-8")
            self.assertEqual(self.fr._codegraph_signal(plan, tier), "off", tier)

    def test_init_tiers_degrade_off_on_missing_or_bad_file(self):
        for tier in self.PLAN_NAME:
            plan = self._plan(tier)
            rc = self.init / "run_config.json"
            rc.unlink(missing_ok=True)
            self.assertEqual(self.fr._codegraph_signal(plan, tier), "off", tier)
            rc.write_text("{not json", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(self.fr._codegraph_signal(plan, tier), "off", tier)
            self.assertEqual(err.getvalue(), "")

    def test_tier_key_argument_no_longer_branches(self):
        """`tier_key` is kept for call-site stability only: an unknown/absent tier
        behaves exactly like a known one (no hidden per-tier branch crept back)."""
        plan = self._plan("t1")
        (self.init / "run_config.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.fr._codegraph_signal(plan, "no-such-tier"), "on")
        self.assertEqual(self.fr._codegraph_signal(plan), "on")
        (self.init / "run_config.json").write_text(
            json.dumps({"no_codegraph": True}), encoding="utf-8")
        self.assertEqual(self.fr._codegraph_signal(plan, "no-such-tier"), "off")


class TestT1PackedPendingZeroChange(unittest.TestCase):
    """t1 packing adoption (pack id in the `cluster_id` field slot): the runner consumes
    PACKED pending[] with ZERO changes — same placeholders, same anchor check, same ack
    state machine (test hook = --pending-file, no enumerator invocation)."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_pack_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _pack_unit(self, pid="pack::authorization::ab12cd34") -> dict:
        # mirror the enumerator: cluster_id field carries the CANONICAL pack id, marker/
        # input FILENAMES are `_safe_name`-sanitized (`::` -> `__`, NTFS ADS separator).
        safe = pid.replace(":", "_")
        return dict(_unit(self.tmp, pid, tier="t1"),
                    input_path=str(self.tmp / "repo" / ".mgh-init" / "inputs" / "t1" / f"{safe}.input.json"),
                    checkpoint_path=str(self.tmp / "repo" / ".mgh-init" / "checkpoints" / "t1" / f"{safe}.json"),
                    done_marker=str(self.tmp / "repo" / ".mgh-init" / "checkpoints" / "t1" / f"{safe}.json.done"),
                    failed_marker=str(self.tmp / "repo" / ".mgh-init" / "checkpoints" / "t1" / f"{safe}.json.failed"))

    def _listing_file(self, units, done=0, failed=0):
        _setup_repo(self.tmp, units, tier="t1")
        p = self.tmp / "pending_t1_packed.json"
        p.write_text(json.dumps(_listing(self.tmp, units, done, failed)),
                     encoding="utf-8")
        return p

    def test_t1_pack_id_fills_template_cluster_id_slot(self):
        fr = _load()
        unit = self._pack_unit()
        msg = fr._fill_template(fr.TIERS["t1"],
                                TEMPLATES["t1"].read_text(encoding="utf-8"),
                                unit, str(self.tmp / "repo"), "on")
        self.assertNotIn("{{", msg)
        self.assertIn("pack::authorization::ab12cd34", msg)   # pack id rides cluster_id
        self.assertIn(unit["input_path"], msg)
        self.assertIn(unit["checkpoint_path"], msg)
        self.assertIn(unit["done_marker"], msg)

    def test_t1_pack_placeholder_set_still_covers_template(self):
        # the dual-form template introduced no new placeholders (zero runner change)
        import re
        cfg = _load().TIERS["t1"]
        text = TEMPLATES["t1"].read_text(encoding="utf-8")
        used = set(re.findall(r"\{\{(\w+)\}\}", text))
        self.assertFalse(used - set(cfg["placeholders"]),
                         f"unmapped placeholders: {used - set(cfg['placeholders'])}")

    def test_t1_packed_pending_end_to_end_testhook(self):
        # a packed listing flows through dispatch/audit/summary exactly like clusters
        units = [self._pack_unit(),
                 self._pack_unit("pack::crypto::deadbeef")]
        lp = self._listing_file(units)
        r = _run_cli_tier("t1", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["tier"], "t1")
        self.assertEqual(out["total"], 2)
        self.assertEqual(out["pending"], 0)                   # both packs reached terminal
        self.assertEqual(out["waves_run"], 2)                 # both packs dispatched
        self.assertFalse(out["partial"])
        for u in units:
            audit = self.tmp / "repo" / ".mgh-init" / "inputs" / "t1" / \
                f"{u['cluster_id'].replace(':', '_')}.task.md"
            self.assertTrue(audit.is_file(), audit)           # audit copy per pack
            body = audit.read_text(encoding="utf-8")
            self.assertIn(u["cluster_id"], body)
            self.assertNotIn("{{", body)

    def test_t1_packed_pending_lazy_done_skip_and_failed_marker(self):
        # pack-level markers keep working: done marker on disk -> unit skipped, never spawned
        done_unit = self._pack_unit()
        Path(done_unit["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(done_unit["done_marker"]).write_text("", encoding="utf-8")
        pending_unit = self._pack_unit("pack::crypto::deadbeef")
        lp = self._listing_file([done_unit, pending_unit], done=1)
        r = _run_cli_tier("t1", self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["pending"], 0)
        self.assertEqual(out["waves_run"], 1)                 # only the pending pack spawned


class TestCooldownCapArithmetic(unittest.TestCase):
    """_cooldown_cap_s pure arithmetic (design D3): the cooldown wait is capped
    by remaining time budget minus the in-flight convergence margin; <= 0 =
    no budget for any cooldown (degrade to immediate continue + disclosure);
    no --time-budget-ms = uncapped."""

    def setUp(self):
        self.fr = _load("fanout_runner_cap")

    def test_no_budget_uncapped(self):
        self.assertEqual(self.fr._cooldown_cap_s(300, None, 0.0, [], 0), 300.0)

    def test_generous_budget_returns_ceiling_above_cooldown(self):
        # the cap is a ceiling; the caller applies min(cooldown_s, cap)
        self.assertEqual(self.fr._cooldown_cap_s(300, 600.0, 0.0, [], 0), 600.0)

    def test_tight_budget_shrinks_cooldown(self):
        self.assertEqual(self.fr._cooldown_cap_s(300, 100.0, 0.0, [], 0), 100.0)

    def test_inflight_convergence_margin_shrinks_cap(self):
        # remaining 100, observed avg unit 30s x 2 in-flight = 60 margin -> 40
        self.assertEqual(self.fr._cooldown_cap_s(300, 100.0, 0.0, [30.0, 30.0], 2),
                         40.0)

    def test_exhausted_budget_skips_cooldown(self):
        self.assertEqual(self.fr._cooldown_cap_s(300, 50.0, 50.0, [], 0), 0.0)
        self.assertLessEqual(self.fr._cooldown_cap_s(300, 10.0, 50.0, [], 0), 0.0)


class TestWidenedStallWindowArithmetic(unittest.TestCase):
    """_widened_stall_window pure arithmetic (design D3): one false-kill
    self-evidence event doubles the effective silence window, clamped at the
    `--call-timeout-s` convergence margin so the absolute per-call kill always
    stays reachable. Returning the input unchanged (== at the ceiling) is what
    the caller reads as "no event to disclose"."""

    def setUp(self):
        self.fr = _load("fanout_runner_widen")

    def test_doubles_below_the_ceiling(self):
        self.assertEqual(self.fr._widened_stall_window(900, 7200), 1800)

    def test_overflow_lands_exactly_on_the_ceiling_not_skipped(self):
        # 3600 x 2 = 7200 > 7200 x 0.8 = 5760 -> land ON 5760 (task 2.4: an
        # overflowing doubling takes the cap, it never aborts the widening)
        self.assertEqual(self.fr._widened_stall_window(3600, 7200), 5760)

    def test_at_the_ceiling_is_a_no_op(self):
        self.assertEqual(self.fr._widened_stall_window(5760, 7200), 5760)

    def test_result_never_reaches_the_call_timeout(self):
        for call in (300, 540, 2000, 7200):
            w = 60
            for _ in range(20):            # ratchet hard at the ceiling
                w = self.fr._widened_stall_window(w, call)
            self.assertLess(w, call, f"window {w} must stay below call {call}")
            self.assertLessEqual(w, int(call * 0.8))


class TestPercentileInt(unittest.TestCase):
    """_percentile_int pure arithmetic (design D4): nearest-rank, so every
    reported runtime is an OBSERVED value rather than an interpolated one."""

    def setUp(self):
        self.fr = _load("fanout_runner_pct")

    def test_nearest_rank_over_a_known_population(self):
        v = [float(x) for x in range(1, 101)]   # 1..100
        self.assertEqual(self.fr._percentile_int(v, 50), 50)
        self.assertEqual(self.fr._percentile_int(v, 95), 95)
        self.assertEqual(self.fr._percentile_int(v, 99), 99)
        self.assertEqual(self.fr._percentile_int(v, 100), 100)

    def test_degenerate_populations(self):
        self.assertEqual(self.fr._percentile_int([7.4], 50), 7)
        self.assertEqual(self.fr._percentile_int([1.0, 9.0], 50), 1)
        self.assertEqual(self.fr._percentile_int([1.0, 9.0], 99), 9)

    def test_rounds_to_whole_seconds(self):
        self.assertEqual(self.fr._percentile_int([133.6], 50), 134)


class TestAdaptiveStallWindow(_FakeDispatchBase):
    """False-kill self-evidence + bounded adaptive silence window (design D3).

    The trigger is the only hard evidence this environment can produce that a
    silence was NOT fatal: the unit the window killed then completed on
    re-dispatch within the same run. A run with no such event keeps the
    configured window exactly (TestRunUnitTreeKill holds the unchanged path)."""

    N_UNITS = 3

    @staticmethod
    def _behavior(stall_units):
        def behavior(uid, nth):
            return ("stall", None) if (nth == 1 and uid in stall_units) \
                else ("spawn-ok", "ok")
        return behavior

    def test_stall_killed_then_completed_widens_the_window(self):
        code, out, err = self._run_main(self._behavior({"scout-001"}))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["stall_killed"], ["scout-001"])
        # default 900 doubles to 1800; the summary reports the EFFECTIVE value
        self.assertEqual(data["stall_window_s"], 1800)
        self.assertIn("stall window widened 900s -> 1800s", err)
        widened = [ln for ln in err.splitlines() if "stall window widened" in ln]
        self.assertEqual(len(widened), 1, err)
        self.assertIn("unit scout-001", widened[0])
        # the window is snapshotted AT SPAWN, so the re-dispatch that TRIGGERS
        # the widening was itself still judged at the old value — the widening
        # reaches dispatches after it, never retroactively the one running
        self.assertEqual(self.windows, [900, 900, 900, 900])
        self.assertEqual(data["waves_run"], 4)

    def test_widening_is_bounded_by_the_call_timeout_margin(self):
        # 60 -> 120 -> 240 (= --call-timeout-s 300 x 0.8, the ceiling). The
        # third success has nothing left to widen, so it stays silent: exactly
        # two disclosure lines, and the window never reaches --call-timeout-s
        # itself (the absolute kill must remain reachable above it).
        code, out, err = self._run_main(
            self._behavior({"scout-001", "scout-002", "scout-003"}),
            "--stall-timeout-s", "60", "--call-timeout-s", "300")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["waves_run"], 6)
        self.assertEqual(data["stall_window_s"], 240)
        self.assertLess(data["stall_window_s"], 300)
        widened = [ln for ln in err.splitlines() if "stall window widened" in ln]
        self.assertEqual(len(widened), 2, err)
        self.assertIn("60s -> 120s", widened[0])
        self.assertIn("120s -> 240s", widened[1])
        # every attempt is judged at the window in force AT ITS SPAWN: the three
        # opening (killed) attempts and the one that triggers the first
        # widening at 60, the next at 120, the last at 240
        self.assertEqual(self.windows, [60, 60, 60, 60, 120, 240])

    def test_repeated_kills_of_one_unit_still_count_once(self):
        # scout-001 is silence-killed TWICE and completes on the third attempt:
        # one success, therefore ONE widening event. (Reachability note: a unit
        # cannot be re-dispatched after it succeeds — its marker ends it — so
        # the per-unit dedup guard is exercised here as "N kills of one unit
        # are one piece of evidence", not as a second success.)
        def behavior(uid, nth):
            if uid == "scout-001" and nth <= 2:
                return ("stall", None)
            return ("spawn-ok", "ok")
        code, out, err = self._run_main(behavior)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["waves_run"], 5)
        self.assertEqual(data["stall_killed"], ["scout-001", "scout-001"])
        self.assertEqual(data["stall_window_s"], 1800)
        self.assertEqual(
            len([ln for ln in err.splitlines() if "stall window widened" in ln]),
            1, err)

    def test_no_event_keeps_the_window_and_omits_the_field(self):
        # Clean run: the summary must NOT carry stall_window_s at all (an
        # always-present key reporting the configured value would read as
        # "this run widened", which is the opposite of the truth).
        code, out, err = self._run_main(self._behavior(set()))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertNotIn("stall_window_s", data)
        self.assertNotIn("stall window widened", err)

    def test_disabled_criterion_never_widens(self):
        # --stall-timeout-s 0: there is no window to widen, and no window to
        # exceed — so no stall event exists to self-certify against. Every
        # dispatch must be handed 0 (which is what makes _run_unit's silence
        # branch unreachable; the behavioural half of this lives in
        # TestRunUnitTreeKill.test_zero_window_disables_the_silence_criterion).
        code, out, err = self._run_main(self._behavior(set()),
                                        "--stall-timeout-s", "0",
                                        "--call-timeout-s", "300")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(self.windows, "the run dispatched something")
        self.assertEqual(set(self.windows), {0})
        self.assertNotIn("stall_window_s", data)
        self.assertNotIn("stall window widened", err)
        self.assertEqual(data["stall_killed"], [])

    def test_cost_visibility_fields(self):
        # A stall kill burns slot-seconds; a run with completed units reports
        # their runtime distribution. Both are what makes the threshold
        # re-calibratable from data instead of guesswork (design D4).
        code, out, err = self._run_main(self._behavior({"scout-001"}))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        for k in ("runtime_p50_s", "runtime_p95_s", "runtime_max_s",
                  "stall_killed_slots_s", "stall_killed_slot_pct"):
            self.assertIn(k, data)
        for k in ("runtime_p50_s", "runtime_p95_s", "runtime_max_s"):
            self.assertIsInstance(data[k], int, k)
        self.assertGreaterEqual(data["stall_killed_slots_s"], 0)
        self.assertGreaterEqual(data["stall_killed_slot_pct"], 0.0)
        self.assertLessEqual(data["stall_killed_slot_pct"], 100.0)
        self.assertLessEqual(data["runtime_p50_s"], data["runtime_p95_s"])
        self.assertLessEqual(data["runtime_p95_s"], data["runtime_max_s"])
        self.assertEqual(data["stall_killed"], ["scout-001"])


class TestCostVisibilityOmission(unittest.TestCase):
    """Design D4 omission semantics: with no completed unit the three runtime
    keys are ABSENT, not 0 — 0 seconds would read as "units are instant"
    rather than "no data", which is exactly the misreading that would poison a
    later calibration."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_cost_"))
        self.units = [_unit(self.tmp, f"scout-{i:03d}") for i in range(1, 3)]
        _setup_repo(self.tmp, self.units)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_runtime_keys_absent_when_nothing_completed(self):
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, self.units)), encoding="utf-8")
        # zero time budget -> soft-stop before any dispatch: no unit completes
        r = _run_cli(self.tmp, lp, "--time-budget-ms", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertTrue(data["partial"])
        for k in ("runtime_p50_s", "runtime_p95_s", "runtime_max_s"):
            self.assertNotIn(k, data)
        self.assertEqual(data["stall_killed_slots_s"], 0)
        self.assertEqual(data["stall_killed_slot_pct"], 0.0)

    def test_empty_run_still_carries_the_cost_pair(self):
        lp = self.tmp / "pending.json"
        lp.write_text(json.dumps(_listing(self.tmp, [])), encoding="utf-8")
        r = _run_cli(self.tmp, lp)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        self.assertEqual(data["waves_run"], 0)
        self.assertEqual(data["stall_killed_slots_s"], 0)
        self.assertEqual(data["stall_killed_slot_pct"], 0.0)
        self.assertNotIn("runtime_p50_s", data)


class _StormBase(_FakeDispatchBase):
    """Shared harness for cooldown/storm/retry tests: like _fake_run but the
    behavior returns (status, ack, detail) so a crash's detail can carry the
    rate-limit mark the way the real _run_unit leaves it."""

    def _fake_run3(self, behavior):
        def fake(host, cmd, task, cwd, call_timeout_s, stall_timeout_s=0,
                 run_log_path=None, uid="", on_spawn=None):
            nth = fake.state.get(uid, 0) + 1
            fake.state[uid] = nth
            status, ack, detail = behavior(uid, nth)
            self.calls.append((uid, status, ack))
            if ack == "ok":
                unit = next(u for u in self.units if u.get("batch_id") == uid)
                Path(unit["done_marker"]).write_text("done", encoding="utf-8")
            pid = 700000 + len(self.calls)
            if on_spawn is not None:
                on_spawn(pid)
            return (status, ack if status == "spawn-ok" else None, detail,
                    pid, status == "stall", True)
        fake.state = {}
        return fake

    def _run_main3(self, behavior, *extra, wave="1"):
        stub = self._disk_stub()
        saved_list = dict(self.fr.TIERS["scout"])
        saved_run = self.fr._run_unit
        self.fr.TIERS["scout"]["list_script"] = str(stub)
        self.fr._run_unit = self._fake_run3(behavior)
        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout"),
                "--host", "claude", "--wave", wave, "--cooldown-s", "0", *extra]
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

    def _rl_crash(self, uid):
        return ("crash", None,
                f"{self.fr._RATELIMIT_MARK}; exit=1; "
                f"stderr tail: 429 Too Many Requests for unit {uid}")


class TestFastFailCooldown(_StormBase):
    """Fast-fail storm cooldown (design D2/D3): requeue events (crash/timeout/
    stall/spawn-error re-queues; failed acks and pre-spawn failures never
    count) within the sliding window arm a budget-capped cooldown that pauses
    NEW dispatch only; before the breaker exits, at most one bounded backoff
    (cooldown -> disk re-derivation -> re-observe) may disarm it."""

    def test_third_requeue_triggers_cooldown_then_bounded_backoff(self):
        code, out, err = self._run_main3(lambda uid, nth: ("crash", None, "crash"),
                                         "--cooldown-s", "1")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["stalled"])
        self.assertGreaterEqual(data["cooldowns"], 2)   # storm + pre-breaker backoff
        self.assertIn("cooldown #1", err)
        self.assertIn("pausing NEW dispatch", err)
        self.assertIn("pre-breaker backoff", err)

    def test_in_flight_units_keep_harvesting_during_cooldown(self):
        # scout-002 sleeps well past the cooldown while scout-001's re-crashes
        # arm it: the ok ack must still land (harvest never pauses), and its
        # ok line lands on stderr AFTER the cooldown line.
        def behavior(uid, nth):
            if uid == "scout-002":
                time.sleep(2.5)
                return ("spawn-ok", "ok", "done")
            return ("crash", None, "crash")
        code, out, err = self._run_main3(behavior, "--cooldown-s", "1", "--wave", "2")
        data = json.loads(out)
        self.assertEqual(data["done"], 1)
        u2 = next(u for u in self.units if u.get("batch_id") == "scout-002")
        self.assertTrue(Path(u2["done_marker"]).is_file())
        self.assertGreaterEqual(data["cooldowns"], 1)
        self.assertLess(err.index("cooldown #1"), err.index("unit scout-002: ok"))

    def test_cooldown_zero_disables_layer(self):
        code, out, err = self._run_main3(lambda uid, nth: ("crash", None, "crash"),
                                         "--cooldown-s", "0")
        self.assertEqual(code, 2, err)
        self.assertEqual(json.loads(out)["cooldowns"], 0)
        self.assertNotIn("cooldown #", err)
        self.assertNotIn("pre-breaker backoff", err)

    def test_negative_cooldown_rejected(self):
        code, _, err = self._run_main3(lambda uid, nth: ("crash", None, "crash"),
                                       "--cooldown-s", "-1")
        self.assertEqual(code, 2)
        self.assertIn("--cooldown-s must be >= 0", err)

    def test_help_documents_storm_mechanisms(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        flat = " ".join(r.stdout.split())
        for needle in ("requeue", "--cooldown-s", "--no-rate-limit-stop",
                       "--retry-failed", "retried_failed", "rate_limited",
                       "rate limit", "pre-breaker backoff"):
            self.assertIn(needle, flat, needle)


class TestRateLimitStorm(_StormBase):
    """Crash-tail rate-limit classification + storm truncation (design D1/D4):
    quota-signature crashes within the since-last-disk-advance window at >=
    --wave ALL rate-limit -> immediate exit 2 fast path (ahead of any new
    cooldown); drift/mixed/unknown degrade to the cooldown + breaker path."""

    N_UNITS = 5

    def test_all_rate_limit_storm_truncates_fast(self):
        # worker-side barrier: both units must crash before either future is
        # harvested, so both crash events accumulate in one dispatch round and
        # no re-dispatch can race ahead of the truncation flag (deterministic
        # waves_run == 2)
        barrier = threading.Barrier(2, timeout=30)

        def behavior(uid, nth):
            barrier.wait()
            return self._rl_crash(uid)
        code, out, err = self._run_main3(behavior, "--wave", "2",
                                         "--cooldown-s", "0")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["rate_limited"])
        self.assertEqual(sorted(data["rate_limited_crashes"]),
                         ["scout-001", "scout-002"])
        self.assertFalse(data["stalled"])                  # fast path, not the breaker
        self.assertNotIn("stalled_pending", data)
        self.assertEqual(data["cooldowns"], 0)             # truncation precedes cooldown
        self.assertEqual(data["waves_run"], 2)
        self.assertIn("rate-limit crash storm", err)
        self.assertIn("--no-rate-limit-stop", err)         # recipe discloses the opt-out
        self.assertIn("crash_cause=rate-limit", err)

    def test_signature_drift_degrades_to_cooldown_path(self):
        code, out, err = self._run_main3(lambda uid, nth: ("crash", None, "crash"),
                                         "--wave", "5", "--cooldown-s", "1")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertNotIn("rate_limited_crashes", data)
        self.assertTrue(data["stalled"])                   # breaker still bounds the loop
        self.assertGreaterEqual(data["cooldowns"], 1)      # event path backstops
        self.assertIn("crash_cause=unknown", err)

    def test_mixed_unknown_crash_blocks_truncation(self):
        def behavior(uid, nth):
            if uid == "scout-003":
                return ("crash", None, "crash")            # script defect, no signature
            return self._rl_crash(uid)
        code, out, err = self._run_main3(behavior, "--wave", "5", "--cooldown-s", "1")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertTrue(data["stalled"])

    def test_no_rate_limit_stop_disables_truncation(self):
        code, out, err = self._run_main3(lambda uid, nth: self._rl_crash(uid),
                                         "--wave", "5", "--no-rate-limit-stop")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertNotIn("rate_limited_crashes", data)
        self.assertNotIn("rate-limit crash storm", err)

    def test_ok_terminal_with_429_in_output_never_classified(self):
        def behavior(uid, nth):
            return ("spawn-ok", "ok", "report cites 429 / rate limit / quota")
        code, out, err = self._run_main3(behavior, "--wave", "2")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertNotIn("crash_cause", err)

    def test_timeout_terminal_not_classified(self):
        def behavior(uid, nth):
            return ("timeout", None, "reason:rate-limit; output silent")
        code, out, err = self._run_main3(behavior, "--wave", "2")
        self.assertEqual(code, 2, err)
        self.assertNotIn("crash_cause", err)
        self.assertFalse(json.loads(out)["rate_limited"])


class TestRateLimitStormTwoUnits(_StormBase):
    """Storm scenarios that need an exact small unit set for deterministic
    threshold/clearing traces."""

    N_UNITS = 2

    def test_below_wave_threshold_never_truncates(self):
        # isolated quota crashes with disk advances in between keep the window
        # count (max 2) below --wave 5: no truncation, the run completes, the
        # event cooldown still fires on the 3 sparse requeues
        def behavior(uid, nth):
            if uid == "scout-001":
                return self._rl_crash(uid) if nth < 4 else ("spawn-ok", "ok", "done")
            return ("spawn-ok", "ok", "done")
        code, out, err = self._run_main3(behavior, "--wave", "5", "--cooldown-s", "1")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertNotIn("rate_limited_crashes", data)
        self.assertFalse(data["stalled"])
        self.assertGreaterEqual(data["cooldowns"], 1)

    def test_disk_advance_clears_storm_window(self):
        # scout-002's ok-advance clears the window between scout-001's quota
        # crashes: truncation fires on the 3rd (not 2nd) crash — proof the
        # window re-anchors on disk terminal advance.
        def behavior(uid, nth):
            if uid == "scout-001":
                return self._rl_crash(uid) if nth < 4 else ("spawn-ok", "ok", "done")
            return ("spawn-ok", "ok", "done")
        code, out, err = self._run_main3(behavior, "--wave", "2", "--cooldown-s", "0")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["rate_limited"])
        self.assertEqual(data["rate_limited_crashes"], ["scout-001"])
        n001 = sum(1 for uid, status, _ in self.calls
                   if uid == "scout-001" and status == "crash")
        self.assertEqual(n001, 3)   # 2 would mean the ok-advance never cleared


class TestRetryFailed(_StormBase):
    """--retry-failed claim semantics: a claimed failed unit's .failed marker
    is deleted at claim (evidence stays in run.log), the unit dispatches
    normally, a re-failure writes a fresh marker, and each unit is retried at
    most once per call."""

    N_UNITS = 2

    def _mark_failed(self, bid):
        u = next(u for u in self.units if u.get("batch_id") == bid)
        Path(u["failed_marker"]).write_text(
            json.dumps({"unit": bid, "reason": "provider blip", "tier": "scout"}),
            encoding="utf-8")

    def test_claim_deletes_marker_and_retries_to_done(self):
        self._mark_failed("scout-001")
        code, out, err = self._run_main3(lambda uid, nth: ("spawn-ok", "ok", "done"),
                                         "--retry-failed")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["retried_failed"], 1)
        u1 = next(u for u in self.units if u.get("batch_id") == "scout-001")
        self.assertFalse(Path(u1["failed_marker"]).exists())   # deleted at claim
        self.assertTrue(Path(u1["done_marker"]).is_file())
        self.assertIn("--retry-failed — .failed marker deleted at claim", err)

    def test_without_flag_failed_marker_lazy_skips(self):
        # without the flag the pre-failed unit is lazy-skipped forever (never
        # spawned); scout-002 still completes, so the skipped unit surfaces as
        # the documented stalled_pending drift (exit 2), not a retry
        self._mark_failed("scout-001")
        code, out, err = self._run_main3(lambda uid, nth: ("spawn-ok", "ok", "done"))
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertEqual(data["retried_failed"], 0)
        self.assertTrue(data["stalled"])
        u1 = next(u for u in self.units if u.get("batch_id") == "scout-001")
        self.assertTrue(Path(u1["failed_marker"]).exists())    # untouched
        n001 = sum(1 for uid, _, _ in self.calls if uid == "scout-001")
        self.assertEqual(n001, 0)                              # never spawned

    def test_retry_is_bounded_once_per_call_and_refails_writes_marker(self):
        # scout-001 re-fails after its one retry: the fresh failed ack rewrites
        # the marker and the once-per-call bound blocks a second claim
        self._mark_failed("scout-001")

        def behavior(uid, nth):
            if uid == "scout-001":
                return ("spawn-ok", "failed:still-broken", "failed:still-broken")
            return ("spawn-ok", "ok", "done")
        code, out, err = self._run_main3(behavior, "--retry-failed")
        self.assertEqual(code, 2, err)                         # breaker ends the loop
        data = json.loads(out)
        self.assertEqual(data["retried_failed"], 1)
        n001 = sum(1 for uid, _, _ in self.calls if uid == "scout-001")
        self.assertEqual(n001, 1)                              # claimed exactly once
        u1 = next(u for u in self.units if u.get("batch_id") == "scout-001")
        self.assertTrue(Path(u1["failed_marker"]).exists())    # re-failure rewrote it


class TestStdoutContractKeys(_FakeDispatchBase):
    """Summary contract: existing fields zero add/remove; the three always-on
    storm-resilience keys (cooldowns/retried_failed/rate_limited) ride every
    summary, plus the two always-on cost-visibility keys
    (stall_killed_slots_s / stall_killed_slot_pct); rate_limited_crashes /
    context_overflow / stalled_pending / stall_window_s and the runtime_*
    trio stay conditional disclosures."""

    N_UNITS = 2

    def test_clean_run_exact_key_set(self):
        code, out, err = self._run_main(lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(
            set(data.keys()),
            {"runner", "tier", "repo", "host", "total", "done", "failed",
             "pending", "wave", "waves_run", "partial", "stall_killed",
             "stalled", "cooldowns", "retried_failed", "rate_limited",
             # cost visibility (design D4): the always-on pair, plus the
             # runtime_* trio (present because this run completed units) and
             # the ABSENT stall_window_s (nothing widened here)
             "stall_killed_slots_s", "stall_killed_slot_pct",
             "runtime_p50_s", "runtime_p95_s", "runtime_max_s"})
        self.assertEqual(data["cooldowns"], 0)
        self.assertEqual(data["retried_failed"], 0)
        self.assertFalse(data["rate_limited"])
        self.assertEqual(data["stall_killed_slots_s"], 0)
        self.assertEqual(data["stall_killed_slot_pct"], 0.0)
        self.assertNotIn("stall_window_s", data)
        for k in ("runtime_p50_s", "runtime_p95_s", "runtime_max_s"):
            self.assertIsInstance(data[k], int, k)


class TestFailedCountSingleCount(_FakeDispatchBase):
    """M1: a failure is counted ONCE. The disk re-list already includes the
    .failed markers this run wrote, so adding the in-run write ledger on top
    reported every failure twice (a full-failure run said 20 for 10 units);
    the --retry-failed decision and the report gap disclosure eat this
    number. Fix shape: max(disk snapshot, start + written), never the sum."""

    N_UNITS = 3

    def _failed_counting_stub(self):
        """Marker-aware enumerator that counts .failed too (the shared
        _disk_stub only derives done)."""
        stub = self.tmp / "stub_failed_enum.py"
        body = f"""
import json, sys
from pathlib import Path
UNITS = json.loads({json.dumps(self.units)!r})
failed = [u for u in UNITS if Path(u['failed_marker']).is_file()]
pending = [u for u in UNITS if not (Path(u['done_marker']).is_file()
                                    or Path(u['failed_marker']).is_file())]
print(json.dumps({{'repo': {str(self.repo)!r}, 'total': len(UNITS),
                   'done': len(UNITS) - len(pending) - len(failed),
                   'failed': len(failed), 'pending': pending}}))
"""
        stub.write_text(body, encoding="utf-8")
        return stub

    def test_relisted_failures_counted_once_in_summary_and_sidecar(self):
        # every unit dies on a failed ack -> marker written -> the drain
        # re-list reports failed=3 on disk; the summary must say 3, not 6
        stub = self._failed_counting_stub()
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "failed: boom"), stub=stub)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["failed"], 3,
                         "each failure counted once (pre-fix double count: 6)")
        self.assertEqual(data["pending"], 0)
        self.assertFalse(data["partial"])
        # the sidecar derives from the same snapshot — same single count
        sidecar = json.loads(
            (self.init / "fanout_progress.scout.json").read_text(encoding="utf-8"))
        self.assertEqual(sidecar["failed"], 3)
        self.assertEqual(sidecar["state"], "exited-clean")


class TestActiveSinkWiring(unittest.TestCase):
    """M2: the dispatcher registers each unit's active output sinks in
    _UNIT_SINKS and _run_unit CLAIMS them — its reader threads roll the
    dispatcher-registered dicts, so the periodic in-flight heartbeat's `idle`
    reads seconds since the child's REAL last byte. Pre-fix the heartbeat
    read a dead dispatch-side copy (never written by any reader) and idle
    always equalled time-since-dispatch, showing healthy units as
    "suspected hung". Real child, no fakes."""

    def setUp(self):
        self.fr = _load("fanout_runner_sinkwiring")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_sink_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.fr._UNIT_SINKS.clear()

    def test_run_unit_claims_registered_sinks_and_rolls_them(self):
        out_sink = {"ts": 0.0, "tail": "", "lock": threading.Lock()}
        err_sink = {"ts": 0.0, "tail": "", "lock": threading.Lock()}
        self.fr._UNIT_SINKS["u1"] = (out_sink, err_sink)
        cmd = [sys.executable, "-c",
               "import time\n"
               "for i in range(6):\n"
               "    print('tick', i, flush=True)\n"
               "    time.sleep(0.2)"]
        status, _, detail, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, self.tmp / "u1.run.log", "u1")
        self.assertEqual(status, "spawn-ok", detail)
        self.assertNotIn("u1", self.fr._UNIT_SINKS, "claim = pop")
        self.assertIn("tick", out_sink["tail"],
                      "reader threads rolled the REGISTERED sink (pre-fix: "
                      "they rolled private copies, tail stayed empty)")
        self.assertGreater(out_sink["ts"], 0.0, "last-byte stamp advanced")
        # the heartbeat's exact idle formula on the live sinks: the child
        # emitted its last byte just before exiting -> idle ~0, far below any
        # stall window (pre-fix the registered ts stayed 0.0 -> idle = now)
        idle = max(0, int(time.monotonic() - max(out_sink["ts"],
                                                 err_sink["ts"])))
        self.assertLess(idle, 2)

    def test_unregistered_uid_builds_private_sinks(self):
        # direct/test callers (no registration) keep the old behavior
        cmd = [sys.executable, "-c", "print('hello')"]
        status, ack, detail, _, _, _ = self.fr._run_unit(
            "claude", cmd, "", self.tmp, 60, 0, None, "u2")
        self.assertEqual(status, "spawn-ok")
        self.assertIsNone(ack, "non-ack stdout parses to None (unchanged)")
        self.assertEqual(detail, "hello")
        self.assertEqual(self.fr._UNIT_SINKS, {})


# ---- B1 lockstep side A: run_config unit budget forwarded to the enumerators
# (fix-mgh-init-enumeration-caliber) ----

class TestRunConfigUnitBudgetForward(unittest.TestCase):
    """The dispatcher reads <init-dir>/run_config.json's budgets.max_unit_bytes and
    forwards it as `--max-unit-bytes <v>` to the scout/t1/t3 enumerator CLI — the
    step-0-recorded budget previously had NO consumer (recorded, then silently
    ignored; sharding stayed on the enumerator default 192KB). Source stays the
    run_config file alone (never a second CLI flag); missing/malformed run_config
    or field -> no flag (enumerator default, legacy runs unchanged; t2/scout-merge
    aggregate tiers are a different budget family and are NOT in scope)."""

    def setUp(self):
        self.fr = _load()
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_rcbudget_"))
        self.init = self.tmp / "repo" / ".mgh-init"
        self.init.mkdir(parents=True, exist_ok=True)

    def _args(self):
        # plan artifacts all anchored inside <init-dir> (the runner's real layout)
        return type("A", (), {
            "scout_plan": str(self.init / "scout_plan.json"),
            "clusters": str(self.init / "clusters.json"),
            "candidates": str(self.init / "controls_candidates.json"),
            "inventory": str(self.init / "controls_inventory.json"),
            "fmt": "opencode", "rules_dir": "r", "target": str(self.tmp / "repo"),
            "checkpoints": str(self.init / "checkpoints"),
            "inputs_dir": str(self.init / "inputs"),
            "retry_failed": False, "budget": None,
            "init_dir": str(self.init)})()

    def _capture_cmd(self, tier_name):
        captured = {}

        def fake_run(cmd, **kw):
            captured["cmd"] = cmd
            return type("R", (), {"returncode": 0,
                                  "stdout": json.dumps({"repo": str(self.tmp / "repo"),
                                                        "total": 0, "done": 0,
                                                        "failed": 0, "pending": []}),
                                  "stderr": ""})()

        cfg = dict(self.fr.TIERS[tier_name])
        with mock.patch.object(self.fr.subprocess, "run", fake_run):
            self.fr._list_pending(cfg, self._args())
        return captured["cmd"]

    def _write_run_config(self, budget):
        (self.init / "run_config.json").write_text(json.dumps(
            {"target": str(self.tmp / "repo"), "budgets": {"max_unit_bytes": budget}}),
            encoding="utf-8")

    def test_recorded_budget_forwarded_to_unit_enumerators(self):
        self._write_run_config(65536)
        for tier in ("scout", "t1", "t3"):
            cmd = self._capture_cmd(tier)
            self.assertIn("--max-unit-bytes", cmd, tier)
            self.assertEqual(cmd[cmd.index("--max-unit-bytes") + 1], "65536", tier)

    def test_aggregate_tiers_never_receive_the_flag(self):
        self._write_run_config(65536)
        for tier in ("t2", "scout-merge"):
            cmd = self._capture_cmd(tier)
            self.assertNotIn("--max-unit-bytes", cmd, tier)

    def test_missing_run_config_no_flag(self):
        for tier in ("scout", "t1", "t3"):
            cmd = self._capture_cmd(tier)
            self.assertNotIn("--max-unit-bytes", cmd, tier)

    def test_field_absent_or_non_positive_no_flag(self):
        (self.init / "run_config.json").write_text(json.dumps(
            {"target": "t", "budgets": {}}), encoding="utf-8")
        self.assertNotIn("--max-unit-bytes", self._capture_cmd("t1"))
        (self.init / "run_config.json").write_text(json.dumps(
            {"target": "t", "budgets": {"max_unit_bytes": 0}}), encoding="utf-8")
        self.assertNotIn("--max-unit-bytes", self._capture_cmd("t1"))
        (self.init / "run_config.json").write_text(json.dumps(
            {"target": "t", "budgets": {"max_unit_bytes": "big"}}), encoding="utf-8")
        self.assertNotIn("--max-unit-bytes", self._capture_cmd("t1"))

class TestQuotaAdmissionArithmetic(unittest.TestCase):
    """Pure arithmetic behind the quota-mode admission gate: admissible iff
    dispatches-in-window x K + K <= N; when blocked, resume ts = the
    (in-window - max-in-window)-th oldest timestamp + W."""

    def setUp(self):
        self.fr = _load("fanout_runner_quota_arith")

    def _adm(self, times, n, w, k, now=1000.0):
        return self.fr._quota_admission(times, w, n, k, now)

    def test_empty_window_admissible(self):
        admissible, used, resume = self._adm([], 100, 600, 10)
        self.assertTrue(admissible)
        self.assertEqual(used, 0)
        self.assertEqual(resume, 0.0)

    def test_exact_fit_boundary_admissible(self):
        # 9 in-window x 10 + 10 = 100 <= 100: the LAST unit of the window
        # still fits (the spec formula is `used + K <= N`, not `used < N`).
        times = [1000.0 - i for i in range(9)]
        admissible, used, _ = self._adm(times, 100, 600, 10)
        self.assertTrue(admissible)
        self.assertEqual(used, 90)

    def test_one_over_blocked_resume_at_oldest_plus_window(self):
        times = [1000.0 - i for i in range(10)]
        admissible, used, resume = self._adm(times, 100, 600, 10)
        self.assertFalse(admissible)
        self.assertEqual(used, 100)
        self.assertAlmostEqual(resume, min(times) + 600)

    def test_aged_out_entries_do_not_count(self):
        # entries older than W are outside the window: 10 dispatches but only
        # 3 still in-window -> 30 + 10 <= 100 admissible
        times = [1000.0 - 700, 1000.0 - 690] + [1000.0 - i for i in range(3)]
        admissible, used, _ = self._adm(times, 100, 600, 10)
        self.assertTrue(admissible)
        self.assertEqual(used, 30)

    def test_multiple_must_slide(self):
        # N=30 K=10: max in-window = 2; 4 in-window -> the 2 OLDEST must
        # slide first -> resume = 2nd-oldest + W
        times = [1000.0 - i * 10 for i in range(4)]  # 970, 980, 990, 1000
        admissible, _, resume = self._adm(times, 30, 600, 10, now=1000.0)
        self.assertFalse(admissible)
        self.assertAlmostEqual(resume, 980.0 + 600)

    def test_never_admissible_reports_now(self):
        # K > N: even zero dispatches cannot fit -> resume = now (the caller
        # owns the wait cadence and must not busy-spin on it)
        admissible, used, resume = self._adm([], 5, 600, 10, now=1000.0)
        self.assertFalse(admissible)
        self.assertEqual(used, 0)
        self.assertEqual(resume, 1000.0)

    def test_caller_list_not_mutated(self):
        times = [900.0, 950.0]
        self._adm(times, 5, 10, 10, now=1000.0)
        self.assertEqual(times, [900.0, 950.0])


class TestQuotaModeStartupValidation(_FakeDispatchBase):
    """Quota flag pairing + value domain, spawn-time fail-loud: quota mode
    activates iff --quota-calls AND --quota-window-s are BOTH passed; any
    other shape is rejected with exit 2 + recipe BEFORE any spawn or
    enumerator side effect (same shape as the timeout-invariant check)."""

    def _ok(self, uid, nth):
        return ("spawn-ok", "ok")

    def _assert_rejected(self, code, err, needle):
        self.assertEqual(code, 2)
        self.assertIn(needle, err)
        self.assertEqual(self.calls, [])  # zero spawn

    def test_calls_without_window_rejected(self):
        code, _, err = self._run_main(self._ok, "--quota-calls", "100")
        self._assert_rejected(code, err, "not paired")

    def test_window_without_calls_rejected(self):
        code, _, err = self._run_main(self._ok, "--quota-window-s", "600")
        self._assert_rejected(code, err, "not paired")

    def test_per_unit_alone_rejected(self):
        code, _, err = self._run_main(self._ok,
                                      "--quota-calls-per-unit", "8")
        self._assert_rejected(code, err, "not paired")

    def test_zero_calls_rejected(self):
        code, _, err = self._run_main(self._ok, "--quota-calls", "0",
                                      "--quota-window-s", "600")
        self._assert_rejected(code, err, "must both be >= 1")

    def test_zero_window_rejected(self):
        code, _, err = self._run_main(self._ok, "--quota-calls", "100",
                                      "--quota-window-s", "0")
        self._assert_rejected(code, err, "must both be >= 1")

    def test_zero_per_unit_rejected(self):
        code, _, err = self._run_main(self._ok, "--quota-calls", "100",
                                      "--quota-window-s", "600",
                                      "--quota-calls-per-unit", "0")
        self._assert_rejected(code, err, "--quota-calls-per-unit must be >= 1")

    def test_paired_run_dispatches_normally(self):
        # the legal pair: admission opens (K defaults to 10, budget 1000
        # comfortably above 1 unit), both units run, quota payload present
        code, out, err = self._run_main(
            self._ok, "--quota-calls", "1000", "--quota-window-s", "600")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["done"], 2)
        self.assertEqual(data["quota"]["calls"], 1000)
        self.assertEqual(data["quota"]["window_s"], 600)
        self.assertEqual(data["quota"]["calls_per_unit"], 10)  # default K
        self.assertEqual(data["quota"]["admission_waits"], 0)

    def test_help_documents_quota_mode(self):
        r = subprocess.run([sys.executable, str(SCRIPT), "--help"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        flat = " ".join(r.stdout.split())
        for needle in ("--quota-calls", "--quota-window-s",
                       "--quota-calls-per-unit", "ESTIMATE",
                       "quota admission", "byte-identical"):
            self.assertIn(needle, flat, needle)


class TestQuotaAdmissionGate(_FakeDispatchBase):
    """End-to-end quota admission (quota mode = an ESTIMATE over this run's
    dispatch timestamps): margin-short pauses pause NEW dispatch only,
    in-flight units keep harvesting, the window slide re-opens admission, the
    wait never crosses the soft deadline, and the zero-progress breaker never
    misreads an admission pause as zero progress."""

    N_UNITS = 3

    def test_margin_short_pauses_then_window_slide_resumes(self):
        # N=2 K=1 W=2: units 1-2 dispatch immediately, unit 3 blocks until
        # unit 1's timestamp slides out (~2s) — one wait episode, then all
        # three done. The wave cap (3) is NOT the binding gate (orthogonal).
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "ok"),
            "--quota-calls", "2", "--quota-window-s", "2",
            "--quota-calls-per-unit", "1", wave="3")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["done"], 3)
        self.assertEqual(data["waves_run"], 3)
        self.assertEqual(data["quota"], {"calls": 2, "window_s": 2,
                                         "calls_per_unit": 1,
                                         "admission_waits": 1})
        self.assertIn("quota admission wait #1", err)
        self.assertIn("pausing NEW dispatch", err)
        self.assertIn("ESTIMATE", err)          # honest boundary on stderr

    def test_in_flight_units_keep_harvesting_during_admission_wait(self):
        # unit 2 sleeps past the wait: its ok ack must land while the
        # admission-wait episode is still open (harvest never pauses)
        def behavior(uid, nth):
            if uid == "scout-002":
                time.sleep(1.2)
                return ("spawn-ok", "ok")
            return ("spawn-ok", "ok")
        code, out, err = self._run_main(
            behavior, "--quota-calls", "2", "--quota-window-s", "2",
            "--quota-calls-per-unit", "1", wave="3")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["done"], 3)
        self.assertLess(err.index("quota admission wait #1"),
                        err.index("unit scout-002: ok"))

    def test_admission_wait_hits_soft_deadline_partial_exit(self):
        # N=1 K=1 W=60: the second unit can NEVER fit this window; the wait
        # runs into the 1.5s soft budget -> exit 0 + partial:true, the two
        # other units stay pending (resumable), wait disclosed, exit clean
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "ok"),
            "--quota-calls", "1", "--quota-window-s", "60",
            "--quota-calls-per-unit", "1",
            "--time-budget-ms", "1500", "--call-timeout-s", "1",
            "--stall-timeout-s", "0")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(data["partial"])
        self.assertEqual(data["done"], 1)
        self.assertEqual(data["pending"], 2)
        self.assertEqual(data["waves_run"], 1)
        self.assertGreaterEqual(data["quota"]["admission_waits"], 1)
        self.assertIn("soft time budget reached", err)

    def test_admission_pause_never_trips_zero_progress_breaker(self):
        # ~4s of ZERO dispatch between the three units (N=1: strictly serial
        # per window): the breaker's observations key on NEW dispatches only,
        # so the pauses must NOT be misread as zero progress (a pre-isolation
        # regression stalled here via the drain re-list observation point)
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "ok"),
            "--quota-calls", "1", "--quota-window-s", "2",
            "--quota-calls-per-unit", "1",
            "--time-budget-ms", "15000", "--call-timeout-s", "5",
            "--stall-timeout-s", "0")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["stalled"])
        self.assertNotIn("stalled_pending", data)
        self.assertEqual(data["done"], 3)
        self.assertEqual(data["quota"]["admission_waits"], 2)

    def test_no_quota_flags_stdout_stderr_sidecar_free_of_quota(self):
        # byte-identity anchor (zero-change leg): without the flags the
        # stdout key set is EXACTLY the pre-quota set, the `quota` key is
        # absent from stdout AND sidecar, and stderr carries no quota token
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertNotIn("quota", data)
        self.assertEqual(set(data), {
            "runner", "tier", "repo", "host", "total", "done", "failed",
            "pending", "wave", "waves_run", "partial", "stall_killed",
            "stalled", "stall_killed_slots_s", "stall_killed_slot_pct",
            "runtime_p50_s", "runtime_p95_s", "runtime_max_s",
            "cooldowns", "retried_failed", "rate_limited"})
        self.assertNotIn("quota admission", err)
        sidecars = list(self.init.glob("fanout_progress.*.json"))
        self.assertEqual(len(sidecars), 1)
        sidecar = json.loads(sidecars[0].read_text(encoding="utf-8"))
        self.assertNotIn("quota", sidecar)

    def test_sidecar_quota_matches_stdout_quota(self):
        code, out, err = self._run_main(
            lambda uid, nth: ("spawn-ok", "ok"),
            "--quota-calls", "1000", "--quota-window-s", "600")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        sidecar = json.loads(
            next(self.init.glob("fanout_progress.*.json"))
            .read_text(encoding="utf-8"))
        self.assertEqual(sidecar.get("quota"), data["quota"])


class TestQuotaWindowReset(_StormBase):
    """Quota-mode cooldown/truncation upgrades: a storm cooldown carrying a
    rate-limit-signature crash waits out the window reset (last signature
    event + W) instead of the fixed --cooldown-s; the crash-storm truncation
    fires only AFTER one full reset wait completed and signature crashes
    still recur. Non-signature events and the pre-breaker backoff keep the
    plain --cooldown-s length; without the quota flags the legacy truncation
    is byte-identical (TestRateLimitStorm is the zero-change lock)."""

    N_UNITS = 5

    def _admission_headroom(self):
        # quota pair big enough that admission never binds in these tests —
        # they exercise the COOLDOWN/TRUNCATION layer, not the gate
        return ("--quota-calls", "1000", "--quota-window-s", "3",
                "--cooldown-s", "1")

    def test_signature_cooldown_waits_out_window_reset_then_truncates(self):
        # round 1: 5 signature crashes -> cooldown waits the FULL 3s reset
        # (not --cooldown-s 1) -> "fully waited" stamp -> round 2 crashes
        # again -> NOW the truncation fires, recipe carries the verify line.
        # worker-side barrier: all five crash before either future is
        # harvested, so no slot frees early enough to re-dispatch ahead of
        # the cooldown arm (deterministic waves_run == 10).
        barrier = threading.Barrier(5, timeout=30)

        def behavior(uid, nth):
            if nth == 1:
                barrier.wait()
            return self._rl_crash(uid)
        code, out, err = self._run_main3(behavior,
                                         *self._admission_headroom(),
                                         wave="5")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["rate_limited"])
        self.assertFalse(data["stalled"])            # fast path, not breaker
        self.assertEqual(sorted(data["rate_limited_crashes"]),
                         [f"scout-{i:03d}" for i in range(1, 6)])
        self.assertEqual(data["cooldowns"], 1)
        self.assertEqual(data["waves_run"], 10)      # 5 + 5 (one full reset between)
        self.assertIn("waiting out the quota window reset", err)
        self.assertIn("quota window reset fully waited", err)
        self.assertIn("verify --quota-calls 1000", err)
        self.assertIn("crash_cause=rate-limit", err)

    def test_full_reset_then_recovery_never_truncates(self):
        # every unit crashes once (signature) then succeeds: the reset wait
        # self-heals the window exhaustion — no truncation, run completes
        def behavior(uid, nth):
            if nth == 1:
                return self._rl_crash(uid)
            return ("spawn-ok", "ok", "done")
        code, out, err = self._run_main3(behavior, "--quota-calls", "1000",
                                         "--quota-window-s", "2",
                                         "--cooldown-s", "1", wave="5")
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertNotIn("rate_limited_crashes", data)
        self.assertEqual(data["done"], 5)
        self.assertEqual(data["cooldowns"], 1)
        self.assertIn("quota window reset fully waited", err)

    def test_non_signature_cooldown_keeps_fixed_length(self):
        # unknown-cause crashes under quota mode: cooldown stays at the
        # fixed --cooldown-s (no window-reset note), drift path backstops
        code, out, err = self._run_main3(lambda uid, nth: ("crash", None, "crash"),
                                         *self._admission_headroom(),
                                         wave="5")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertFalse(data["rate_limited"])
        self.assertTrue(data["stalled"])
        self.assertGreaterEqual(data["cooldowns"], 1)
        self.assertNotIn("waiting out the quota window reset", err)
        self.assertNotIn("crash_cause=rate-limit", err)

    def test_no_quota_flags_truncates_on_wave_th_crash_zero_change(self):
        # zero-change leg: without the flags the FIRST wave-th all-signature
        # crash window truncates immediately — no reset-wait precondition
        code, out, err = self._run_main3(lambda uid, nth: self._rl_crash(uid),
                                         wave="1")
        self.assertEqual(code, 2, err)
        data = json.loads(out)
        self.assertTrue(data["rate_limited"])
        self.assertEqual(data["waves_run"], 1)
        self.assertNotIn("quota window reset", err)
        self.assertNotIn("--quota-calls", err)





class TestMaterializeChildConfig(unittest.TestCase):
    """Per-unit child config materialization (static credential injection):
    global-config copy with ONLY the cred-declared provider overridden to the
    static baseURL+apiKey entry; provider id UNCHANGED (model-id prefix
    coupling); plugins/agents/model preserved verbatim; idempotent; apikey
    lands only in the written file."""

    def setUp(self):
        self.fr = _load("fanout_runner_mat")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_mat_"))
        self.global_cfg = self.tmp / "opencode.json"
        self.global_cfg.write_text(json.dumps({
            "model": "wizard-local/glm-4",
            "plugin": ["wizard-opencode-plugin"],
            "provider": {"wizard": {
                "npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "https://placeholder.example",
                            "apiKey": "PLACEHOLDER"}},
                "other": {"npm": "@ai-sdk/other"}}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        self.cred = {"v": 1, "baseURL": "https://gw.example/api",
                     "apikey": "SECRET-TOK", "provider_id": "wizard",
                     "global_config": str(self.global_cfg),
                     "keep_plugins": True, "expired_signatures": ["401"]}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_override_shape_id_unchanged_others_verbatim(self):
        target = self.fr._materialize_child_config(self.cred, self.tmp / "u1")
        body = json.loads(target.read_text(encoding="utf-8"))
        self.assertIn("wizard", body["provider"])
        node = body["provider"]["wizard"]
        self.assertEqual(node["options"]["baseURL"], "https://gw.example/api")
        self.assertEqual(node["options"]["apiKey"], "SECRET-TOK")
        self.assertEqual(node["npm"], "@ai-sdk/openai-compatible")
        # provider ID is the dict key — unchanged by construction; sibling
        # provider, plugins, model preserved
        self.assertIn("other", body["provider"])
        self.assertEqual(body["plugin"], ["wizard-opencode-plugin"])
        self.assertEqual(body["model"], "wizard-local/glm-4")

    def test_idempotent_and_rotated_token_flows(self):
        d = self.tmp / "u1"
        self.fr._materialize_child_config(self.cred, d)
        first = (d / "opencode" / "opencode.json").read_text(encoding="utf-8")
        self.fr._materialize_child_config(self.cred, d)
        self.assertEqual(first,
                         (d / "opencode" / "opencode.json").read_text(
                             encoding="utf-8"))
        rotated = dict(self.cred, apikey="NEW-TOK")
        self.fr._materialize_child_config(rotated, d)
        body = json.loads((d / "opencode" / "opencode.json").read_text(
            encoding="utf-8"))
        self.assertEqual(body["provider"]["wizard"]["options"]["apiKey"],
                         "NEW-TOK")

    def test_keep_plugins_false_strips_plugin_list(self):
        cred = dict(self.cred, keep_plugins=False)
        target = self.fr._materialize_child_config(cred, self.tmp / "u2")
        body = json.loads(target.read_text(encoding="utf-8"))
        self.assertNotIn("plugin", body)

    def test_unknown_provider_valueerror(self):
        cred = dict(self.cred, provider_id="absent")
        with self.assertRaises(ValueError):
            self.fr._materialize_child_config(cred, self.tmp / "u3")

    def test_missing_global_config_valueerror(self):
        cred = dict(self.cred, global_config=str(self.tmp / "absent.json"))
        with self.assertRaises(ValueError):
            self.fr._materialize_child_config(cred, self.tmp / "u4")


class TestCredExpiredTailClassify(unittest.TestCase):
    """Pure signature scan: case-insensitive substring over BOTH tails;
    empty signature set = scan disabled (classification identical to running
    without a cred file)."""

    def setUp(self):
        self.fr = _load("fanout_runner_credtail")

    def _cred(self, sigs):
        return {"expired_signatures": sigs}

    def test_hit_either_stream_case_insensitive(self):
        cred = self._cred(["401", "Login Required"])
        self.assertTrue(self.fr._cred_expired_tail(cred, "", "HTTP 401 up"))
        self.assertTrue(self.fr._cred_expired_tail(cred, "please LOGIN REQUIRED",
                                                   ""))
        self.assertFalse(self.fr._cred_expired_tail(cred, "ok", "fine"))

    def test_empty_signatures_disabled(self):
        self.assertFalse(self.fr._cred_expired_tail(self._cred([]), "401", "401"))


class TestCredStartupValidation(unittest.TestCase):
    """--cred-file startup fail-loud: unreadable / schema-invalid payload →
    exit 2 BEFORE any enumerator side effect."""

    def setUp(self):
        self.base = _FakeDispatchBase.__new__(_FakeDispatchBase)
        self.base.setUp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base.tmp, ignore_errors=True)

    def _cred_file(self, body) -> Path:
        p = self.base.tmp / "cred.json"
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def test_missing_file_exit2(self):
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"),
            "--cred-file", str(self.base.tmp / "nope.json"))
        self.assertEqual(code, 2)
        self.assertIn("cred file unreadable", err)

    def test_bad_schema_exit2(self):
        p = self._cred_file({"v": 1})
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"), "--cred-file", str(p))
        self.assertEqual(code, 2)
        self.assertIn("schema validation", err)
        self.assertIn("baseURL", err)

    def test_valid_cred_never_blocks_dispatch(self):
        gp = self.base.tmp / "opencode.json"
        gp.write_text(json.dumps({"provider": {"wizard": {
            "options": {"baseURL": "https://p", "apiKey": "P"}}}}),
            encoding="utf-8")
        p = self._cred_file({"v": 1, "baseURL": "https://gw", "apikey": "T",
                             "provider_id": "wizard",
                             "global_config": str(gp),
                             "keep_plugins": True,
                             "expired_signatures": []})
        # host patched to the opencode form (the harness bakes --host claude
        # into argv, which the cred gate would rightly refuse): materialization
        # runs, the fake _run_unit converges, done = 2
        saved = self.base.fr._detect_host
        self.base.fr._detect_host = lambda explicit, tier: "opencode"
        try:
            code, out, err = self.base._run_main(
                lambda uid, nth: ("spawn-ok", "ok"), "--cred-file", str(p))
        finally:
            self.base.fr._detect_host = saved
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertEqual(data["done"], 2)
        # child config materialized for both dispatched units
        self.assertTrue((self.base.init / "childcfg" / "scout-001" / "opencode"
                         / "opencode.json").is_file())
        self.assertTrue((self.base.init / "childcfg" / "scout-002" / "opencode"
                         / "opencode.json").is_file())


class TestCredHostGate(unittest.TestCase):
    """--cred-file is opencode-form only: a resolved claude/dsh host exits 2
    with a recipe (NEVER a silent no-credential dispatch). --isolate-data on
    other hosts is a note + proceed (harmless redundancy, not a misuse)."""

    def setUp(self):
        self.base = _FakeDispatchBase.__new__(_FakeDispatchBase)
        self.base.setUp()
        self.fr = self.base.fr

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base.tmp, ignore_errors=True)

    def _cred_file(self) -> Path:
        gp = self.base.tmp / "opencode.json"
        gp.write_text(json.dumps({"provider": {"wizard": {
            "options": {"baseURL": "https://p", "apiKey": "P"}}}}),
            encoding="utf-8")
        p = self.base.tmp / "cred.json"
        p.write_text(json.dumps({"v": 1, "baseURL": "https://gw", "apikey": "T",
                                 "provider_id": "wizard",
                                 "global_config": str(gp),
                                 "keep_plugins": True,
                                 "expired_signatures": []}), encoding="utf-8")
        return p

    def test_claude_host_rejected_exit2_zero_dispatch(self):
        p = self._cred_file()
        saved = self.fr._detect_host
        self.fr._detect_host = lambda explicit, tier: "claude"
        try:
            code, out, err = self.base._run_main(
                lambda uid, nth: ("spawn-ok", "ok"), "--cred-file", str(p))
        finally:
            self.fr._detect_host = saved
        self.assertEqual(code, 2)
        self.assertIn("opencode host form only", err)
        self.assertIn("recipe", err.lower())

    def test_isolate_data_other_host_notes_and_proceeds(self):
        saved = self.fr._detect_host
        self.fr._detect_host = lambda explicit, tier: "claude"
        try:
            code, out, err = self.base._run_main(
                lambda uid, nth: ("spawn-ok", "ok"), "--isolate-data")
        finally:
            self.fr._detect_host = saved
        self.assertEqual(code, 0, err)
        self.assertIn("--isolate-data ignored", err)


class TestCredExpiredTruncation(unittest.TestCase):
    """End-to-end credential-expiry fast-stop: a REAL _run_unit (spy Popen
    swaps the host CLI for a python child that writes a 401 signature to
    stderr and exits non-zero) → the output-tail scan hits → dispatch stops
    immediately (wave=1: the second unit is never dispatched), exit 2, stdout
    credential_expired + credential_expired_units, child config materialized
    for the dispatched unit only."""

    N_UNITS = 2

    def setUp(self):
        import tempfile
        self.fr = _load("fanout_runner_credexp")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_credexp_"))
        self.repo = self.tmp / "repo"
        self.init = self.repo / ".mgh-init"
        (self.init / "checkpoints" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "inputs" / "scout").mkdir(parents=True, exist_ok=True)
        (self.init / "scout_plan.json").write_text("{}", encoding="utf-8")
        self.units = [_unit(self.tmp, f"scout-{i:03d}")
                      for i in range(1, self.N_UNITS + 1)]
        for u in self.units:
            Path(u["input_path"]).write_text("{}", encoding="utf-8")
        self.global_cfg = self.tmp / "opencode.json"
        self.global_cfg.write_text(json.dumps({"provider": {"wizard": {
            "options": {"baseURL": "https://p", "apiKey": "P"}}}}),
            encoding="utf-8")
        self.cred_path = self.tmp / "cred.json"
        self.cred_path.write_text(json.dumps(
            {"v": 1, "baseURL": "https://gw", "apikey": "T",
             "provider_id": "wizard", "global_config": str(self.global_cfg),
             "keep_plugins": True, "expired_signatures": ["401"]}),
            encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_main(self, *extra):
        stub = self.tmp / "stub_enum.py"
        units_json = json.dumps(json.dumps(self.units))
        body = (
            "import json, sys\n"
            "from pathlib import Path\n"
            f"UNITS = json.loads({units_json})\n"
            "pending = [u for u in UNITS if not Path(u['done_marker']).is_file()]\n"
            "print(json.dumps({'repo': " + json.dumps(str(self.repo)) +
            ", 'total': len(UNITS), 'done': 0, 'failed': 0, "
            "'pending': pending}))\n")
        stub.write_text(body, encoding="utf-8")
        saved_list = dict(self.fr.TIERS["scout"])
        saved_detect = self.fr._detect_host
        self.fr.TIERS["scout"]["list_script"] = str(stub)
        self.fr._detect_host = lambda explicit, tier: "opencode"
        real_popen = subprocess.Popen

        def spy_popen(cmd, **kw):
            # the tier enumerator (stub_enum.py) must run FOR REAL — only the
            # host-CLI dispatch spawn is swapped for the 401 child
            if any("stub_enum.py" in str(a) for a in cmd):
                return real_popen(cmd, **kw)
            kw = dict(kw)
            child = [sys.executable, "-c",
                     "import sys; sys.stderr.write('HTTP 401 unauthorized'); "
                     "sys.exit(3)"]
            return real_popen(child, **kw)

        argv = ["fanout_runner.py",
                "--scout-plan", str(self.init / "scout_plan.json"),
                "--checkpoints", str(self.init / "checkpoints" / "scout"),
                "--inputs-dir", str(self.init / "inputs" / "scout"),
                "--cred-file", str(self.cred_path),
                "--wave", "1", "--cooldown-s", "0",
                "--stall-timeout-s", "0", "--call-timeout-s", "60", *extra]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with mock.patch.object(self.fr.subprocess, "Popen", spy_popen), \
                    contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(err):
                code = self.fr.main()
        finally:
            sys.argv = old
            self.fr.TIERS["scout"].update(saved_list)
            self.fr._detect_host = saved_detect
        return code, out.getvalue(), err.getvalue()

    def test_first_401_stops_dispatch(self):
        code, out, err = self._run_main()
        self.assertEqual(code, 2, err[-600:])
        data = json.loads(out)
        self.assertTrue(data["credential_expired"])
        self.assertEqual(data["credential_expired_units"], ["scout-001"])
        # wave=1: the first hit stops the run — unit 2 never dispatched
        self.assertEqual(data["waves_run"], 1)
        self.assertIn("CRED-EXPIRED", err)
        self.assertIn("credential-expired signature matched", err)
        self.assertIn("--resume --retry-failed", err)
        # child config materialized for the dispatched unit only
        u1cfg = (self.init / "childcfg" / "scout-001" / "opencode"
                 / "opencode.json")
        self.assertTrue(u1cfg.is_file())
        self.assertFalse((self.init / "childcfg" / "scout-002").exists())
        # stdout/stderr never echo the apikey value or a key literal
        self.assertNotIn('"apikey"', out)
        self.assertNotIn('"apikey"', err)
        # ocdata dir created for the dispatched unit (data isolation implied)
        self.assertTrue((self.init / "ocdata" / "scout-001").is_dir())


class TestDryRunPurePlan(unittest.TestCase):
    """--dry-run dispatch form = pure plan: exit 0, plan on stdout, ZERO
    disk writes (no liveness/sidecar/audit copies/markers/childcfg)."""

    def setUp(self):
        self.base = _FakeDispatchBase.__new__(_FakeDispatchBase)
        self.base.setUp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base.tmp, ignore_errors=True)

    def _tree(self) -> set:
        return {str(p.relative_to(self.base.tmp)) for p in
                self.base.tmp.rglob("*") if p.is_file()}

    def test_plan_zero_writes_exit0(self):
        stub = self.base._disk_stub()   # stub file exists BEFORE the snapshot
        before = self._tree()
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"), "--dry-run", stub=stub)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        self.assertTrue(data["dry_run"])
        self.assertEqual(data["plan_units"], 2)
        self.assertEqual(len(data["plan"]), 2)
        entry = data["plan"][0]
        self.assertEqual(entry["unit"], "scout-001")
        self.assertTrue(entry["audit_path"].endswith("scout-001.task.md"))
        self.assertTrue(entry["done_marker"])
        self.assertEqual(self._tree(), before, "dry-run must write NOTHING")

    def test_dry_run_path_drift_reported_not_written(self):
        # poison one unit's input path out of tree → the plan flags it as
        # would_fail_pre_spawn instead of writing a .failed marker
        self.base.units[0]["input_path"] = str(self.base.tmp / "evil.slice.md")
        stub = self.base._disk_stub()
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"), "--dry-run", stub=stub)
        self.assertEqual(code, 0, err)
        data = json.loads(out)
        flagged = [e for e in data["plan"] if "would_fail_pre_spawn" in e]
        self.assertEqual(len(flagged), 1)
        self.assertIn("path-drift", flagged[0]["would_fail_pre_spawn"])
        markers = list((self.base.init / "checkpoints" / "scout").glob("*.failed"))
        self.assertEqual(markers, [], "dry-run must not write markers")


class TestSpecialAuthAndOrphanAdvisories(unittest.TestCase):
    """stderr advisories (non-blocking, exit-neutral): the PROJECT-level
    special-auth entry present + no --cred-file → one note; cred-file passed →
    no note; entry absent → no note. A residual liveness file → orphan note."""

    def setUp(self):
        self.base = _FakeDispatchBase.__new__(_FakeDispatchBase)
        self.base.setUp()
        self.fr = self.base.fr

    def tearDown(self):
        import shutil
        shutil.rmtree(self.base.tmp, ignore_errors=True)

    def test_doc_present_notes_absent_cred_dispatches(self):
        doc = self.base.tmp / "doc" / "mgh-special-auth.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("guide", encoding="utf-8")
        saved = self.fr._special_auth_doc_path
        self.fr._special_auth_doc_path = lambda repo=None: doc
        try:
            code, out, err = self.base._run_main(
                lambda uid, nth: ("spawn-ok", "ok"))
        finally:
            self.fr._special_auth_doc_path = saved
        self.assertEqual(code, 0, err)
        self.assertIn("special-auth entry present", err)
        self.assertIn("WITHOUT static injection", err)

    def test_doc_present_with_cred_file_no_note(self):
        doc = self.base.tmp / "doc" / "mgh-special-auth.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("guide", encoding="utf-8")
        gp = self.base.tmp / "opencode.json"
        gp.write_text(json.dumps({"provider": {"wizard": {
            "options": {"baseURL": "https://p", "apiKey": "P"}}}}),
            encoding="utf-8")
        cred = self.base.tmp / "cred.json"
        cred.write_text(json.dumps({"v": 1, "baseURL": "https://gw",
                                    "apikey": "T", "provider_id": "wizard",
                                    "global_config": str(gp),
                                    "keep_plugins": True,
                                    "expired_signatures": []}),
                        encoding="utf-8")
        saved_doc = self.fr._special_auth_doc_path
        saved_host = self.fr._detect_host
        self.fr._special_auth_doc_path = lambda repo=None: doc
        self.fr._detect_host = lambda explicit, tier: "opencode"
        try:
            code, out, err = self.base._run_main(
                lambda uid, nth: ("spawn-ok", "ok"), "--cred-file", str(cred))
        finally:
            self.fr._special_auth_doc_path = saved_doc
            self.fr._detect_host = saved_host
        self.assertEqual(code, 0, err)
        self.assertNotIn("special-auth entry present", err)

    def test_doc_absent_silent(self):
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        self.assertNotIn("special-auth", err)

    def test_stale_liveness_file_orphan_note(self):
        pid_file = self.base.init / "fanout_runner.scout.pid"
        pid_file.write_text(json.dumps({"pid": 999999999,
                                        "started_ts": "2026-10-16T00:00:00",
                                        "tier": "scout", "host": "opencode",
                                        "cmdline": ["x"], "children": []}),
                            encoding="utf-8")
        code, out, err = self.base._run_main(
            lambda uid, nth: ("spawn-ok", "ok"))
        self.assertEqual(code, 0, err)
        self.assertIn("stale liveness file", err)
        self.assertIn("--kill-stale --dry-run", err)


class TestEnvInjectionClaim(unittest.TestCase):
    """_run_unit claims the per-unit XDG env registered in _UNIT_ENV (the env
    twin of _UNIT_SINKS): registered uid → child env carries the two vars;
    unregistered uid → byte-identical legacy env (no XDG vars)."""

    def setUp(self):
        self.fr = _load("fanout_runner_envinj")
        self.tmp = Path(tempfile.mkdtemp(prefix="fanout_envinj_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.fr._UNIT_ENV.clear()

    def test_registered_uid_env_merged_unregistered_clean(self):
        captured = []
        real_popen = subprocess.Popen

        def spy_popen(cmd, **kw):
            captured.append(dict(kw["env"]) if kw.get("env") is not None
                            else None)
            kw = dict(kw)
            kw.pop("env", None)
            return real_popen([sys.executable, "-c", "pass"], **kw)

        self.fr._UNIT_ENV["scout-001"] = {
            "XDG_CONFIG_HOME": str(self.tmp / "cfg"),
            "XDG_DATA_HOME": str(self.tmp / "data")}
        try:
            with mock.patch.object(self.fr.subprocess, "Popen", spy_popen):
                self.fr._run_unit("opencode", ["host-cli", "run"], "TASK",
                                  self.tmp, 30, 0, uid="scout-001")
                self.fr._run_unit("opencode", ["host-cli", "run"], "TASK",
                                  self.tmp, 30, 0, uid="scout-002")
        finally:
            self.fr._UNIT_ENV.clear()
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0]["XDG_CONFIG_HOME"], str(self.tmp / "cfg"))
        self.assertEqual(captured[0]["XDG_DATA_HOME"], str(self.tmp / "data"))
        self.assertNotIn("XDG_CONFIG_HOME", captured[1])
        self.assertNotIn("XDG_DATA_HOME", captured[1])
        # claim semantics: the registry entry was consumed
        self.assertNotIn("scout-001", self.fr._UNIT_ENV)

if __name__ == "__main__":
    unittest.main(verbosity=2)
