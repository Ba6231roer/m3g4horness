#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for write_runconfig.py — atomic run_config.json start-state intent writer.

Asserts: atomic write of <target>/.mgh-init/run_config.json; target recorded ABSOLUTE;
--no-scout / skip_consistency recorded (--merge refused, no mode field); --target required (exit 2); --format
defaults to opencode (omitted -> exit 0); stdout ack shape. Run from a non-script cwd
(import robustness).
"""
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


WC = _load("write_runconfig")


def _run(*argv):
    old, sys.argv = sys.argv, ["write_runconfig.py"] + list(argv)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = WC.main()
    except SystemExit as e:           # argparse misuse (missing required / bad choice) -> exit 2
        code = int(e.code) if isinstance(e.code, int) else 2
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


class TestWriteRunconfig(unittest.TestCase):
    def test_writes_run_config_with_absolute_target(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_")).resolve()
        code, out, _ = _run("--target", str(target), "--format", "opencode", "--no-scout")
        self.assertEqual(code, 0)
        rc_path = target / ".mgh-init" / "run_config.json"
        self.assertTrue(rc_path.is_file())
        cfg = json.loads(rc_path.read_text(encoding="utf-8"))
        self.assertEqual(cfg["target"], str(target))           # ABSOLUTE
        self.assertTrue(Path(cfg["target"]).is_absolute())
        self.assertEqual(cfg["format"], "opencode")
        self.assertTrue(cfg["no_scout"])
        ack = json.loads(out)
        self.assertEqual(ack["run_config"], str(rc_path.resolve()))

    def test_merge_refused_exit2(self):
        # H11(b): --merge has NO deterministic implementation — refused at step 0
        # with a recipe, NEVER a silent mode=merge run_config.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc2_")).resolve()
        code, out, err = _run("--target", str(target), "--format", "claude",
                              "--merge", "/tmp/p")
        self.assertEqual(code, 2)
        self.assertIn("merge", (err + out).lower())
        self.assertFalse((target / ".mgh-init" / "run_config.json").exists())

    def test_payload_records_no_merge_fields(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc2b_")).resolve()
        code, _, _ = _run("--target", str(target), "--no-scout")
        self.assertEqual(code, 0)
        cfg = json.loads((target / ".mgh-init" / "run_config.json")
                         .read_text(encoding="utf-8"))
        for k in ("mode", "merge", "merge_partials_dir"):
            self.assertNotIn(k, cfg)

    def test_atomic_no_tmp_left(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc3_")).resolve()
        _run("--target", str(target), "--format", "opencode")
        rc_dir = target / ".mgh-init"
        self.assertFalse(any(p.suffix == ".tmp" for p in rc_dir.glob("*.tmp")))

    def test_missing_required_exit2(self):
        code, _, _ = _run("--format", "opencode")  # no --target
        self.assertEqual(code, 2)

    def test_format_defaults_opencode(self):
        # Omitting --format (no --target conflict) -> exit 0 + format == "opencode".
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_fmt_")).resolve()
        code, out, _ = _run("--target", str(target))
        self.assertEqual(code, 0)
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["format"], "opencode")
        self.assertEqual(json.loads(out)["format"], "opencode")

    def test_bad_budget_exit2(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc4_")).resolve()
        code, _, _ = _run("--target", str(target), "--format", "opencode", "--max-unit-bytes", "-5")
        self.assertEqual(code, 2)

    def test_skip_consistency_recorded(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc5_")).resolve()
        _run("--target", str(target), "--format", "opencode", "--skip-consistency")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["skip_consistency"])

    def test_include_tests_recorded(self):
        # --include-tests → run_config["include_tests"] == True (mirrors include_dotfiles).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc6_")).resolve()
        _run("--target", str(target), "--format", "opencode", "--include-tests")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertTrue(cfg["include_tests"])

    def test_include_tests_default_false(self):
        # Default (flag absent) → include_tests == False (mgh-init excludes test sources).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc7_")).resolve()
        _run("--target", str(target), "--format", "opencode")
        cfg = json.loads((target / ".mgh-init" / "run_config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["include_tests"])


    def test_run_root_default_writes_mgh_init(self):
        # default (no --run-root) -> <target>/.mgh-init/run_config.json (old behavior).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_rr1_")).resolve()
        code, _, _ = _run("--target", str(target), "--format", "opencode")
        self.assertEqual(code, 0)
        self.assertTrue((target / ".mgh-init" / "run_config.json").is_file())

    def test_run_root_named_dir(self):
        # --run-root .mgh-ut-init -> <target>/.mgh-ut-init/run_config.json.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_rr2_")).resolve()
        code, out, _ = _run("--target", str(target), "--format", "opencode",
                            "--run-root", ".mgh-ut-init")
        self.assertEqual(code, 0)
        rc = target / ".mgh-ut-init" / "run_config.json"
        self.assertTrue(rc.is_file())
        self.assertEqual(json.loads(out)["run_config"], str(rc.resolve()))

    def test_init_dir_overrides_run_root(self):
        # --init-dir wins over --run-root; run_config lands in --init-dir, NOT --run-root.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_rr3_")).resolve()
        custom = target / "custom"
        code, out, _ = _run("--target", str(target), "--format", "opencode",
                            "--run-root", ".mgh-ut-init", "--init-dir", str(custom))
        self.assertEqual(code, 0)
        self.assertTrue((custom / "run_config.json").is_file())
        self.assertFalse((target / ".mgh-ut-init" / "run_config.json").is_file())

    def test_run_root_explicit_default_byte_equivalent(self):
        # no --run-root ≡ --run-root .mgh-init (spec: default is byte-equivalent).
        t1 = Path(tempfile.mkdtemp(prefix="mgh_wc_rr4_")).resolve()
        t2 = Path(tempfile.mkdtemp(prefix="mgh_wc_rr5_")).resolve()
        _, o1, _ = _run("--target", str(t1), "--format", "opencode")
        _, o2, _ = _run("--target", str(t2), "--format", "opencode", "--run-root", ".mgh-init")
        a1, a2 = json.loads(o1), json.loads(o2)
        # identical schema/flags; run_config/target differ only by the temp dir.
        for k in ("format", "no_scout", "no_codegraph", "skip_consistency"):
            self.assertEqual(a1[k], a2[k])
        self.assertEqual(Path(a1["run_config"]), (t1 / ".mgh-init" / "run_config.json").resolve())
        self.assertEqual(Path(a2["run_config"]), (t2 / ".mgh-init" / "run_config.json").resolve())

    # ---- sentinel co-write (deterministic side-effect) ----

    def test_sentinel_cowritten_with_fields(self):
        # run_config write ALSO writes <init-dir>/.active with domain/target/out_roots/v.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_sent1_")).resolve()
        code, out, _ = _run("--target", str(target), "--format", "opencode")
        self.assertEqual(code, 0)
        sp = target / ".mgh-init" / ".active"
        self.assertTrue(sp.is_file(), "sentinel .active must co-exist after write_runconfig")
        sent = json.loads(sp.read_text(encoding="utf-8"))
        self.assertEqual(sent["domain"], "mgh-init")
        self.assertEqual(sent["target"], str(target))          # Windows-native abs target
        self.assertEqual(sent["out_roots"], [])                # default roots NOT listed
        self.assertEqual(sent["v"], 1)
        self.assertEqual(json.loads(out)["sentinel"], str(sp.resolve()))

    def test_sentinel_default_roots_not_listed(self):
        # default product roots are built into the guard allowlist — out_roots stays empty
        # unless --out/--rules-dir deviate from the defaults.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_sent2_")).resolve()
        _run("--target", str(target), "--format", "claude",
             "--rules-dir", str(target / "docs" / "security-controls"))  # = claude default? no:
        # docs/security-controls IS the opencode default rules dir; passing it explicitly is
        # byte-equal to the default → still not listed.
        sent = json.loads((target / ".mgh-init" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sent["out_roots"], [])

    def test_sentinel_custom_out_and_rules_dir_listed(self):
        # non-default --out (custom run_config path → its parent dir) and --rules-dir are
        # listed as abs roots so the guard's allowlist extends to them.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_sent3_")).resolve()
        custom_out = target / "custom-run" / "run_config.json"
        custom_rules = target / "custom-rules"
        code, out, _ = _run("--target", str(target), "--format", "opencode",
                            "--out", str(custom_out), "--rules-dir", str(custom_rules))
        self.assertEqual(code, 0)
        sent = json.loads((target / ".mgh-init" / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sent["out_roots"],
                         [str(custom_out.resolve().parent), str(custom_rules.resolve())])
        self.assertTrue(all(Path(r).is_absolute() for r in sent["out_roots"]))

    def test_sentinel_idempotent_rewrite(self):
        # second invocation overwrites cleanly (no .tmp residue, no duplicate roots, same v).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_sent4_")).resolve()
        _run("--target", str(target), "--format", "opencode")
        _run("--target", str(target), "--format", "opencode")
        init = target / ".mgh-init"
        sent = json.loads((init / ".active").read_text(encoding="utf-8"))
        self.assertEqual(sent["v"], 1)
        self.assertFalse(any(p.name.endswith(".tmp") for p in init.iterdir()),
                         [p.name for p in init.iterdir()])

    def test_sentinel_domain_follows_run_root(self):
        # --run-root .mgh-ut-init → domain "mgh-ut-init" + sentinel inside .mgh-ut-init.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_sent5_")).resolve()
        _run("--target", str(target), "--format", "opencode", "--run-root", ".mgh-ut-init")
        sp = target / ".mgh-ut-init" / ".active"
        self.assertTrue(sp.is_file())
        self.assertEqual(json.loads(sp.read_text(encoding="utf-8"))["domain"], "mgh-ut-init")

    # ---- run-dir gitignore co-write (fix-mgh-init-distribution-links 1.6 / D5) ----

    def test_gitignore_cowritten_on_fresh_bootstrap(self):
        # step 0 lands <run-root>/.gitignore (body `*`) so checkpoints/inputs stay out
        # of the target project's git (the shells/contracts promise this; the script
        # side effect is the single deterministic writer).
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_git1_")).resolve()
        code, _, _ = _run("--target", str(target), "--format", "opencode")
        self.assertEqual(code, 0)
        gi = target / ".mgh-init" / ".gitignore"
        self.assertTrue(gi.is_file(), "run-dir .gitignore must co-exist after step 0")
        self.assertEqual(gi.read_text(encoding="utf-8"), "*\n")

    def test_gitignore_idempotent_never_clobbers(self):
        # an existing run-dir .gitignore (user-tuned) is NEVER rewritten or appended.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_git2_")).resolve()
        init = target / ".mgh-init"
        init.mkdir(parents=True)
        custom = "# keep my extra rules\n*.custom\n"
        (init / ".gitignore").write_text(custom, encoding="utf-8")
        code, _, _ = _run("--target", str(target), "--format", "opencode")
        self.assertEqual(code, 0)
        self.assertEqual((init / ".gitignore").read_text(encoding="utf-8"), custom)

    def test_target_root_gitignore_untouched(self):
        # co-write lands INSIDE the run dir only; the target's own .gitignore is zero-touch.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_git3_")).resolve()
        root_gi = target / ".gitignore"
        root_gi.write_text("node_modules/\n", encoding="utf-8")
        _run("--target", str(target), "--format", "opencode")
        self.assertEqual(root_gi.read_text(encoding="utf-8"), "node_modules/\n")
        self.assertEqual((target / ".mgh-init" / ".gitignore").read_text(encoding="utf-8"),
                         "*\n")

    def test_gitignore_follows_init_dir_override(self):
        # --init-dir wins: the .gitignore lands beside the run_config it protects.
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_git4_")).resolve()
        custom = target / "custom"
        code, _, _ = _run("--target", str(target), "--format", "opencode",
                          "--init-dir", str(custom))
        self.assertEqual(code, 0)
        self.assertTrue((custom / ".gitignore").is_file())
        self.assertFalse((target / ".mgh-init" / ".gitignore").exists())


class TestFsyncDurability(unittest.TestCase):
    """M6: the crash-recovery anchor's atomic write MUST fsync content before
    os.replace — replace's atomicity alone does not flush CONTENT (a power cut
    can land a zero-length run_config after a "successful" replace)."""

    def test_all_three_writes_fsync_before_replace(self):
        from unittest import mock
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_f_")).resolve()
        events = []
        real_fsync, real_replace = os.fsync, os.replace
        with mock.patch("os.fsync", side_effect=lambda fd: (events.append("fsync"),
                                                            real_fsync(fd))[-1]),              mock.patch("os.replace", side_effect=lambda s, d: (events.append("replace"),
                                                                real_replace(s, d))[-1]):
            code, _, _ = _run("--target", str(target))
        self.assertEqual(code, 0)
        # run_config + sentinel + gitignore: every replace preceded by a fsync
        self.assertGreaterEqual(events.count("fsync"), 3)
        self.assertLess(events.index("fsync"), events.index("replace"))

    def test_no_tmp_residue_after_success(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_t_")).resolve()
        code, _, _ = _run("--target", str(target))
        self.assertEqual(code, 0)
        self.assertEqual(list((target / ".mgh-init").glob("*.tmp")), [])


class TestSentinelDomainLocationInvariant(unittest.TestCase):
    """M6: a sentinel written INTO a canonically-named run dir must carry that
    dir's domain — a mismatched explicit combo activates the wrong domain's
    trusted subtrees at that location. Custom-named --init-dir keeps the
    documented "--init-dir wins" override semantics."""

    def test_canonical_mismatch_exit_2(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_i_")).resolve()
        code, _, err = _run("--target", str(target), "--init-dir",
                            str(target / ".mgh-init"), "--run-root", ".mgh-ut-init")
        self.assertEqual(code, 2)
        self.assertIn("--run-root", err)
        self.assertFalse((target / ".mgh-init" / ".active").exists())

    def test_canonical_match_passes(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_m_")).resolve()
        code, _, _ = _run("--target", str(target), "--init-dir",
                          str(target / ".mgh-ut-init"), "--run-root", ".mgh-ut-init")
        self.assertEqual(code, 0)
        sent = json.loads((target / ".mgh-ut-init" / ".active")
                          .read_text(encoding="utf-8"))
        self.assertEqual(sent["domain"], "mgh-ut-init")

    def test_default_combo_unchanged(self):
        target = Path(tempfile.mkdtemp(prefix="mgh_wc_d_")).resolve()
        code, _, _ = _run("--target", str(target))
        self.assertEqual(code, 0)
        sent = json.loads((target / ".mgh-init" / ".active")
                          .read_text(encoding="utf-8"))
        self.assertEqual(sent["domain"], "mgh-init")


if __name__ == "__main__":
    unittest.main()
