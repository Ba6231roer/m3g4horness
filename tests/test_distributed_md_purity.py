#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_distributed_purity.py regression (R5.10 / R5.8).

Subprocess-runs the lint and asserts: (1) the real shipped set is clean
(CI gate — a leaked `R5.2` / `(D12)` MUST fail CI); (2) reverse cases — planting
each prohibited class into a fixture yields exit 2; (3) operational paths /
stage labels are NOT false positives (exit 0); (4) `--allowlist` suppresses a
known false positive; (5) the lint itself is zero-runtime-dep + `--help` works;
(6) the repo-root docs/ tree is developer-private and NEVER shippable — it is not
a scan root, no shipped file may point at it, and the two `docs/` families that
legitimately DO appear in shipped content (target-generated security-controls /
test-conventions dirs, and the core/docs/ Apache attribution namespace) must stay
clean; (7) the three scan surfaces dispatch to the right rule family, and the SDD
surface (openspec) skips archived changes + the docs-writing carve-out.
Run: py tests/test_distributed_md_purity.py
"""
import ast, importlib.util, json, re, subprocess, sys, tempfile, unittest
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


def load_lint_module():
    """Import the lint to assert on its constants (structural, not textual)."""
    spec = importlib.util.spec_from_file_location("_purity_under_test", LINT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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

    def test_sdr_callface_artifacts_scanned_and_clean(self):
        # The sdr shells gained wording about the codegraph carrier (run_config.json /
        # no_codegraph) and the in-domain recovery command; the dispatcher gained the
        # matching consumer. Both ship → both MUST stay free of dev-only provenance.
        root = HERE.parent
        files = [root / "releases" / "claude-code" / "commands" / "mgh-sdr.md",
                 root / "releases" / "opencode" / "command" / "mgh-sdr.md",
                 root / "core" / "scripts" / "fanout_runner.py"]
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    def test_ut_init_artifacts_scanned_and_clean(self):
        # ut-init shells + stage prompts + agent defs + contracts (task 9.3 / 10.6) MUST pass
        # distribution-purity (no dev-only provenance / dangling refs).
        root = HERE.parent
        files = ([root / "releases" / "claude-code" / "commands" / "mgh-ut-init.md",
                  root / "releases" / "opencode" / "command" / "mgh-ut-init.md"]
                 + [root / "core" / "prompts" / "stages" / f"ut-{s}.md"
                    for s in ("extract", "synthesize", "rulewriter", "rules-consistency")]
                 + [root / "releases" / "claude-code" / "agents" / f"ut-{s}.md"
                    for s in ("extract", "synthesize", "rulewriter", "rules-consistency")]
                 + [root / "releases" / "opencode" / "agent" / f"ut-{s}.md"
                    for s in ("extract", "synthesize", "rulewriter", "rules-consistency")]
                 + sorted((root / "core" / "contracts" / "ut-init").glob("*.md")))
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    # --- repo-root docs/ is the maintainer's private workspace -----------------
    # install.sh does NOT copy it into a target project, so every pointer to it
    # from shipped content is a dead link there. This guard REPLACED the older
    # add-plain-language-doctrine guard, which asserted the opposite (man pages
    # must ship; every command shell must carry a `docs/man/<cmd>.md` pointer).
    # Direction inverted on purpose — do not "restore" the old assertions.
    def test_repo_root_docs_is_not_a_scan_root(self):
        mod = load_lint_module()
        roots = [str(p).replace("\\", "/")
                 for p in list(mod.SCAN_DIRS) + list(mod.SCAN_SCRIPT_DIRS)]
        offenders = [p for p in roots if "/docs/" in p or p.endswith("/docs")]
        self.assertFalse(offenders,
                         f"repo-root docs/ must never be a scan root: {offenders}")

    def test_no_shipped_file_points_at_repo_root_docs(self):
        root = HERE.parent
        shells = (sorted((root / "releases" / "claude-code" / "commands").glob("mgh-*.md"))
                  + sorted((root / "releases" / "opencode" / "command").glob("mgh-*.md")))
        self.assertTrue(shells, "no command shells found")
        for s in shells:
            body = s.read_text(encoding="utf-8")
            self.assertNotIn("docs/man", body,
                             f"{s} points at the developer-private docs/man tree")
            self.assertNotIn("人类读者", body,
                             f"{s} still carries a human-reader pointer to a page "
                             f"that is not installed into target projects")
        r = run_lint("--files", *[str(s) for s in shells])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["violations"], [])

    def test_catches_repo_root_docs_reference(self):
        d = self._assert_caught("walkthrough: docs/man/mgh-init.md\n")
        self.assertIn("repo_docs", {h["pattern"] for h in d["violations"][0]["hits"]})

    def test_catches_repo_root_docs_paths(self):
        for body in ("plain-language glossary: docs/glossary.md\n",
                     "sync anchor: docs/upstream-index.md\n",
                     "per-stage notes live in docs/upstream/01-stages-prompts.md\n"):
            with self.subTest(body=body):
                d = self._assert_caught(body)
                self.assertIn("repo_docs",
                              {h["pattern"] for h in d["violations"][0]["hits"]})

    def test_preserves_target_generated_and_attribution_docs_paths(self):
        # Three families share the `docs/` prefix and must NOT be conflated:
        # the tooling's runtime outputs inside the TARGET project, and the
        # core/docs/ Apache-2.0 attribution records.
        body = ("detail files -> <target>/docs/security-controls/<cat>.md\n"
                "conventions  -> <target>/docs/test-conventions/<cat>.md\n"
                "see core/docs/NOTICE and core/docs/prompt-provenance.md\n"
                "upstream ref: code.claude.com/docs/en/memory.md\n"
                "upstream ref: opencode.ai/docs/rules\n")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["violations"], [])

    def test_verbatim_prompt_prose_is_exempt(self):
        # core/prompts/** is an R1-frozen verbatim port: its body is the upstream
        # authors' prose and mentions the UPSTREAM project's own doc layout
        # ("docs/manifests/tree", "docs/config/non-code files"). Left in scope it
        # would be an unfixable failure, so pattern 9 is skipped there.
        root = HERE.parent / "core" / "prompts"
        for f in (root / "stages" / "s2-threat-model.md",
                  root / "stages" / "s4-quality-bar.md",
                  root / "stages" / "s4-system.md"):
            self.assertTrue(f.is_file(), f"{f} missing")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_shipped_scripts_scanned_for_pointers_not_dev_vocab(self):
        # Scripts ship, but the host agent is required NOT to read their source
        # (errors go to stderr), so pointer-class refs are flagged there while
        # dev-manual vocabulary in comments stays legitimate shorthand.
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            ptr = d / "a.py"
            ptr.write_text("# see docs/man/mgh-init.md\n", encoding="utf-8")
            self.assertEqual(run_lint("--files", str(ptr)).returncode, 2)

            upstream = d / "b.py"
            upstream.write_text("# idea from glasswing_docs/09\n", encoding="utf-8")
            self.assertEqual(run_lint("--files", str(upstream)).returncode, 2)

            vocab = d / "c.py"
            vocab.write_text("# fail-loud per R5.9 (D4, FD3)\n", encoding="utf-8")
            self.assertEqual(run_lint("--files", str(vocab)).returncode, 0)

            vocab_md = d / "c.md"
            vocab_md.write_text("fail-loud per R5.9\n", encoding="utf-8")
            self.assertEqual(run_lint("--files", str(vocab_md)).returncode, 2)

    # --- R5.11: SDD artifacts must not point at the private docs/ area ---------
    def test_scan_mode_classifies_the_three_surfaces(self):
        mod = load_lint_module()
        root = HERE.parent
        self.assertEqual(mod.scan_mode(
            root / "openspec" / "specs" / "distribution-purity" / "spec.md"), "sdd")
        self.assertEqual(mod.scan_mode(
            root / "openspec" / "changes" / "add-mgh-ut" / "proposal.md"), "sdd")
        self.assertEqual(mod.scan_mode(
            root / "releases" / "opencode" / "command" / "mgh-sra.md"), "md")
        self.assertEqual(mod.scan_mode(
            root / "core" / "scripts" / "discover_controls.py"), "script")

    def test_sdd_scope_skips_archive_and_the_docs_writing_change(self):
        mod = load_lint_module()
        root = HERE.parent
        self.assertEqual({p.as_posix() for p in mod.SDD_SCAN_DIRS},
                         {(root / "openspec" / "specs").as_posix(),
                          (root / "openspec" / "changes").as_posix()})
        self.assertIn("archive", mod.SDD_SKIP_PARTS)
        changes = root / "openspec" / "changes"
        archived = next((changes / "archive").glob("*/proposal.md"))
        self.assertTrue(archived.is_file(), f"{archived} missing")
        self.assertFalse(mod._sdd_kept(archived))          # frozen history
        exempt = changes / "add-skill-dev-experience-doc" / "proposal.md"
        self.assertTrue(exempt.is_file(), f"{exempt} missing")
        self.assertFalse(mod._sdd_kept(exempt))            # the carve-out
        self.assertTrue(mod._sdd_kept(changes / "add-mgh-ut" / "proposal.md"))
        self.assertTrue(mod._sdd_kept(
            root / "openspec" / "specs" / "distribution-purity" / "spec.md"))

    def test_repo_docs_hits_flags_pointers_and_spares_everything_else(self):
        mod = load_lint_module()
        for body in ("见 docs/man/mgh-init.md",
                     "背景见 docs/opencode-context-mechanics.md",
                     "见 docs/glossary.md",
                     "见 docs/upstream-index.md"):
            with self.subTest(body=body):
                self.assertTrue(mod.repo_docs_hits(body), body)
        for body in ("写 <target>/docs/security-controls/a.md",
                     "写 <target>/docs/test-conventions/a.md",
                     "见 core/docs/NOTICE 与 core/docs/prompt-provenance.md",
                     "概念 (glasswing_docs/09 §1.1)",          # tail of a longer word
                     "ref: code.claude.com/docs/en/memory.md",  # upstream URL
                     "ref: opencode.ai/docs/rules",
                     "本仓根 `docs/` 指针",                     # bare dir, no entry
                     "用户手写的 <target>/docs/ 内容"):
            with self.subTest(body=body):
                self.assertFalse(mod.repo_docs_hits(body), body)

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


class TestSourceTreePathPrefix(unittest.TestCase):
    """Class 10 (fix-mgh-init-distribution-links): `core/(prompts|contracts|scripts)/…`
    spellings in shipped md are dangling pointers — the content ships as `<host>/mgh-core/`,
    and no target project has `<target>/core/`. Legal forms: install-layout paths
    (`mgh-core/…`, `.claude/mgh-core/…`) or sibling-relative wording inside stage prompts.
    md-only (script comments stay legitimate maintenance shorthand); core/prompts/** gets
    NO verbatim-prose exemption for this class (the spelling is unreachable everywhere).
    """

    def test_catches_core_prefix_references(self):
        for body in ("遵循 `core/prompts/fragments/codegraph-hint.md`\n",
                     "见 `core/contracts/init/unit-inputs.md`\n",
                     "wrapper at `core/contracts/init/clusters.md`\n",
                     "run `core/scripts/list_clusters.py`\n"):
            with self.subTest(body=body):
                d = self._assert_caught(body)
                self.assertIn("source_tree_path",
                              {h["pattern"] for h in d["violations"][0]["hits"]})

    def test_install_layout_and_sibling_forms_not_flagged(self):
        body = ("assets at `.claude/mgh-core/prompts/fragments/codegraph-hint.md`\n"
                "dsh root: `mgh-core/contracts/init/unit-inputs.md`\n"
                "opencode: `.opencode/mgh-core/scripts/list_clusters.py`\n"
                "sibling: the fragments/ dir next to this stages/ dir holds "
                "`codegraph-hint.md`\n")
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["violations"], [])

    def test_md_only_script_comments_exempt(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "a.py"
            f.write_text("# see core/scripts/foo.py for the sibling\n", encoding="utf-8")
            self.assertEqual(run_lint("--files", str(f)).returncode, 0)

    def test_init_slice_source_tree_refs_fixed(self):
        # The init-slice hits this batch fixes MUST be clean (removed from the
        # baseline): 6 stage prompts' codegraph-hint refs + rules-format refs
        # (1 stage + 3 per-host agents) + the three init shells' Output section.
        root = HERE.parent
        files = ([root / "core" / "prompts" / "stages" / f"init-{s}.md"
                  for s in ("scout", "induct", "survey", "resolve", "rulewriter")]
                 + [root / "core" / "prompts" / "stages" / f"sra-{s}.md"
                    for s in ("clarify", "augment")]
                 + [root / "core" / "prompts" / "fragments" / "codegraph-hint.md"]
                 + [root / "releases" / "claude-code" / "agents" / "init-rulewriter.md"]
                 + [root / "releases" / "opencode" / "agent" / n
                    for n in ("init-rulewriter.md", "init-rulewriter-fanout.md")]
                 + [root / "releases" / "claude-code" / "commands" / "mgh-init.md",
                    root / "releases" / "opencode" / "command" / "mgh-init.md",
                    root / "releases" / "dsh" / "skills" / "mgh-init" / "SKILL.md"])
        for f in files:
            self.assertTrue(f.is_file(), f"{f} missing")
        r = run_lint("--files", *[str(f) for f in files])
        self.assertEqual(r.returncode, 0,
                         f"init slice still carries source-tree path refs:\n{r.stderr}")

    # --- baseline allowlist pins legacy class-10 hits without admitting new ones ---
    def test_baseline_pins_legacy_hits_and_only_shrinks(self):
        mod = load_lint_module()
        baseline = mod.DEFAULT_ALLOWLIST
        self.assertTrue(baseline.is_file(), f"missing baseline file: {baseline}")
        entries = [ln.strip() for ln in baseline.read_text(encoding="utf-8").splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
        self.assertTrue(entries, "baseline file has no active entries")
        # every pinned entry must still be a live hit (stale pins = the baseline is
        # hiding a fixed line, i.e. it can grow back); full lint MUST exit 0.
        r = run_lint()
        self.assertEqual(r.returncode, 0, f"baseline misses a violation:\n{r.stderr}")
        d = json.loads(r.stdout)
        self.assertEqual(d["allowlisted"], len(entries),
                         "baseline has stale entries (fixed lines still pinned) — "
                         "remove them; the baseline only shrinks")
        # 基线只减不增: pin the count; a batch that fixes hits lowers this number.
        self.assertLessEqual(len(entries), BASELINE_MAX_ENTRIES,
                             "baseline grew past the pinned maximum — new class-10 "
                             "references are NOT allowed; fix the reference instead")

    def test_new_source_tree_hit_is_red_even_with_baseline(self):
        # a fresh `core/...` reference on a NOT-pinned line must fail the lint even
        # though the baseline pins legacy hits.
        mod = load_lint_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            f = root / "f.md"
            f.write_text("see `core/prompts/fragments/new-thing.md`\n", encoding="utf-8")
            r = run_lint("--files", str(f), "--allowlist", str(mod.DEFAULT_ALLOWLIST))
            self.assertEqual(r.returncode, 2,
                             "new class-10 hit escaped the baseline (suppressed by mistake)")

    # --- fragment header must not claim a loading mechanism that does not exist ---
    def test_codegraph_hint_header_states_real_loading(self):
        # fix-mgh-init-distribution-links 1.2: the fragment is Read by the stage agent
        # when the task signals codegraph=on; no inlining mechanism exists anywhere in
        # the chain, and a false "Inlined …" claim makes a weak model trust a load
        # path that never happens (same family as a dead link).
        f = HERE.parent / "core" / "prompts" / "fragments" / "codegraph-hint.md"
        self.assertTrue(f.is_file(), f"{f} missing")
        header = f.read_text(encoding="utf-8").split("-->", 1)[0]
        self.assertNotIn("Inlined", header,
                         "codegraph-hint.md header claims an inlining mechanism that "
                         "does not exist — restate the real loading (Read on signal)")

    def _assert_caught(self, body):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "f.md"
            f.write_text(body, encoding="utf-8")
            r = run_lint("--files", str(f))
            self.assertEqual(r.returncode, 2, f"expected violation for: {body!r}")
            d = json.loads(r.stdout)
            self.assertEqual(len(d["violations"]), 1)
            return d


# 基线只减不增 (design D10): the class-10 legacy baseline after this batch's init-slice
# fix. Lower this constant when a later batch fixes more hits; NEVER raise it.
BASELINE_MAX_ENTRIES = 200


class TestDistributionCompleteness(unittest.TestCase):
    """fix-mgh-init-distribution-links 1.4: every agent definition an init shell's
    subagent inventory names MUST exist in that platform's release set — a named-but-
    missing file is a dangling spawn instruction (claude face lacked
    init-scout-merge-rollup). dsh is out of scope: its agents are tier-named
    (scout.md/t1.md/…) by design, so the 1:1 name check only applies to
    claude + opencode."""

    FACES = {
        "claude": (HERE.parent / "releases" / "claude-code" / "commands" / "mgh-init.md",
                   HERE.parent / "releases" / "claude-code" / "agents"),
        "opencode": (HERE.parent / "releases" / "opencode" / "command" / "mgh-init.md",
                     HERE.parent / "releases" / "opencode" / "agent"),
    }
    AGENT_NAME_RX = re.compile(r"`(init-[a-z0-9-]+)`")

    def _inventory_line(self, shell: Path) -> str:
        for line in shell.read_text(encoding="utf-8").splitlines():
            if "`init-survey`" in line and "`init-scout`" in line:
                return line
        self.fail(f"subagent inventory line not found in {shell}")

    def test_inventory_named_agents_exist(self):
        for platform, (shell, agent_dir) in self.FACES.items():
            with self.subTest(platform=platform):
                names = set(self.AGENT_NAME_RX.findall(self._inventory_line(shell)))
                self.assertTrue(names, f"{platform}: no agent names parsed")
                missing = sorted(n for n in names
                                 if not (agent_dir / f"{n}.md").is_file())
                self.assertFalse(
                    missing,
                    f"{platform}: shell inventory names missing agent files "
                    f"{missing} (install self-check warns; CI fails here)")

    def test_dsh_inventory_out_of_scope_documented(self):
        # guard against someone "fixing" the dsh face by renaming its tier-named
        # agents: the dsh init shell names stages, not agent files, by design.
        dsh_shell = (HERE.parent / "releases" / "dsh" / "skills" / "mgh-init"
                     / "SKILL.md")
        self.assertTrue(dsh_shell.is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
