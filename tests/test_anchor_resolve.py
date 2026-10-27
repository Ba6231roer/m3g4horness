#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for anchor_resolve.py — shared evidence-anchor parsing/resolution
(design D2 of harden-mgh-init-output-gates; single source for the T2 boundary
existence gate and the assembly-boundary coverage gate).

In-process import from the scripts dir (pure library module, no CLI). Covers:
token three-form parsing, resolution ladder (exact -> case -> unique basename),
line-range check, per-segment symbol check, normalized matching keys, and the
basename non-unique/missing failure shapes. Run: py -3 tests/test_anchor_resolve.py
"""
import sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core" / "scripts"))

import anchor_resolve as ar  # noqa: E402


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestParseAnchorToken(unittest.TestCase):
    def test_three_forms(self):
        # closed set: path:line / path::sym / path:sym (+ bare path)
        self.assertEqual(ar.parse_anchor_token("src/a/Foo.java:12"),
                         ("src/a/Foo.java", 12, None))
        self.assertEqual(ar.parse_anchor_token("src/a/Foo.java::Foo.bar"),
                         ("src/a/Foo.java", None, "Foo.bar"))
        self.assertEqual(ar.parse_anchor_token("src/a/Foo.java:Foo.bar"),
                         ("src/a/Foo.java", None, "Foo.bar"))
        self.assertEqual(ar.parse_anchor_token("src/a/Foo.java"),
                         ("src/a/Foo.java", None, None))

    def test_backslash_and_quotes_normalized(self):
        self.assertEqual(ar.parse_anchor_token('"src\\a\\Foo.java:3"'),
                         ("src/a/Foo.java", 3, None))

    def test_no_path_shape_never_line_or_symbol(self):
        # a bare 'C:12' fragment has no path shape -> bare path (no false line
        # anchor); 'src/x.v1:yy' has a non-source ext -> bare path
        self.assertEqual(ar.parse_anchor_token("C:12"), ("C:12", None, None))
        self.assertEqual(ar.parse_anchor_token("src/x.v1:yy"),
                         ("src/x.v1:yy", None, None))


class TestResolutionLadder(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_ar_"))
        _write(self.repo / "src" / "a" / "Foo.java",
               "class Foo {\n  void bar() {}\n  void baz() {}\n}\n")
        self.resolver = ar.RepoResolver(self.repo)

    def test_exact_hit(self):
        p, how = self.resolver.resolve("src/a/Foo.java")
        self.assertIsNotNone(p)
        self.assertEqual(how, "exact")

    def test_case_insensitive_same_dir_hit(self):
        # On POSIX the explicit ladder step fires ("case"); on Windows the FS
        # itself is case-insensitive so is_file() already hits ("exact").
        # Either way the token RESOLVES to the same file — never "missing".
        p, how = self.resolver.resolve("src/a/foo.JAVA")
        self.assertIsNotNone(p)
        self.assertIn(how, ("exact", "case"))

    def test_unique_basename_hit(self):
        # no directory prefix at all -> unique whole-repo basename recovers it
        p, how = self.resolver.resolve("Foo.java")
        self.assertIsNotNone(p)
        self.assertEqual(how, "basename")
        self.assertEqual(p.name, "Foo.java")

    def test_basename_ambiguous_is_missing(self):
        _write(self.repo / "other" / "Foo.java", "class Foo2 {}\n")
        r2 = ar.RepoResolver(self.repo)
        p, how = r2.resolve("Foo.java")
        self.assertIsNone(p)
        self.assertEqual(how, "missing")

    def test_absent_file_is_missing(self):
        p, how = self.resolver.resolve("src/missing/Bar.java")
        self.assertIsNone(p)
        self.assertEqual(how, "missing")

    def test_empty_is_empty(self):
        p, how = self.resolver.resolve("  ")
        self.assertIsNone(p)
        self.assertEqual(how, "empty")


class TestCheckAnchor(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_ck_"))
        _write(self.repo / "src" / "a" / "Foo.java",
               "class Foo {\n  void bar() {}\n}\n")
        self.resolver = ar.RepoResolver(self.repo)

    def test_ok_line_anchor(self):
        r = ar.check_anchor("src/a/Foo.java:2", self.resolver)
        self.assertEqual(r["status"], "ok")

    def test_ok_symbol_anchor_both_forms(self):
        self.assertEqual(
            ar.check_anchor("src/a/Foo.java::Foo.bar", self.resolver)["status"],
            "ok")
        self.assertEqual(
            ar.check_anchor("src/a/Foo.java:Foo.bar", self.resolver)["status"],
            "ok")

    def test_line_out_of_range(self):
        r = ar.check_anchor("src/a/Foo.java:99", self.resolver)
        self.assertEqual(r["status"], "line_out_of_range")
        self.assertEqual(r["lines"], 3)
        # 1-based: line 0 is out of range too
        self.assertEqual(
            ar.check_anchor("src/a/Foo.java:0", self.resolver)["status"],
            "line_out_of_range")

    def test_symbol_absent(self):
        r = ar.check_anchor("src/a/Foo.java::Foo.nope", self.resolver)
        self.assertEqual(r["status"], "symbol_absent")
        # every '.'-segment must appear: class present, method absent
        r2 = ar.check_anchor("src/a/Foo.java::Nope.bar", self.resolver)
        self.assertEqual(r2["status"], "symbol_absent")

    def test_file_missing(self):
        r = ar.check_anchor("src/missing/Bar.java:3", self.resolver)
        self.assertEqual(r["status"], "file_missing")
        self.assertIsNone(r["resolved"])

    def test_by_basename_passes_with_counter_status(self):
        # bare filename, unique in repo -> PASSING but classified separately
        r = ar.check_anchor("Foo.java:Foo.bar", self.resolver)
        self.assertEqual(r["status"], "by_basename")
        self.assertNotIn(r["status"], ar.VIOLATION_STATUSES)


class TestMatchKeys(unittest.TestCase):
    def test_keys_full_then_basename(self):
        keys = ar.evidence_path_keys("src\\A\\Foo.java")
        self.assertEqual(keys, ["src/a/foo.java", "foo.java"])

    def test_keys_dedup_when_bare_basename(self):
        self.assertEqual(ar.evidence_path_keys("Foo.java"), ["foo.java"])

    def test_normalized_substring_match(self):
        # coverage reconciliation shape: normalized key in normalized text
        body = ar.normalize_for_match("锚点: SRC\\A\\Foo.java::Foo.bar 相关")
        self.assertIn(ar.evidence_path_keys("src/a/foo.java")[0], body)
        # a differently-rooted path still matches via its basename key
        self.assertIn(ar.evidence_path_keys("other/dir/Foo.java")[-1], body)
        self.assertNotIn(ar.evidence_path_keys("src/other/Bar.java")[0], body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
