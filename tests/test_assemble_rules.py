#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for assemble_rules.py: opencode lazy-index build + purity lint (R5.7 closed loop).

opencode: T3 writes shipped detail files to <target>/<rules-dir>/<cat>.md; assemble_rules
builds a CONCISE lazy-load index block in AGENTS.md (one `@<rel>` line per detail file) and
purity-lints the detail files. claude: lint-only over .claude/rules/security-*.md.

Runs the script as a REAL subprocess from a NON-script cwd (FD2 family robustness — also
covers task 7.2: import/cwd self-containment). Run: py -3 tests/test_assemble_rules.py
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "assemble_rules.py"
PY = sys.executable  # real interpreter when launched via `py -3`

# The child prints JSON with `ensure_ascii=False` (Chinese lint tokens). On Windows
# the child's pipe stdout defaults to the console codepage (cp936); decoding those
# bytes as UTF-8 would fail and leave stdout=None. Normalize the boundary so Chinese
# token assertions are reliable cross-platform (does not change the script contract).
_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestAssembleOpencode(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_asm_"))
        self.rules_dir = self.target / "docs" / "security-controls"
        self.agents = self.target / "AGENTS.md"
        self.cwd = self.target  # NON-script cwd (task 7.2)

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPT), "--target", str(self.target), *args],
                              cwd=str(self.cwd), env=_CHILD_ENV,
                              capture_output=True, text=True, encoding="utf-8")

    def _seed(self):
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- **AuthConfig**: Bearer Token。锚点: src/A.java::A.b\n")
        _write(self.rules_dir / "authorization.md",
               "# 授权 安全控制\n\n- **方法级安全**: @PreAuthorize。锚点: src/C.java::C.d\n")

    def test_builds_concise_index_block(self):
        # 6.1: detail files -> AGENTS.md concise index (one @-ref line each + lazy directive).
        self._seed()
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(body.count("<!-- security-controls:end -->"), 1)
        self.assertIn("## 安全设计 — 复用,勿重造", body)
        self.assertIn("**按需加载**", body)                          # lazy directive present
        # display name = first H1 minus the ` 安全控制` suffix; ref relative to target
        self.assertIn("- 认证 → @docs/security-controls/authentication.md", body)
        self.assertIn("- 授权 → @docs/security-controls/authorization.md", body)
        # rule BODIES stay in detail files, NOT inlined into the index
        self.assertNotIn("Bearer Token", body)
        self.assertNotIn("@PreAuthorize", body)
        summ = json.loads(r.stdout)
        self.assertEqual(summ["categories"], ["authentication", "authorization"])
        self.assertEqual(summ["block"], "security-controls")
        self.assertTrue(summ["lint"]["ok"])
        self.assertIn("docs/security-controls", summ["rules_dir"].replace("\\", "/"))

    def test_rules_dir_override(self):
        # --rules-dir relocates detail files; index @-refs follow.
        custom = self.target / "custom-rules"
        _write(custom / "crypto.md",
               "# 加密 安全控制\n\n- **CipherUtil**: AES。锚点: src/X.java::X.y\n")
        r = self._run("--format", "opencode", "--rules-dir", "custom-rules")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertIn("- 加密 → @custom-rules/crypto.md", body)

    def test_idempotent_two_runs_one_block(self):
        self._seed()
        self._run("--format", "opencode")
        self._run("--format", "opencode")
        body = self.agents.read_text(encoding="utf-8")
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(body.count("<!-- security-controls:end -->"), 1)

    def test_legacy_branded_block_migrated(self):
        # 6.4: old `<!-- mgh-init:begin -->` branded block swept on first run.
        _write(self.agents,
               "# Proj\n\n用户内容。\n\n"
               "<!-- mgh-init:begin:audit-logging -->\n### 旧\n- 旧内容\n"
               "<!-- mgh-init:end:audit-logging -->\n\n尾部。\n")
        self._seed()
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertNotIn("mgh-init:begin", body)          # legacy swept
        self.assertIn("用户内容。", body)                  # user content kept
        self.assertIn("尾部。", body)
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)
        self.assertEqual(json.loads(r.stdout)["migrated_legacy_blocks"], 1)

    def test_old_inline_block_replaced_by_index(self):
        # 6.4: old "full inline" block (SAME sentinel, pre-change output) -> index block.
        _write(self.agents,
               "# Proj\n\n<!-- security-controls:begin -->\n## 安全设计\n\n"
               "### 旧全量内联\n- 一大堆旧规则正文\n<!-- security-controls:end -->\n\n尾部\n")
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- **AuthConfig**: 锚点: src/A.java::A.b\n")
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertNotIn("旧全量内联", body)               # old inline body gone
        self.assertIn("尾部", body)                         # user content kept
        self.assertIn("- 认证 → @docs/security-controls/authentication.md", body)
        self.assertEqual(body.count("<!-- security-controls:begin -->"), 1)

    def test_user_content_preserved_when_block_appended(self):
        _write(self.agents, "# My Proj\n\n一些手写说明。\n")
        self._seed()
        self._run("--format", "opencode")
        body = self.agents.read_text(encoding="utf-8")
        self.assertIn("# My Proj", body)
        self.assertIn("一些手写说明。", body)

    def test_check_fails_loud_on_leaked_script_name(self):
        _write(self.rules_dir / "crypto.md",
               "# 加密 安全控制\n\n- 由 discover_controls.py 发现。锚点: src/X.java::X.y\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 2)
        summ = json.loads(r.stdout)
        self.assertFalse(summ["lint"]["ok"])
        self.assertTrue(any(v["token"] == "discover_controls.py"
                            for v in summ["lint"]["violations"]))
        # a non-check (write) run must NOT persist a polluted index
        r2 = self._run("--format", "opencode")
        self.assertEqual(r2.returncode, 2)
        body = self.agents.read_text(encoding="utf-8") if self.agents.exists() else ""
        self.assertNotIn("security-controls:begin", body)

    def test_bare_tier_token_not_flagged(self):
        _write(self.rules_dir / "input-validation.md",
               "# 输入校验 安全控制\n\n- **Sanitizer**: 复用。锚点: src/T1LineParser.java::T1LineParser.parse\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertTrue(json.loads(r.stdout)["lint"]["ok"])

    def test_bare_generic_words_not_flagged(self):
        # bare `category` / `缺失` / `锚点` are EXCLUDED from the token set (no FP).
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- 这是个 category 字段。某控制缺失。锚点: src/A.java::A.b\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertTrue(json.loads(r.stdout)["lint"]["ok"])

    def test_check_fails_loud_on_inventory_schema_field(self):
        # 6.2: controls_inventory.json schema field names leaked into the body.
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- **AuthConfig**: Bearer Token。锚点: src/A.java::A.b\n"
               "found_controls:\n  - C-AUTHN-001\nevidence_count: 1\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 2)
        summ = json.loads(r.stdout)
        self.assertFalse(summ["lint"]["ok"])
        toks = {v["token"] for v in summ["lint"]["violations"]}
        self.assertIn("found_controls", toks)
        self.assertIn("evidence_count", toks)

    def test_check_fails_loud_on_yaml_fence(self):
        # 6.2: a `---` YAML front-matter fence inside an opencode detail file.
        _write(self.rules_dir / "authentication.md",
               "---\ncategory: authentication\n---\n"
               "# 认证 安全控制\n\n- **AuthConfig**: 锚点: src/A.java::A.b\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 2)
        summ = json.loads(r.stdout)
        self.assertFalse(summ["lint"]["ok"])
        self.assertTrue(any(v["token"] == "--- YAML fence"
                            for v in summ["lint"]["violations"]))

    def test_check_fails_loud_on_discovery_prose(self):
        # 6.2: scanner/regex internals + anchor mispointed at scanner internals.
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- C-AUTHN-001(扫描器模式定义) 检测模式。"
               "锚点：扫描器内部正则定义\n")
        r = self._run("--format", "opencode", "--check")
        self.assertEqual(r.returncode, 2)
        summ = json.loads(r.stdout)
        self.assertFalse(summ["lint"]["ok"])
        toks = {v["token"] for v in summ["lint"]["violations"]}
        self.assertIn("扫描器模式定义", toks)
        self.assertIn("扫描器内部正则", toks)
        self.assertIn("锚点：扫描器", toks)  # full-width-colon variant

    def test_index_no_orphan_for_absent_category(self):
        # 6.3: only seed authentication; index has authentication, NOT authorization (no orphan).
        _write(self.rules_dir / "authentication.md",
               "# 认证 安全控制\n\n- **AuthConfig**: 锚点: src/A.java::A.b\n")
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertIn("@docs/security-controls/authentication.md", body)
        self.assertNotIn("authorization", body)
        self.assertNotIn("@docs/security-controls/authorization.md", body)

    def test_display_name_falls_back_to_stem(self):
        # 6.3: detail file with NO `#` heading -> index display name = filename stem.
        _write(self.rules_dir / "authentication.md",
               "- **AuthConfig**: Bearer Token。锚点: src/A.java::A.b\n")
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        body = self.agents.read_text(encoding="utf-8")
        self.assertIn("- authentication → @docs/security-controls/authentication.md", body)

    def test_empty_rules_dir_leaves_agents_unchanged(self):
        # no detail files -> AGENTS.md left untouched (nothing to index).
        r = self._run("--format", "opencode")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertFalse(self.agents.exists())
        self.assertEqual(json.loads(r.stdout)["categories"], [])

    def test_runs_from_unrelated_cwd(self):
        # R5.3a: self-locating; runs from a cwd unrelated to script dir AND target.
        self._seed()
        other_cwd = Path(tempfile.mkdtemp(prefix="mgh_cwd_"))
        r = subprocess.run([PY, str(SCRIPT), "--target", str(self.target),
                            "--format", "opencode"], cwd=str(other_cwd),
                           env=_CHILD_ENV, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        self.assertTrue(json.loads(r.stdout)["lint"]["ok"])


class TestLintClaude(unittest.TestCase):
    def setUp(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_cl_"))

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPT), "--target", str(self.target), *args],
                              env=_CHILD_ENV,
                              capture_output=True, text=True, encoding="utf-8")

    def test_claude_check_fails_on_leak(self):
        _write(self.target / ".claude" / "rules" / "security-crypto.md",
               "---\npaths: [\"src/**\"]\n---\n# 安全\n- 经 chunk_sources.py 切片发现。\n")
        r = self._run("--format", "claude", "--check")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["lint"]["ok"])

    def test_claude_check_clean(self):
        _write(self.target / ".claude" / "rules" / "security-crypto.md",
               "---\npaths: [\"src/**\"]\n---\n# 安全\n- **CipherUtil**: AES 封装。锚点: src/C.java::C.b\n")
        r = self._run("--format", "claude", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")

    def test_claude_paths_frontmatter_and_bare_words_not_flagged(self):
        # claude legitimately uses `paths:` front matter (fence check is opencode-only),
        # and bare `category`/`缺失`/`锚点` are excluded from the token set (no FP).
        _write(self.target / ".claude" / "rules" / "security-crypto.md",
               "---\npaths:\n  - \"src/**\"\n---\n"
               "# 安全\n- 这是个 category 字段。某控制缺失。锚点: src/C.java::C.b\n")
        r = self._run("--format", "claude", "--check")
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        summ = json.loads(r.stdout)
        self.assertTrue(summ["lint"]["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
