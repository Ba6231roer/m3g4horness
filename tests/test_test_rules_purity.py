#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""test_test_rules_purity — assemble_test_rules.py --check must fail loud (exit 2) on rule
bodies leaking ut-internal tokens / inventory schema fields / process prose / YAML fences
(opencode), and pass clean detail files."""

import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
ASSEMBLE = SCRIPTS / "assemble_test_rules.py"
PY = sys.executable

CLEAN = """\
# JUnit 5 测试约定

- **JUnit 5 平台**: 用 `@Test` 写单测。用法: 新测试用 JUnit 5。
  锚点: `src/test/java/com/acme/UserServiceTest.java::UserServiceTest.t`
"""


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestTestRulesPurity(unittest.TestCase):
    def _run_check(self, target, fmt="opencode"):
        return subprocess.run([PY, str(ASSEMBLE), "--target", str(target), "--format", fmt,
                               "--check"], capture_output=True, text=True, encoding="utf-8")

    def _clean_target(self):
        t = Path(tempfile.mkdtemp(prefix="mgh_pur_"))
        _write(t, "docs/test-conventions/junit5.md", CLEAN)
        return t

    def test_clean_detail_passes(self):
        t = self._clean_target()
        r = self._run_check(t, "opencode")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["lint"]["ok"])

    def test_tool_token_leak_fails_loud(self):
        t = self._clean_target()
        _write(t, "docs/test-conventions/bad.md",
               "# X\n\n- **bad**: 这是 mgh-ut-init 内部脚本 classify_tests.py 的产物\n")
        r = self._run_check(t, "opencode")
        self.assertEqual(r.returncode, 2, "tool-token leak must fail loud")
        d = json.loads(r.stdout)
        self.assertFalse(d["lint"]["ok"])
        self.assertTrue(any("mgh-ut-init" in v["token"] for v in d["lint"]["violations"]))

    def test_schema_field_leak_fails_loud(self):
        t = self._clean_target()
        _write(t, "docs/test-conventions/bad.md",
               "# X\n\n- **bad**: uniformity 字段泄漏 uniformity=uniform, assert_density=2.3\n")
        r = self._run_check(t, "opencode")
        self.assertEqual(r.returncode, 2, "schema-field leak must fail loud")
        toks = [v["token"] for v in json.loads(r.stdout)["lint"]["violations"]]
        self.assertTrue(any("uniformity" in tok for tok in toks))

    def test_process_prose_leak_fails_loud(self):
        t = self._clean_target()
        _write(t, "docs/test-conventions/bad.md",
               "# X\n\n- **bad**: 该约定经归类器子分与抽样提炼得出\n")
        r = self._run_check(t, "opencode")
        self.assertEqual(r.returncode, 2, "process-prose leak must fail loud")

    def test_yaml_fence_leak_fails_loud_opencode(self):
        t = self._clean_target()
        _write(t, "docs/test-conventions/bad.md",
               "---\ndescription: leaked front matter\n---\n# X\n")
        r = self._run_check(t, "opencode")
        self.assertEqual(r.returncode, 2, "opencode YAML fence must fail loud")

    def test_claude_frontmatter_is_exempt(self):
        # claude rule files legitimately carry `---` front matter; the fence check is
        # opencode-only (token check still runs).
        t = Path(tempfile.mkdtemp(prefix="mgh_pur_"))
        _write(t, ".claude/rules/test-junit5.md",
               "---\ndescription: JUnit5 convention\n---\n# JUnit 5\n\n- **ok**: 用 JUnit 5。\n"
               "  锚点: `src/test/java/com/acme/UserServiceTest.java::UserServiceTest.t`\n")
        r = self._run_check(t, "claude")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_leak_prevents_agents_md_write(self):
        # a violating detail file must NOT result in AGENTS.md being written (fail-loud).
        t = self._clean_target()
        _write(t, "docs/test-conventions/bad.md", "# X\n\n- **bad**: 泄漏 uniformity 字段\n")
        r = subprocess.run([PY, str(ASSEMBLE), "--target", str(t), "--format", "opencode"],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((t / "AGENTS.md").exists(), "AGENTS.md written despite lint failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
