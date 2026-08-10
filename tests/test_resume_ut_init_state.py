#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""resume_ut_init_state — re-entrant ut-init resume from disk (copy of init's resume_state
test, adapted to the ut step graph: classify prelude, no codegraph-resolve step, ut product
names). init's resume_state.py is untouched (its own tests cover it)."""

import contextlib, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RS = _load("resume_ut_init_state")
WC = _load("write_ut_runconfig")


class _State:
    """Build a synthetic ut run dir under a temp target (run_config via the real writer)."""
    def __init__(self, fmt="opencode", run_root=".mgh-ut-init", **rc_flags):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_rsut_"))
        self.run_root = run_root
        self.init = self.target / run_root
        self.init.mkdir(parents=True, exist_ok=True)
        argv = ["write_ut_runconfig.py", "--target", str(self.target), "--format", fmt]
        if run_root != ".mgh-ut-init":
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
        argv = ["resume_ut_init_state.py", "--init-dir", str(self.init)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def main_target(self, *extra):
        argv = ["resume_ut_init_state.py", "--target", str(self.target)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = RS.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def base_classify(self, n=2):
        """test_groups.json with n groups (extract tier total = n)."""
        self.write_json("test_groups.json", {
            "repo": str(self.target),
            "groups": [{"id": f"layer{i}", "layer": "service", "family": "MockitoExtension",
                        "uniformity": "uniform", "member_count": 1,
                        "assert_density": 1.0, "members": [f"src/test/{i}.java"]}
                       for i in range(n)],
            "unclassified": [], "scanned": n, "truncated": False,
        })


class TestResumeUtInitState(unittest.TestCase):
    def test_missing_run_config_fails_loud_exit2(self):
        # an existing run dir with NO run_config.json -> fail-loud (never guess the step graph).
        init = Path(tempfile.mkdtemp(prefix="mgh_rsut_")) / ".mgh-ut-init"
        init.mkdir(parents=True, exist_ok=True)
        code, out, err = RS_main(init)
        self.assertEqual(code, 2)
        self.assertIn("run_config", err + out)

    def test_init_dir_missing_exit1(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_rsut_"))
        init = target / "does-not-exist"
        code, _, err = RS_main(init)
        self.assertEqual(code, 1)

    def test_run_config_only_is_classify(self):
        s = _State()
        st = s.state()
        self.assertEqual(st["step"], "classify")
        self.assertEqual(st["tiers"]["classify"], {"done": 0, "failed": 0, "total": 1})
        self.assertEqual(st["next_action"]["kind"], "bash")
        self.assertTrue(st["resumable"])

    def test_classify_done_is_extract(self):
        s = _State()
        s.base_classify(n=3)
        st = s.state()
        self.assertEqual(st["step"], "extract")
        self.assertEqual(st["tiers"]["extract"], {"done": 0, "failed": 0, "total": 3})

    def test_mid_extract_resume_from_disk(self):
        s = _State()
        s.base_classify(n=2)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        st = s.state()
        self.assertEqual(st["tiers"]["extract"], {"done": 1, "failed": 0, "total": 2})
        self.assertEqual(st["step"], "extract")

    def test_extract_complete_is_synthesize(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        st = s.state()
        self.assertEqual(st["step"], "synthesize")
        self.assertTrue(all(p is not None for p in
                            st["next_action"]["absolute_paths"]))

    def test_synthesize_done_is_rules(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": [
            {"category": "junit5", "name": "x", "layer": "service", "anchor": "a.java::A.t",
             "evidence": ["a.java::A.t"], "provenance": {"groups": ["layer0"], "strong": 1, "weak": 0},
             "confidence": 0.8}]})
        st = s.state()
        self.assertEqual(st["step"], "rules")
        self.assertEqual(st["tiers"]["rules"], {"done": 0, "failed": 0, "total": 1})

    def test_rules_complete_is_assemble(self):
        s = _State(fmt="claude")
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": [
            {"category": "junit5", "name": "x", "layer": "service", "anchor": "a.java::A.t",
             "evidence": ["a.java::A.t"], "provenance": {"groups": ["layer0"], "strong": 1, "weak": 0},
             "confidence": 0.8}]})
        s.write_json("checkpoints/rules/junit5.claude.json", {"unit": "junit5"})
        s.touch("checkpoints/rules/junit5.claude.json.done")
        st = s.state()
        self.assertEqual(st["step"], "assemble")

    def test_assemble_done_is_consistency(self):
        s = _State(fmt="claude")
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": []})
        s.touch("checkpoints/assemble/.done")
        st = s.state()
        self.assertEqual(st["step"], "consistency")

    def test_skip_consistency_goes_to_mutators(self):
        s = _State(skip_consistency=True)
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": []})
        s.touch("checkpoints/assemble/.done")
        st = s.state()
        self.assertEqual(st["tiers"]["consistency"]["total"], 0)
        self.assertEqual(st["step"], "mutators")

    def test_consistency_done_is_mutators(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": []})
        s.touch("checkpoints/assemble/.done")
        s.touch("checkpoints/consistency/.done")
        st = s.state()
        self.assertEqual(st["step"], "mutators")

    def test_mutators_done_finalize(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": []})
        s.touch("checkpoints/assemble/.done")
        s.touch("checkpoints/consistency/.done")
        s.write_json("default_mutators.json", {"source": "builtin-fallback",
                                               "mutators": ["MATH"], "parser_notes": []})
        st = s.state()
        self.assertEqual(st["step"], "done")
        self.assertIn("finalize", st["next_action"]["desc"])
        self.assertTrue(st["resumable"])

    def test_manifest_present_done_resumable_false(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("test_rules_inventory.json", {"repo": ".", "rules": []})
        s.touch("checkpoints/assemble/.done")
        s.touch("checkpoints/consistency/.done")
        s.write_json("default_mutators.json", {"source": "builtin-fallback",
                                               "mutators": ["MATH"], "parser_notes": []})
        s.write_json("ut_manifest.json", {"version": "0.1.19", "format": "opencode"})
        st = s.state()
        self.assertEqual(st["step"], "done")
        self.assertFalse(st["resumable"])

    def test_failed_unit_counted_tier_proceeds(self):
        s = _State()
        s.base_classify(n=2)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("checkpoints/extract/layer1.json.failed",
                     {"unit": "layer1", "reason": "parse error", "tier": "extract"})
        st = s.state()
        self.assertEqual(st["tiers"]["extract"], {"done": 1, "failed": 1, "total": 2})
        self.assertEqual(st["step"], "synthesize")

    def test_high_failure_advisory(self):
        s = _State()
        s.base_classify(n=2)
        for i in range(2):
            s.write_json(f"checkpoints/extract/layer{i}.json.failed",
                         {"unit": f"layer{i}", "reason": "boom", "tier": "extract"})
        st = s.state()
        self.assertIn("WARNING", " ".join(st["notes"]))
        self.assertEqual(st["step"], "synthesize")

    def test_step_graph_has_classify_no_codegraph(self):
        # ut step graph: classify prelude present, no codegraph-resolve step.
        s = _State()
        self.assertEqual(s.state()["step"], "classify")
        # no codegraph-resolve in the state machine: after classify -> extract directly.
        st = s.state()
        self.assertIn("classify", st["tiers"])
        self.assertNotIn("resolve", st["tiers"])

    def test_check_consistent_exit0(self):
        s = _State()
        s.base_classify(n=1)
        code, out, _ = s.main("--check")
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_check_inconsistent_extract_without_groups_exit2(self):
        s = _State()
        s.touch("checkpoints/extract/layer0.json.done")  # marker but no test_groups.json
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_check_both_done_and_failed_exit2(self):
        s = _State()
        s.base_classify(n=1)
        s.write_json("checkpoints/extract/layer0.json", {"unit": "layer0"})
        s.touch("checkpoints/extract/layer0.json.done")
        s.write_json("checkpoints/extract/layer0.json.failed",
                     {"unit": "layer0", "reason": "x", "tier": "extract"})
        code, out, _ = s.main("--check")
        self.assertEqual(code, 2)
        violations = json.loads(out)["violations"]
        self.assertTrue(any("ambiguous" in v["issue"] for v in violations))

    def test_run_root_explicit_default_byte_equivalent(self):
        # --target <t> ≡ --target <t> --run-root .mgh-ut-init (spec: byte-level identical).
        s = _State()
        c1, o1, _ = s.main_target()
        c2, o2, _ = s.main_target("--run-root", ".mgh-ut-init")
        self.assertEqual(c1, c2)
        self.assertEqual(o1, o2)                                # byte-identical stdout

    def test_run_root_named_dir_read(self):
        # --run-root <custom> reads <t>/<custom>; default --target misses it (exit 1).
        s = _State(run_root=".mgh-ut-custom")
        code, out, _ = s.main_target("--run-root", ".mgh-ut-custom")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["step"], "classify")   # only run_config present
        code2, _, _ = s.main_target()
        self.assertEqual(code2, 1)

    def test_resume_reads_back_sampling_budget(self):
        # F9: first run `--uniform-sample 8 --hetero-sample 16` -> interrupt (classify done,
        # extract pending) -> `--resume`: extract next_action carries the read-back budget,
        # state.sampling exposes it, user need NOT re-type sampling flags.
        s = _State(uniform_sample=8, hetero_sample=16)
        s.base_classify(n=2)                  # classify done; extract tier pending (0/2)
        st = s.state()
        self.assertEqual(st["step"], "extract")
        self.assertIn("--sample-uniform 8", st["next_action"]["desc"])
        self.assertIn("--sample-hetero 16", st["next_action"]["desc"])
        self.assertEqual(st["sampling"]["uniform_sample"], 8)
        self.assertEqual(st["sampling"]["hetero_sample"], 16)
        # subsplit_threshold not overridden -> default 0.8, still surfaced for transparency
        self.assertEqual(st["sampling"]["subsplit_threshold"], 0.8)

    def test_resume_degrades_when_run_config_lacks_sampling(self):
        # backward-compat: a legacy/partial run_config without a `sampling` block degrades
        # gracefully — no sample hint in extract next_action, state.sampling == {}; the
        # exit-code / step-graph contract is unchanged.
        s = _State()
        rc = s.init / "run_config.json"
        cfg = json.loads(rc.read_text(encoding="utf-8"))
        cfg.pop("sampling", None)
        rc.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        s.base_classify(n=1)
        st = s.state()
        self.assertEqual(st["step"], "extract")
        self.assertNotIn("--sample-uniform", st["next_action"]["desc"])
        self.assertEqual(st["sampling"], {})


def RS_main(init_dir):
    argv = ["resume_ut_init_state.py", "--init-dir", str(init_dir)]
    old, sys.argv = sys.argv, argv
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = RS.main()
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


if __name__ == "__main__":
    unittest.main(verbosity=2)
