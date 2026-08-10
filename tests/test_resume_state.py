#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for resume_state.py — re-entrant orchestrator resume-state machine.

Synthesizes `<target>/.mgh-init/` progress states and asserts step / tiers / next_action are
derived PURELY from disk (independent of any conversation memory). Covers the spec scenarios:
fresh-session mid-T1 resume, run_config statelessness (--no-scout honored), scout-merge not
skipped, completed run, --merge short-circuit, missing run_config fail-loud, --check.
"""
import contextlib, importlib.util, io, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RS = _load("resume_state")
WC = _load("write_runconfig")


class _State:
    """Build a synthetic run dir under a temp target."""
    def __init__(self, fmt="opencode", run_root=".mgh-init", **rc_flags):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_rs_"))
        self.run_root = run_root
        self.init = self.target / run_root
        self.init.mkdir(parents=True, exist_ok=True)
        # write run_config via the real writer (stateless-resume intent source).
        # Only pass --run-root for non-default names so the default case exercises the
        # bare --target path (byte-equivalent to the prior hard-coded .mgh-init behavior).
        argv = ["write_runconfig.py", "--target", str(self.target), "--format", fmt]
        if run_root != ".mgh-init":
            argv += ["--run-root", run_root]
        for k, v in rc_flags.items():
            argv.append(f"--{k.replace('_', '-')}")
            if not isinstance(v, bool):
                argv.append(str(v))
        old, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                WC.main()
        finally:
            sys.argv = old

    def write_json(self, rel, obj):
        p = self.init / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def touch(self, rel):
        p = self.init / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")
        return p

    def state(self):
        s, recipe = RS.resolve(self.init)
        assert s is not None, recipe
        return s

    def main(self, *extra):
        argv = ["resume_state.py", "--init-dir", str(self.init)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def main_target(self, *extra):
        """Resolve the run dir from --target (+ optional --run-root), NOT --init-dir."""
        argv = ["resume_state.py", "--target", str(self.target)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()


class TestResumeState(unittest.TestCase):
    def test_run_config_only_is_discover(self):
        s = _State()
        st = s.state()
        self.assertEqual(st["step"], "discover")
        self.assertEqual(st["tiers"]["discover"], {"done": 0, "failed": 0, "total": 1})
        self.assertEqual(st["next_action"]["kind"], "bash")
        self.assertTrue(st["resumable"])

    def test_no_scout_honored_skips_to_t1(self):
        # --no-scout recorded in run_config: scout tier skipped, discover done -> t1
        s = _State(no_scout=True)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [
            {"cluster_id": "auth::X::aa", "category": "authorization", "kind": "auth"}],
            "truncated": False})
        st = s.state()
        self.assertEqual(st["step"], "t1")          # NOT scout
        self.assertEqual(st["tiers"]["scout"], {"done": 0, "failed": 0, "total": 0})  # skipped
        self.assertEqual(st["tiers"]["t1"], {"done": 0, "failed": 0, "total": 1})

    def test_mid_t1_resume_from_disk(self):
        s = _State(no_scout=True)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [
            {"cluster_id": "auth::X::aa", "category": "authorization", "kind": "auth"},
            {"cluster_id": "crypto::Y::bb", "category": "crypto", "kind": "other"}],
            "truncated": False})
        # one of two t1 units done
        s.write_json("checkpoints/t1/auth_X_aa.json", {"unit": "auth::X::aa"})
        s.touch("checkpoints/t1/auth_X_aa.json.done")
        st = s.state()
        self.assertEqual(st["step"], "t1")
        self.assertEqual(st["tiers"]["t1"], {"done": 1, "failed": 0, "total": 2})
        self.assertEqual(st["next_action"]["kind"], "bash")
        # absolute_paths are absolute + reuse real product paths
        for p in st["next_action"]["absolute_paths"]:
            self.assertTrue(Path(p).is_absolute())

    def test_scout_merge_not_skipped_on_resume(self):
        # all scout reader batches .done, but scout_candidates.json / merge marker absent
        s = _State()  # scout enabled
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [
            {"batch_id": "scout-001"}, {"batch_id": "scout-002"}], "truncated": False})
        for bid in ("scout-001", "scout-002"):
            s.write_json(f"checkpoints/scout/{bid}.json", {"batch_id": bid})
            s.touch(f"checkpoints/scout/{bid}.json.done")
        st = s.state()
        self.assertEqual(st["step"], "scout")               # NOT t1
        self.assertEqual(st["next_action"]["kind"], "subagent")  # init-scout-merge
        self.assertEqual(st["tiers"]["scout"], {"done": 2, "failed": 0, "total": 2})

    def test_completed_run_reports_done(self):
        s = _State(no_scout=True, skip_consistency=True)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        s.write_json("controls_inventory.json", {"repo": str(s.target), "format": "opencode",
                                                  "controls": []})
        s.touch("checkpoints/t2/synthesis.json.done")
        s.write_json("init_manifest.json", {"version": 7, "format": "opencode"})
        st = s.state()
        self.assertEqual(st["step"], "done")
        self.assertFalse(st["resumable"])
        self.assertEqual(st["next_action"]["kind"], "done")

    def test_merge_mode_short_circuit(self):
        s = _State(merge="/tmp/partials")
        st = s.state()
        self.assertEqual(st["step"], "merge")
        self.assertEqual(st["next_action"]["kind"], "bash")

    def test_missing_run_config_fails_loud_exit2(self):
        # .mgh-init exists but run_config.json absent (legacy in-flight run) -> exit 2
        target = Path(tempfile.mkdtemp(prefix="mgh_rs2_"))
        init = target / ".mgh-init"
        init.mkdir(parents=True, exist_ok=True)
        argv = ["resume_state.py", "--init-dir", str(init)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 2)
        self.assertIn("run_config", err.getvalue().lower() + out.getvalue().lower())

    def test_init_dir_missing_exit1(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_rs3_"))
        argv = ["resume_state.py", "--target", str(target)]  # no .mgh-init
        old, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = RS.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 1)

    def test_check_inconsistent_t2_without_inventory_exit2(self):
        s = _State(no_scout=True)
        s.touch("checkpoints/t2/synthesis.json.done")  # marker but no inventory
        code, out, err = s.main("--check")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_check_consistent_exit0(self):
        s = _State(no_scout=True)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        code, out, _ = s.main("--check")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_format_propagated_from_run_config(self):
        s = _State(fmt="claude", no_scout=True)
        self.assertEqual(s.state()["format"], "claude")

    # ---- partial fan-out tolerance (.failed terminal marker; D1-D7) ----

    def _base_t1(self, clusters):
        s = _State(no_scout=True)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": clusters,
                                       "truncated": False})
        return s

    def test_failed_unit_counted_tier_proceeds(self):
        # 2 clusters: 1 done + 1 failed → done+failed>=total → step past t1 to t2
        s = self._base_t1([
            {"cluster_id": "auth::X::aa", "category": "authorization", "kind": "auth"},
            {"cluster_id": "crypto::Y::bb", "category": "crypto", "kind": "other"}])
        s.write_json("checkpoints/t1/auth_X_aa.json", {"unit": "auth::X::aa"})
        s.touch("checkpoints/t1/auth_X_aa.json.done")
        s.write_json("checkpoints/t1/crypto_Y_bb.json.failed",
                     {"unit": "crypto::Y::bb", "reason": "parse error", "tier": "t1"})
        st = s.state()
        self.assertEqual(st["tiers"]["t1"], {"done": 1, "failed": 1, "total": 2})
        self.assertEqual(st["step"], "t2")           # proceeded past t1
        joined = " ".join(st["notes"])
        self.assertIn("t1", joined)                  # failure disclosed in notes
        self.assertIn("failed", joined)

    def test_failed_marker_without_record_body_still_counted(self):
        # .failed with NO sibling record body (subagent failed before writing record):
        # body `unit` is authoritative → still counted; --check must NOT flag it.
        s = self._base_t1([
            {"cluster_id": "crypto::Y::bb", "category": "crypto", "kind": "other"}])
        s.write_json("checkpoints/t1/crypto_Y_bb.json.failed",
                     {"unit": "crypto::Y::bb", "reason": "crash before record", "tier": "t1"})
        st = s.state()
        self.assertEqual(st["tiers"]["t1"], {"done": 0, "failed": 1, "total": 1})
        self.assertNotEqual(st["step"], "t1")        # done+failed=1>=1 → proceeded
        code, out, _ = s.main("--check")
        self.assertEqual(code, 0)                     # absent record is NOT a violation
        self.assertTrue(json.loads(out)["ok"])

    def test_check_both_done_and_failed_exit2(self):
        # one unit carrying BOTH .done and .failed → ambiguous terminal → exit 2
        s = self._base_t1([
            {"cluster_id": "auth::X::aa", "category": "authorization", "kind": "auth"}])
        s.write_json("checkpoints/t1/auth_X_aa.json", {"unit": "auth::X::aa"})
        s.touch("checkpoints/t1/auth_X_aa.json.done")
        s.write_json("checkpoints/t1/auth_X_aa.json.failed",
                     {"unit": "auth::X::aa", "reason": "late ack", "tier": "t1"})
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("ambiguous" in v["issue"] for v in violations),
                        [v["issue"] for v in violations])

    def test_high_failure_rate_advisory(self):
        # failed > total/2 → loud WARNING in notes (run still proceeds; not a gate)
        s = self._base_t1([
            {"cluster_id": f"c{i}::x::{i:02d}", "category": "crypto", "kind": "other"}
            for i in range(4)])
        for i in range(3):  # 3 of 4 failed; 1 still pending → tier NOT complete
            s.write_json(f"checkpoints/t1/c{i}__x__{i:02d}.json.failed",
                         {"unit": f"c{i}::x::{i:02d}", "reason": "r", "tier": "t1"})
        st = s.state()
        self.assertEqual(st["tiers"]["t1"]["failed"], 3)
        self.assertEqual(st["step"], "t1")           # done+failed=3 < 4 → still t1
        self.assertIn("WARNING", " ".join(st["notes"]))

    def test_scout_failed_excludes_merge_audit(self):
        # scout .failed count excludes merge.json/audit.json tier-level markers
        s = _State()  # scout enabled
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [
            {"batch_id": "scout-001"}, {"batch_id": "scout-002"}], "truncated": False})
        s.write_json("checkpoints/scout/scout-001.json.failed",
                     {"unit": "scout-001", "reason": "r", "tier": "scout"})
        # stray tier-level markers that must NOT count as reader-batch failures
        s.touch("checkpoints/scout/merge.json.failed")
        s.touch("checkpoints/scout/audit.json.failed")
        st = s.state()
        self.assertEqual(st["tiers"]["scout"]["failed"], 1)   # only scout-001


    # ---- --run-root: default equivalence / named dir / --init-dir priority ----

    def _base_discover(self, run_root=".mgh-init"):
        s = _State(no_scout=True, run_root=run_root)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        return s

    def test_run_root_default_equals_init_dir_resolution(self):
        # --target <t> (no flags) resolves to <t>/.mgh-init == --init-dir <t>/.mgh-init.
        s = self._base_discover()
        code_def, out_def, _ = s.main_target()                  # default resolution
        code_id, out_id, _ = s.main()                           # explicit --init-dir
        self.assertEqual(code_def, 0)
        self.assertEqual(code_id, 0)
        self.assertEqual(json.loads(out_def)["step"], json.loads(out_id)["step"])
        self.assertEqual(json.loads(out_def)["tiers"], json.loads(out_id)["tiers"])

    def test_run_root_explicit_default_byte_equivalent(self):
        # --target <t> ≡ --target <t> --run-root .mgh-init (spec: byte-level identical).
        s = self._base_discover()
        c1, o1, _ = s.main_target()
        c2, o2, _ = s.main_target("--run-root", ".mgh-init")
        self.assertEqual(c1, c2)
        self.assertEqual(o1, o2)                                # byte-identical stdout

    def test_run_root_named_dir_read(self):
        # --run-root .mgh-ut-init reads <t>/.mgh-ut-init; default --target misses it.
        # Only run_config present (no discover products) -> step="discover".
        s = _State(no_scout=True, run_root=".mgh-ut-init")
        code, out, _ = s.main_target("--run-root", ".mgh-ut-init")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["step"], "discover")   # only run_config present
        # default --target resolves <t>/.mgh-init (absent here) -> exit 1
        code2, _, _ = s.main_target()
        self.assertEqual(code2, 1)

    def test_init_dir_overrides_run_root(self):
        # --init-dir wins over --run-root even when --run-root names a nonexistent dir.
        s = self._base_discover()                               # .mgh-init populated -> t2
        code, out, _ = s.main("--run-root", ".mgh-does-not-exist")
        self.assertEqual(code, 0)                               # --init-dir won
        self.assertEqual(json.loads(out)["step"], "t2")         # read .mgh-init, not bogus dir


# ---- scout-tier gate / stale-credential + D4 scout consistency (fix-mgh-init-scout-stranding) ----


class TestScoutConsistency(unittest.TestCase):
    """--check stale-credential + scout-contribution violations, --invalidate-stale
    dry-run/real consistency, tiers.scout.merged additive field."""

    def _scout_enabled(self):
        s = _State()  # scout enabled (no_scout=false)
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        return s

    # --- stale credentials: scout incomplete + downstream aggregate .done ---

    def test_check_stale_violation_t2_only(self):
        s = self._scout_enabled()
        s.touch("checkpoints/t2/synthesis.json.done")  # no scout_plan → scout incomplete
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("stale" in v["issue"] for v in violations),
                        [v["issue"] for v in violations])

    def test_check_stale_violation_t3_only(self):
        s = self._scout_enabled()
        s.touch("checkpoints/t3/authorization.opencode.json.done")
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("stale" in v["issue"] for v in violations),
                        [v["issue"] for v in violations])

    def test_check_stale_violation_t4_only(self):
        s = self._scout_enabled()
        s.touch("checkpoints/t4/consistency.json.done")
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("stale" in v["issue"] for v in violations),
                        [v["issue"] for v in violations])

    def test_check_no_stale_when_scout_complete(self):
        s = self._scout_enabled()
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [],
                                         "truncated": False})  # 0 batches → complete
        s.write_json("controls_inventory.json", {"repo": str(s.target), "format": "opencode",
                                                  "controls": []})
        s.touch("checkpoints/t2/synthesis.json.done")
        s.touch("checkpoints/t3/authorization.opencode.json.done")
        s.touch("checkpoints/t4/consistency.json.done")
        code, out, _ = s.main("--check")
        self.assertEqual(code, 0)                     # complete → NOT stale
        self.assertTrue(json.loads(out)["ok"])

    def test_invalidate_stale_dry_run_lists_not_deletes(self):
        s = self._scout_enabled()
        t2 = s.touch("checkpoints/t2/synthesis.json.done")
        t4 = s.touch("checkpoints/t4/consistency.json.done")
        code, out, _ = s.main("--invalidate-stale", "--dry-run")
        self.assertEqual(code, 0)
        data = json.loads(out)["invalidate_stale"]
        self.assertTrue(data["dry_run"])
        self.assertEqual(len(data["markers"]), 2)
        self.assertTrue(t2.exists() and t4.exists())   # dry-run touches nothing

    def test_invalidate_stale_deletes_markers(self):
        s = self._scout_enabled()
        t2 = s.touch("checkpoints/t2/synthesis.json.done")
        t4 = s.touch("checkpoints/t4/consistency.json.done")
        code, out, _ = s.main("--invalidate-stale")
        self.assertEqual(code, 0)
        data = json.loads(out)["invalidate_stale"]
        self.assertFalse(data["dry_run"])
        self.assertEqual(len(data["removed"]), 2)
        self.assertFalse(t2.exists() and t4.exists())  # really removed
        # after removal, --check no longer reports the stale violation
        code2, out2, _ = s.main("--check")
        self.assertEqual(code2, 0)                     # no markers left → consistent
        self.assertTrue(json.loads(out2)["ok"])

    # --- D4: scout contribution consistency ---

    def test_check_scout_stranded_violation(self):
        # batches>0 + readers terminal + provenance.scout_merged absent = stranded
        s = self._scout_enabled()
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [
            {"batch_id": "b1"}], "truncated": False})
        s.write_json("checkpoints/scout/b1.json", {"batch_id": "b1"})
        s.touch("checkpoints/scout/b1.json.done")
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("never merged" in v["issue"] for v in violations),
                        [v["issue"] for v in violations])

    def test_check_scout_merged_zero_disclosed_not_gating(self):
        # scout_merged=0 → --check exit 0 + notes[] disclosure (recall-gap advisory)
        s = self._scout_enabled()
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [
            {"batch_id": "b1"}], "truncated": False})
        s.write_json("checkpoints/scout/b1.json", {"batch_id": "b1"})
        s.touch("checkpoints/scout/b1.json.done")
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "provenance": {"scout_merged": 0}})
        code, out, _ = s.main("--check")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertTrue(any("merged 0" in n for n in data["notes"]),
                        data["notes"])

    # --- tiers.scout.merged additive field (resolve) ---

    def test_tiers_scout_merged_present_when_foldin_recorded(self):
        s = _State()
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "provenance": {"scout_merged": 5}})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [], "truncated": False})
        st = s.state()
        self.assertEqual(st["tiers"]["scout"].get("merged"), 5)

    def test_tiers_scout_merged_absent_when_foldin_not_run(self):
        s = _State()  # no provenance / no scout_plan → fold-in never ran
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "truncated": False, "unresolved": []})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        st = s.state()
        self.assertNotIn("merged", st["tiers"]["scout"])

    def test_resolve_notes_merged_zero_disclosure(self):
        s = _State()
        s.write_json("controls_candidates.json", {"repo": str(s.target), "candidates": [],
                                                   "provenance": {"scout_merged": 0}})
        s.write_json("clusters.json", {"repo": str(s.target), "clusters": [], "truncated": False})
        s.write_json("scout_plan.json", {"repo": str(s.target), "batches": [
            {"batch_id": "b1"}], "truncated": False})
        s.write_json("checkpoints/scout/b1.json", {"batch_id": "b1"})
        s.touch("checkpoints/scout/b1.json.done")
        st = s.state()
        self.assertTrue(any("merged 0" in n for n in st["notes"]), st["notes"])


if __name__ == "__main__":
    unittest.main()
