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

    def test_out_dir_guard_fails_loud(self):
        """R5.9 self-check: `--out <existing dir>` exits 2 + recipe (the observed misuse
        passed the bare slice DIR instead of <slice_dir>/<safe-stem>.slice.json)."""
        import subprocess
        out_dir = self.repo / "slices"
        out_dir.mkdir()
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "chunk_sources.py"),
             "--in", str(self.big), "--out", str(out_dir)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("NEVER pass --out a directory", r.stderr)
        self.assertIn("<safe-stem>", r.stderr)   # recipe names the canonical file form

    def test_out_file_still_writes(self):
        """A file `--out` writes normally (the dir guard does not over-block)."""
        import subprocess
        out_file = self.repo / "out" / "Big.slice.json"
        out_file.parent.mkdir()
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "chunk_sources.py"),
             "--in", str(self.big), "--line", "1", "--out", str(out_file)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(out_file.exists())


CTRL_JAVA = """\
package com.bank.ctrl;
public class Ctrl {
  public String mask(String s) {
    while (s.length() > 8) {
      s = s.substring(8);
    }
    for (String part : s.split(",")) {
      if (part.isEmpty()) {
        continue;
      }
    }
    try {
      switch (s) {
        case "a":
          break;
        default:
          break;
      }
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
    synchronized (this) {
      s = s.trim();
    }
    do {
      s = s + "x";
    } while (false);
    return s;
  }
  public synchronized void guard(String raw) {
    String cleaned = raw.trim();
  }
}
"""


class TestJavaControlFlowExclusion(unittest.TestCase):
    """M3 ①: JAVA_DEF matches control-flow heads (`while (…) {`, `catch (…) {`,
    `synchronized (…) {`, …) because they are "name + paren + brace" shaped —
    each such block became a phantom function node, splitting big files by loop
    body instead of method body and truncating the enclosing method's
    `line_end` at the first inner block. The exclusion is a deterministic
    post-filter on the captured name (never a regex rewrite), and a
    `synchronized`-MODIFIED real method (whose captured name is the method
    name) stays recognized."""

    def setUp(self):
        self.cs = _load("chunk_sources")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_ctrl_"))
        self.f = self.repo / "Ctrl.java"
        self.f.write_text(CTRL_JAVA, encoding="utf-8")

    def _functions(self):
        return [n for n in self.cs.parse_skeleton(self.f, "java")
                if n["kind"] == "function"]

    def test_control_flow_blocks_produce_no_function_nodes(self):
        names = {n["name"] for n in self._functions()}
        self.assertEqual(names, {"mask", "guard"})   # no while/for/if/try/switch/catch/synchronized/do
        for banned in ("while", "for", "if", "switch", "catch", "try", "do", "guard",
                       "substring", "split", "trim", "RuntimeException"):
            if banned == "guard":
                continue
            self.assertNotIn(banned, names)

    def test_real_method_line_end_not_truncated_by_inner_blocks(self):
        fns = {n["name"]: n for n in self._functions()}
        mask = fns["mask"]
        lines = CTRL_JAVA.splitlines()
        mask_start = next(i + 1 for i, ln in enumerate(lines) if "String mask(" in ln)
        guard_start = next(i + 1 for i, ln in enumerate(lines) if "void guard(" in ln)
        self.assertEqual(mask["line_start"], mask_start)
        # pre-fix: line_end = while-line - 1 (the first inner control-flow node);
        # post-fix: extends to just before the next real method
        self.assertEqual(mask["line_end"], guard_start - 1)
        self.assertGreater(mask["line_end"], mask_start + 5)

    def test_synchronized_modified_real_method_still_recognized(self):
        fns = {n["name"]: n for n in self._functions()}
        self.assertIn("guard", fns)               # `synchronized void guard(…)` is a method
        self.assertEqual(fns["guard"]["line_start"],
                         CTRL_JAVA.splitlines().index("  public synchronized void guard(String raw) {") + 1)


class TestChunkInputValidation(unittest.TestCase):
    """M3 ②③: `--in` pointing at a missing file is exit 2 fail-loud (the old
    behavior reported success + an empty skeleton — a subagent path typo looked
    like a clean run); `--line 0` is rejected (truthiness used to route 0 into
    skeleton mode silently; 0 lines is not a legal request; skeleton mode =
    omit --line)."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_chunk_in_"))
        self.src = self.repo / "A.java"
        self.src.write_text("public class A { void m(){} }\n", encoding="utf-8")

    def _run(self, *extra):
        import subprocess
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "chunk_sources.py"), *extra],
            capture_output=True, text=True)

    def test_missing_in_file_exit_2(self):
        r = self._run("--in", str(self.repo / "nope.java"),
                      "--out", str(self.repo / "o.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("nope.java", r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse((self.repo / "o.json").exists())   # no empty-skeleton artifact

    def test_line_zero_exit_2(self):
        r = self._run("--in", str(self.src), "--line", "0",
                      "--out", str(self.repo / "o.json"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("--line", r.stderr)

    def test_line_negative_exit_2(self):
        r = self._run("--in", str(self.src), "--line", "-3",
                      "--out", str(self.repo / "o.json"))
        self.assertEqual(r.returncode, 2)

    def test_line_one_still_slices(self):
        r = self._run("--in", str(self.src), "--line", "1",
                      "--out", str(self.repo / "o.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / "o.json").exists())


if __name__ == "__main__":
    unittest.main()
