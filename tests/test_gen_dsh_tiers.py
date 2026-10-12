#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""gen_dsh_tiers.py — dsh tier mount generator assertions (add-mgh-dsh-subagent-fanout
task 2.3).

Asserts the three-way contract between `releases/dsh/agents/` definitions, the
fanout_runner closed tier set, and the generated mounting artifacts:
(1) every fanout_runner tier compiles to a mount with the spike-locked shape
    (env task channel / embedded persona / run-in-background off / coarse
    whole-plugin whitelist), (2) named delegation instances compile to
    `- insert:` rows with per-instance toolName + toolFilter, (3) the generator
    is idempotent and `--check` fails loud on drift/missing artifacts, (4)
    broken definitions (missing tier, dangling prompt path, bad tool_name) fail
    loud at compile time, never ship half-wired, (5) the generator itself is
    stdlib-only (zero-runtime-deps product property extends to install-time
    tools that run in the user's environment).
Run: py tests/test_gen_dsh_tiers.py
"""
import ast, importlib.util, io, json, contextlib, shutil, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
AGENTS = ROOT / "releases" / "dsh" / "agents"


def _load():
    spec = importlib.util.spec_from_file_location("gen_dsh_tiers", TOOLS / "gen_dsh_tiers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, argv):
    """Run the generator CLI in-process; returns (exit_code, stdout_json, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["gen_dsh_tiers.py"] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = mod.main()
            except SystemExit as e:
                rc = e.code
    finally:
        sys.argv = old
    text = out.getvalue().strip()
    return rc, (json.loads(text) if text else None), err.getvalue()


class _Generated(unittest.TestCase):
    """Shared fixture: full generation once per class into a scratch dir."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.d = Path(tempfile.mkdtemp(prefix="mgh_tiers_"))
        cls.out = cls.d / "tiers"
        cls.deg = cls.d / "delegates.patch.yml"
        rc, stdout, err = _run(cls.mod, ["--agents", str(AGENTS), "--out", str(cls.out),
                                         "--delegates-out", str(cls.deg)])
        assert rc == 0, err
        cls.stdout = stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _mount(self, tier):
        return (self.out / f"{tier}.yml").read_text(encoding="utf-8")


class TestMountShape(_Generated):
    def test_tier_set_matches_fanout_runner(self):
        sys.path.insert(0, str(ROOT / "core" / "scripts"))
        try:
            import fanout_runner
            tiers = set(fanout_runner.TIERS)
        finally:
            sys.path.pop(0)
        self.assertEqual(tiers, set(self.stdout["tiers"]))
        self.assertEqual(set(tiers), set(self.mod.REQUIRED_TIERS))

    def test_env_task_channel_present(self):
        for tier in self.stdout["tiers"]:
            m = self._mount(tier)
            self.assertIn("task: !!js process.env.MGH_TASK_TEXT", m, tier)
            self.assertIn("name: '@deepseek-ai/dsh-headless'", m, tier)
            self.assertIn("inject: [headlessStartup]", m, tier)

    def test_persona_embeds_leaf_prompt(self):
        # the scout persona must carry the leaf stage prompt VERBATIM (definitions
        # reference by path; the generator embeds — no second copy in the repo)
        leaf = (ROOT / "core" / "prompts" / "stages" / "init-scout.md").read_text(encoding="utf-8")
        m = self._mount("scout")
        persona_line = next(ln for ln in m.splitlines() if "personaPrefix:" in ln)
        persona = json.loads(persona_line.split("personaPrefix:", 1)[1].strip())
        self.assertIn(leaf.strip(), persona)
        self.assertIn("S3 — scout-reader", persona)

    def test_run_in_background_closed_on_both_shell_faces(self):
        for tier in self.stdout["tiers"]:
            m = self._mount(tier)
            for tool in ("tool-bash", "tool-pwsh"):
                block = m.split(f"- id: {tool}\n", 1)[1].split("\n- id:", 1)[0]
                self.assertIn("enableRunInBackground: false", block, f"{tier}/{tool}")

    def test_whitelist_keeps_and_disables(self):
        m = self._mount("t1")
        lines = m.splitlines()
        disabled = {lines[i][len("- id: "):] for i, ln in enumerate(lines)
                    if ln.startswith("- id: ") and i + 1 < len(lines)
                    and lines[i + 1] == "  disabled: true"}
        # kept plugins carry no disabled row (absent = host default enabled);
        # everything else in the base tool surface is switched off whole-plugin.
        for keep in ("tool-fs", "tool-fs-search", "tool-bash", "tool-pwsh"):
            self.assertNotIn(keep, disabled)
        for deny in ("tool-web", "tool-jobs", "tool-subagent", "tool-subagent-control",
                     "tool-ask-user", "tool-goal", "tool-skill", "tool-workflow",
                     "tool-todo", "tool-present", "tool-ralph"):
            self.assertIn(deny, disabled)

    def test_sdr_mount_is_self_contained_persona(self):
        # sdr has no leaf stage prompt (behavior rides definition + task template)
        m = self._mount("sdr")
        self.assertIn("SDR design-compliance reviewer", m)


class TestDelegatesShape(_Generated):
    def _rows(self):
        rows, cur = [], None
        for ln in self.deg_lines:
            if ln.startswith("- insert:"):
                cur = []
                rows.append(cur)
            elif cur is not None:
                cur.append(ln)
        return rows

    def setUp(self):
        self.deg_lines = self.deg.read_text(encoding="utf-8").splitlines()

    def test_all_eleven_stage_instances_present(self):
        names = [self.stdout["delegates"]]
        want = {"mgh_sast_survey", "mgh_sast_threat_model", "mgh_sast_decompose",
                "mgh_sast_deepdive", "mgh_sast_verify", "mgh_sast_chain",
                "mgh_sast_triage", "mgh_sast_scope_resolver",
                "mgh_sra_clarify", "mgh_sra_augment", "mgh_sra_consistency"}
        self.assertEqual(want, set(names[0]))

    def test_row_shape(self):
        for row in self._rows():
            body = "\n".join(row)
            self.assertIn("name: '@deepseek-ai/dsh-tool-subagent'", body)
            self.assertIn("provider: spawn", body)
            self.assertIn("toolName: mgh_", body)
            self.assertIn("toolFilter:", body)
            self.assertRegex(body, r"persona: \"")

    def test_id_matches_tool_name(self):
        text = self.deg.read_text(encoding="utf-8")
        for tn in self.stdout["delegates"]:
            self.assertIn(f"- id: {tn.replace('_', '-')}", text, tn)
        self.assertNotIn("mgh-mgh-", text)


class TestFailLoud(unittest.TestCase):
    def setUp(self):
        self.mod = _load()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_tiers_fl_"))
        self.agents = self.d / "agents"
        self.agents.mkdir()
        # minimal valid fanout tier + delegate fixtures
        (self.agents / "scout.md").write_text(
            "---\nkind: fanout\nprompt: core/prompts/stages/init-scout.md\n"
            "description: x\n---\nbody\n", encoding="utf-8")
        for t in ("t1", "t2", "t3", "scout-merge"):
            (self.agents / f"{t}.md").write_text(
                f"---\nkind: fanout\nprompt: core/prompts/stages/init-scout.md\n"
                f"description: x\n---\nbody {t}\n", encoding="utf-8")
        (self.agents / "sdr.md").write_text(
            "---\nkind: fanout\nprompt: none\ndescription: x\n---\nbody sdr\n",
            encoding="utf-8")
        (self.agents / "sast-survey.md").write_text(
            "---\nkind: delegate\ntool_name: mgh_sast_survey\nprompt: none\n"
            "tool_filter: [read, grep]\ndescription: x\n---\nsv\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def _gen(self, extra=()):
        return _run(self.mod, ["--agents", str(self.agents),
                               "--out", str(self.d / "out")] + list(extra))

    def test_missing_tier_definition_fails(self):
        (self.agents / "t3.md").unlink()
        rc, _, err = self._gen()
        self.assertEqual(rc, 2)
        self.assertIn("missing fanout tier definition", err)

    def test_dangling_prompt_path_fails(self):
        (self.agents / "t1.md").write_text(
            "---\nkind: fanout\nprompt: core/prompts/stages/nope.md\n"
            "description: x\n---\nbody\n", encoding="utf-8")
        rc, _, err = self._gen()
        self.assertEqual(rc, 2)
        self.assertIn("referenced leaf prompt not found", err)

    def test_duplicate_tool_name_fails(self):
        (self.agents / "dup.md").write_text(
            "---\nkind: delegate\ntool_name: mgh_sast_survey\nprompt: none\n"
            "tool_filter: [read]\ndescription: x\n---\ndup\n", encoding="utf-8")
        rc, _, err = self._gen()
        self.assertEqual(rc, 2)
        self.assertIn("duplicate delegate tool_name", err)

    def test_unknown_frontmatter_key_fails(self):
        (self.agents / "sdr.md").write_text(
            "---\nkind: fanout\nprompt: none\ndescription: x\nbogus: 1\n---\nb\n",
            encoding="utf-8")
        rc, _, err = self._gen()
        self.assertEqual(rc, 2)
        self.assertIn("unknown frontmatter key", err)

    def test_check_mode_no_write_and_drift_fails(self):
        rc, stdout, _ = self._gen()
        self.assertEqual(rc, 0)
        stale = self.d / "out" / "scout.yml"
        content_before = stale.read_text(encoding="utf-8")
        rc, stdout, _ = self._gen(("--check",))
        self.assertEqual(rc, 0)
        self.assertEqual("present", stdout["action"])
        self.assertEqual(content_before, stale.read_text(encoding="utf-8"))
        stale.write_text(content_before + "# tampered\n", encoding="utf-8")
        rc, _, err = self._gen(("--check",))
        self.assertEqual(rc, 2)
        self.assertIn("stale", err)


class TestRealDefinitionsPassAndAreRooted(unittest.TestCase):
    def test_repo_definitions_compile(self):
        mod = _load()
        d = Path(tempfile.mkdtemp(prefix="mgh_tiers_real_"))
        try:
            rc, stdout, err = _run(mod, ["--agents", str(AGENTS),
                                         "--out", str(d / "tiers"),
                                         "--delegates-out", str(d / "delegates.yml"),
                                         "--check"])
            # --check against a never-generated dir must fail loud (missing)
            self.assertEqual(rc, 2)
            self.assertIn("missing", err)
            rc, stdout, err = _run(mod, ["--agents", str(AGENTS),
                                         "--out", str(d / "tiers"),
                                         "--delegates-out", str(d / "delegates.yml")])
            self.assertEqual(rc, 0, err)
            self.assertEqual(6, len(stdout["tiers"]))
            self.assertEqual(11, len(stdout["delegates"]))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_definitions_never_carry_host_prefixed_roots(self):
        # dsh install root is target-relative `mgh-core/` — a `.opencode/`/`.claude/`
        # prefix in a dsh definition would ship a dead path into the persona.
        for p in sorted(AGENTS.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            self.assertNotIn(".opencode/mgh-core", text, p.name)
            self.assertNotIn(".claude/mgh-core", text, p.name)


class TestGeneratorZeroDeps(unittest.TestCase):
    def test_generator_imports_only_stdlib(self):
        stdlib = set(sys.stdlib_module_names)
        tree = ast.parse((TOOLS / "gen_dsh_tiers.py").read_text(encoding="utf-8"),
                         filename=str(TOOLS / "gen_dsh_tiers.py"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name.split(".")[0] for n in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for top in names:
                self.assertIn(top, stdlib, f"non-stdlib import {top}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
