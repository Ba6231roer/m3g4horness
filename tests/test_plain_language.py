#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""check_plain_language.py regression (plain-language-doctrine / R5.8).

Subprocess-runs the lint and asserts: (1) the real repo state is green under
the committed allowlist (CI gate); (2) a proposal missing the `> **人话序**`
preamble fails loud (exit 2) and the allowlist exempts it (exit 0); (3) a
blacklisted jargon term in a human-facing file warns but exits 0; (4) an
english-atom-dense line warns, while legitimate flags/paths/code/known tool
names do NOT; (5) agent-facing files (stage prompts / contract md) are never
scanned (no false positives); (6) `--help` works and the lint is
zero-runtime-dep.
Run: py tests/test_plain_language.py
"""
import ast, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LINT = ROOT / "tools" / "check_plain_language.py"
ALLOWLIST = ROOT / "tools" / "plain_language_allowlist.txt"
PY = sys.executable


def run_lint(*extra):
    r = subprocess.run([PY, str(LINT), *extra], capture_output=True)
    r.stdout = r.stdout.decode("utf-8", "replace")
    r.stderr = r.stderr.decode("utf-8", "replace")
    return r


def run_lint_in_root(root: Path, *extra):
    """Run the lint with its repo-relative scan roots pointed at a temp root
    (mirrors openspec/ + docs/ layout) via a symlink-free copy: the lint
    locates roots from its own file position, so we copy the script in and
    build the expected directory shape around it."""
    tools = root / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    (tools / "check_plain_language.py").write_text(
        LINT.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([PY, str(tools / "check_plain_language.py"), *extra],
                       capture_output=True)
    r.stdout = r.stdout.decode("utf-8", "replace")
    r.stderr = r.stderr.decode("utf-8", "replace")
    return r


class TestPlainLanguage(unittest.TestCase):
    # --- forward: real repo state is green under the committed allowlist ---
    def test_repo_green_under_allowlist(self):
        self.assertTrue(ALLOWLIST.is_file(), "committed allowlist missing")
        r = run_lint("--allowlist", str(ALLOWLIST))
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["missing_preambles"], [])
        self.assertEqual(d["warnings"], [])
        self.assertGreaterEqual(d["scanned"], 12)   # 6 proposals + 5 man + glossary
        # the doctrine change itself must carry the preamble WITHOUT allowlist
        self.assertGreaterEqual(d["allowlisted"], 1)

    def test_doctrine_change_preamble_present_without_allowlist(self):
        # add-plain-language-doctrine proves the marker convention is followed
        # by at least the change that introduced it (no allowlist needed).
        d = json.loads(run_lint().stdout)
        self.assertNotIn("add-plain-language-doctrine", d["missing_preambles"])

    # --- missing preamble fails loud (exit 2); allowlist exempts (exit 0) ---
    def test_missing_preamble_fails_loud(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch = root / "openspec" / "changes" / "sample-change"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text("## Why\n\nno preamble here\n",
                                            encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 2)
            d = json.loads(r.stdout)
            self.assertEqual(d["missing_preambles"], ["sample-change"])

    def test_preamble_marker_satisfies_existence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch = root / "openspec" / "changes" / "good-change"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text(
                "> **人话序**(先讲清楚):demo\n\n## Why\n", encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)["missing_preambles"], [])

    def test_allowlist_exempts_missing_preamble(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch = root / "openspec" / "changes" / "legacy-change"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text("## Why\n\nold change\n",
                                            encoding="utf-8")
            al = root / "allow.txt"
            al.write_text("legacy-change\n", encoding="utf-8")
            r = run_lint_in_root(root, "--allowlist", str(al))
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["missing_preambles"], [])
            self.assertEqual(d["allowlisted"], 1)

    def test_archived_changes_not_scanned(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ch = root / "openspec" / "changes" / "archive" / "old"
            ch.mkdir(parents=True)
            (ch / "proposal.md").write_text("## Why\narchived\n", encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 0, r.stderr)

    # --- jargon blacklist: WARN + exit 0, human-facing files only ---
    def test_jargon_in_man_warns_but_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man = root / "docs" / "man"
            man.mkdir(parents=True)
            (man / "x.md").write_text(
                "这个脚本会把仓库锚物化成产物。\n", encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            kinds = {(w["kind"], w.get("term")) for w in d["warnings"]}
            self.assertIn(("jargon", "物化"), kinds)
            self.assertIn(("jargon", "锚"), kinds)

    def test_glossary_term_column_exempt_from_jargon(self):
        # the glossary DEFINES blacklisted terms in its table rows — not a hit
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = root / "docs"
            g.mkdir()
            (g / "glossary.md").write_text(
                "| 哨兵文件 | 磁盘上的 `.active` 小文件 |\n", encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual([w for w in d["warnings"] if w["kind"] == "jargon"],
                             [])

    # --- english-atom density: WARN on bare-english splice; legit uses pass ---
    def test_english_atom_splice_warns(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man = root / "docs" / "man"
            man.mkdir(parents=True)
            (man / "x.md").write_text(
                "来源层等于 producer 物化 repo 锁定,reader 统一走 recipe 拒绝路径。\n",
                encoding="utf-8")
            r = run_lint_in_root(root)
            d = json.loads(r.stdout)
            self.assertTrue(any(w["kind"] == "english_density"
                                for w in d["warnings"]))
            self.assertEqual(r.returncode, 0)   # WARN only

    def test_legit_english_tokens_do_not_warn(self):
        # flags, inline code, paths, known tool names, quotes, headings, tables
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            man = root / "docs" / "man"
            man.mkdir(parents=True)
            (man / "x.md").write_text(
                "# /mgh-init 使用说明\n"
                "> 受众:人类。AI 读的定义在别处。\n"
                "- 重跑加 `--resume`,比如 `py /mgh-init --resume` 这样用。\n"
                "- claude 与 opencode 都支持,git 提交不受影响,建议 gitignore。\n"
                "- 它用 JUnit 和 pytest 写的测试都能识别,mock 打桩也会看。\n"
                "- 任务会被拆成多个并行子单元分给子 AI 各跑一批。\n",
                encoding="utf-8")
            r = run_lint_in_root(root)
            d = json.loads(r.stdout)
            self.assertEqual(d["warnings"], [], r.stderr)

    # --- scope: agent-facing files are never scanned ---
    def test_agent_facing_files_not_scanned(self):
        # a stage prompt / contract md full of jargon must produce NO warnings:
        # the lint's human-facing set is docs/man + docs/glossary + proposals
        # (existence only). Plant agent-facing shape in temp root and assert
        # it contributes neither warnings nor scanned-count growth.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prompts = root / "core" / "prompts" / "stages"
            prompts.mkdir(parents=True)
            (prompts / "init-scout.md").write_text(
                "物化 锚 哨兵 运行域 fan-out recipe NEVER\n" * 5, encoding="utf-8")
            contracts = root / "core" / "contracts"
            contracts.mkdir()
            (contracts / "c.md").write_text("物化 拒识 接线 治类\n", encoding="utf-8")
            r = run_lint_in_root(root)
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["warnings"], [])
            self.assertEqual(d["scanned"], 0)   # nothing human-facing present

    # --- contract surface + self-containment ---
    def test_help_exits_zero(self):
        self.assertEqual(run_lint("--help").returncode, 0)

    def test_lint_is_zero_runtime_deps(self):
        siblings = {p.stem for p in (ROOT / "tools").glob("*.py")}
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
