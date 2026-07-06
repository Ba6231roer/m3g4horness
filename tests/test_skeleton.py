#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for skeleton.json extraction in discover_controls.py (D2)."""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))  # so `from expand_scope import ...` resolves


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# Zero canonical tokens -> regex skips it; skeleton MUST still include it (D2 lossless).
PERM = """\
package com.acme.security;
import jakarta.servlet.http.HttpServletRequest;
public class PermGuard {
  public boolean check(HttpServletRequest r) { return false; }
  public void enforce() {}
}
"""


class TestSkeleton(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_sk_"))
        _write(self.repo, "src/main/java/com/acme/security/PermGuard.java", PERM)

    def _skeleton(self):
        outdir = Path(tempfile.mkdtemp(prefix="mgh_sk_out_"))
        self.d.scan(self.repo, None, 200000, 204800, None, outdir=outdir)
        return json.loads((outdir / "skeleton.json").read_text(encoding="utf-8"))

    def test_skeleton_has_all_fields(self):
        files = self._skeleton()["files"]
        self.assertTrue(files)
        f = next(x for x in files if x["file"].endswith("PermGuard.java"))
        for k in ("file", "lang", "pkg", "classes", "imports",
                  "method_sigs", "fan_in", "bytes", "regex_hit"):
            self.assertIn(k, f)
        self.assertEqual(f["lang"], "java")
        self.assertIn("PermGuard", f["classes"])
        self.assertIn("check", f["method_sigs"])
        self.assertIn("jakarta.servlet.http.HttpServletRequest", f["imports"])
        self.assertGreater(f["bytes"], 0)

    def test_regex_skipped_file_still_in_skeleton(self):
        # PermGuard has zero canonical tokens -> no candidate, but skeleton keeps it
        by_file = {x["file"]: x for x in self._skeleton()["files"]}
        rel = "src/main/java/com/acme/security/PermGuard.java"
        self.assertIn(rel, by_file)
        self.assertFalse(by_file[rel]["regex_hit"])

    def test_no_semantic_judgment_field(self):
        # skeleton MUST NOT carry any 'is_control'/'category'/'kind' semantic verdict —
        # lossless mechanical extraction only (the whole point of D2 vs the regex gate).
        for f in self._skeleton()["files"]:
            for bad in ("is_control", "category", "kind", "confidence"):
                self.assertNotIn(bad, f)


if __name__ == "__main__":
    unittest.main()
