#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for chunk_sources.py (large-file skeleton + slicing)."""
import importlib.util, sys, unittest, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BIG_JAVA = """\
package com.bank.big;
public class BigA {
  public void methodOne() {
    // padding line
    // padding line
    String x = "a";
  }
  public void methodTwo() {
    String y = "b";
  }
}
class BigB {
  public void methodThree() { String z = "c"; }
}
"""


class TestChunkSources(unittest.TestCase):
    def setUp(self):
        self.cs = _load("chunk_sources")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_chunk_"))
        self.big = self.repo / "Big.java"
        self.big.write_text(BIG_JAVA, encoding="utf-8")

    def test_small_file_not_sharded(self):
        small = self.repo / "S.java"
        small.write_text("public class S { void m(){} }", encoding="utf-8")
        self.assertFalse(self.cs.is_big(small, 204800))

    def test_big_file_skeleton_has_nodes(self):
        skel = self.cs.parse_skeleton(self.big, "java")
        names = {n["name"] for n in skel}
        self.assertIn("BigA", names)
        self.assertIn("methodOne", names)
        self.assertIn("methodTwo", names)
        # node line_end >= line_start and bounded
        for n in skel:
            self.assertGreaterEqual(n["line_end"], n["line_start"])

    def test_slice_encloses_candidate_line(self):
        # find the line of methodTwo body
        lines = BIG_JAVA.splitlines()
        target = next(i + 1 for i, ln in enumerate(lines) if 'String y = "b"' in ln)
        sl = self.cs.slice_for_line(self.big, target, window=20, lang="java")
        self.assertTrue(sl["sharded"], "slice within a known node is sharded")
        enc = sl["enclosing"]
        self.assertIsNotNone(enc)
        self.assertEqual(enc["name"], "methodTwo")
        self.assertLessEqual(enc["line_start"], target)
        self.assertGreaterEqual(enc["line_end"], target)

    def test_is_big_threshold(self):
        self.assertTrue(self.cs.is_big(self.big, 50))   # ~400 bytes > 50
        self.assertFalse(self.cs.is_big(self.big, 10_000_000))


if __name__ == "__main__":
    unittest.main()
