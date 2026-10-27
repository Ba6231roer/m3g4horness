#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Tests for validate_inventory.py — T2 boundary validator (R5.9).

Covers the legacy shape checks (wrapper/enum/evidence non-empty/category->kind
drift) and the evidence anchor existence gate (harden-mgh-init-output-gates):
token three-form parsing through the shared anchor_resolve ladder, the four
violation/pass classes (file_missing / line_out_of_range / symbol_absent /
by_basename), stdout classification counters, stderr first-N examples with
control names, and the no-repo fail-loud path.

Runs the script as a REAL subprocess from a NON-script cwd (FD2 family
robustness). Run: py -3 tests/test_validate_inventory.py
"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "validate_inventory.py"
PY = sys.executable  # real interpreter when launched via `py -3`

_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _write(p: Path, text: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class _Base(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_vi_"))
        # 13 lines so the spec-scenario line anchor `:12` is in range
        _write(self.repo / "src" / "a" / "Foo.java",
               "class Foo {\n" + "  // filler\n" * 10 + "  void bar() {}\n}\n")
        self.init_dir = Path(tempfile.mkdtemp(prefix="mgh_vi_out_"))
        self.inv_path = self.init_dir / "controls_inventory.json"
        self.cwd = self.init_dir  # NON-script cwd

    def _ctl(self, evidence, category="authentication", name="spring-auth"):
        return {"name": name, "kind": "auth", "category": category,
                "description": "x", "usage": "y", "evidence": evidence}

    def _write_inv(self, controls, repo=None):
        self.inv_path.write_text(json.dumps(
            {"repo": str(repo or self.repo), "format": "opencode",
             "controls": controls}, ensure_ascii=False), encoding="utf-8")

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPT), "--inventory", str(self.inv_path), *args],
                              cwd=str(self.cwd), env=_CHILD_ENV,
                              capture_output=True, text=True, encoding="utf-8")


class TestShapeLegacy(_Base):
    def test_ok_minimal(self):
        self._write_inv([self._ctl(["src/a/Foo.java:2"])])
        r = self._run()
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        out = json.loads(r.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["anchors"]["anchors_total"], 1)
        self.assertEqual(out["anchors"]["ok"], 1)

    def test_shape_violation_bad_kind(self):
        self._write_inv([self._ctl(["src/a/Foo.java:2"], name="c1") |
                         {"kind": "banana"}])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["ok"])

    def test_shape_violation_empty_evidence(self):
        self._write_inv([self._ctl([], name="c1")])
        r = self._run()
        self.assertEqual(r.returncode, 2)

    def test_missing_inventory_file(self):
        r = subprocess.run([PY, str(SCRIPT), "--inventory", "nope.json"],
                           cwd=str(self.cwd), env=_CHILD_ENV,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(r.returncode, 1)


class TestAnchorGate(_Base):
    def test_three_forms_all_ok(self):
        # spec scenario: one line anchor + both symbol forms -> exit 0, ok=3
        self._write_inv([self._ctl(
            ["src/a/Foo.java:12", "src/a/Foo.java::Foo.bar",
             "src/a/Foo.java:Foo.bar"], name="c-all")])
        r = self._run()
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        a = json.loads(r.stdout)["anchors"]
        self.assertEqual(a["anchors_total"], 3)
        self.assertEqual(a["ok"], 3)
        self.assertEqual(a["file_missing"], 0)

    def test_file_missing(self):
        self._write_inv([self._ctl(["src/missing/Bar.java:3"], name="ctrl-x")])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        out = json.loads(r.stdout)
        self.assertGreaterEqual(out["anchors"]["file_missing"], 1)
        self.assertFalse(out["ok"])
        # stderr example carries the token AND the control name
        self.assertIn("ctrl-x", r.stderr)
        self.assertIn("src/missing/Bar.java:3", r.stderr)

    def test_line_out_of_range(self):
        self._write_inv([self._ctl(["src/a/Foo.java:99"], name="c-line")])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertGreaterEqual(json.loads(r.stdout)["anchors"]["line_out_of_range"], 1)

    def test_symbol_absent(self):
        self._write_inv([self._ctl(["src/a/Foo.java::Foo.nope"], name="c-sym")])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertGreaterEqual(json.loads(r.stdout)["anchors"]["symbol_absent"], 1)

    def test_unique_basename_fallback_passes(self):
        # no dir prefix, unique in repo -> PASSING, counted by_basename
        self._write_inv([self._ctl(["Foo.java:Foo.bar"], name="c-base")])
        r = self._run()
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
        a = json.loads(r.stdout)["anchors"]
        self.assertEqual(a["by_basename"], 1)
        self.assertEqual(a["ok"], 0)

    def test_ambiguous_basename_is_violation(self):
        _write(self.repo / "other" / "Foo.java", "class Foo {}\n")
        self._write_inv([self._ctl(["Foo.java:1"], name="c-amb")])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertGreaterEqual(json.loads(r.stdout)["anchors"]["file_missing"], 1)

    def test_counter_partition(self):
        # every token lands in exactly one bucket: total = ok+by_basename+violations
        self._write_inv([
            self._ctl(["src/a/Foo.java:1", "src/missing/B.java:1"], name="c1"),
            self._ctl(["Foo.java:Foo.bar"], name="c2"),
        ])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        a = json.loads(r.stdout)["anchors"]
        self.assertEqual(a["anchors_total"],
                         a["ok"] + a["by_basename"] + a["file_missing"]
                         + a["line_out_of_range"] + a["symbol_absent"])

    def test_stderr_first_n_per_class(self):
        controls = [self._ctl([f"src/missing/M{i}.java:1"], name=f"c-{i}")
                    for i in range(3)]
        self._write_inv(controls)
        r = self._run("--anchor-top", "2")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stderr.count("anchor[file_missing]"), 2)

    def test_non_string_evidence_item_is_shape_violation(self):
        # contract: evidence items are anchor STRINGS; a dict item fails the
        # shape gate loud (sent back to T2), never silently coerced
        self._write_inv([{"name": "c-dict", "kind": "auth",
                          "category": "authentication",
                          "evidence": [{"file": "src/a/Foo.java", "line": 2}]}])
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertTrue(any("non-empty string" in v.get("issue", "")
                            for v in json.loads(r.stdout)["violations"]))


class TestRepoResolution(_Base):
    def test_missing_repo_fails_loud_with_recipe(self):
        self.inv_path.write_text(json.dumps(
            {"format": "opencode",
             "controls": [self._ctl(["src/a/Foo.java:2"])]}), encoding="utf-8")
        r = self._run()
        self.assertEqual(r.returncode, 2)
        self.assertIn("--repo", r.stderr)

    def test_repo_flag_overrides_inventory_field(self):
        # inventory `repo` points nowhere; --repo supplies the real root
        self._write_inv([self._ctl(["src/a/Foo.java:2"])], repo="Z:/nowhere")
        r = self._run("--repo", str(self.repo))
        self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
