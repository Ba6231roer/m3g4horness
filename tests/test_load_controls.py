#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for load_controls.py (sast controls intake + scope projection).

Covers the three duties: (1) intake validation shared by the main path and `--check`
(well-formed → exit 0; missing name/kind/evidence → exit 2; missing file → exit 1);
(2) scope projection (protects glob hit, entry_points intersection, full-repo = all
in-scope, under-filter keeps out_of_scope_summary); (3) kind alias normalization to the
vvah canonical 6-enum. Mirrors test_list_verify_jobs.py (in-process via importlib) +
test_sast_runtime.py (subprocess from a non-script cwd).
"""
import contextlib, importlib.util, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))
PY = sys.executable


def _load():
    spec = importlib.util.spec_from_file_location("load_controls", SCRIPTS / "load_controls.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctrl(name="c", kind="auth", protects=None, entry_points=None, evidence=None, **extra):
    c = {"name": name, "kind": kind,
         "evidence": evidence if evidence is not None else ["src/x.java:1"]}
    if protects is not None:
        c["protects"] = protects
    if entry_points is not None:
        c["entry_points"] = entry_points
    c.update(extra)
    return c


def _inv(*controls):
    return {"repo": "/svc", "format": "claude", "controls": list(controls)}


class TestLoadControlsInProcess(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lc_"))

    def _write(self, obj, name="inv.json"):
        p = self.d / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, *argv):
        old, sys.argv = sys.argv, ["load_controls.py", *argv]
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    # --- kind alias normalization ---

    def test_normalize_kind_canonical_passthrough(self):
        for k in ("auth", "sandbox", "input-validation", "aslr", "cfi", "other"):
            self.assertEqual(self.m.normalize_kind(k), k)

    def test_normalize_kind_aliases(self):
        cases = {"authn": "auth", "authz": "auth", "rbac": "auth", "iam": "auth", "sso": "auth",
                 "waf": "input-validation", "validation": "input-validation",
                 "sanitization": "input-validation", "encoding": "input-validation",
                 "seccomp": "sandbox", "container": "sandbox", "isolation": "sandbox"}
        for alias, canon in cases.items():
            self.assertEqual(self.m.normalize_kind(alias), canon, alias)

    def test_normalize_kind_unknown_is_none(self):
        for k in ("firewall", "", "Auth", None):
            self.assertIsNone(self.m.normalize_kind(k), repr(k))

    # --- intake validation (--check) ---

    def test_check_ok_exit0(self):
        p = self._write(_inv(_ctrl(kind="authz", protects=["src/api/**"])))
        code, out, _ = self._run("--check", str(p))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["ok"])
        self.assertEqual(d["controls"], 1)

    def test_check_missing_name_exit2(self):
        p = self._write(_inv({"kind": "auth", "evidence": ["a:1"]}))
        code, out, _ = self._run("--check", str(p))
        self.assertEqual(code, 2)
        self.assertFalse(json.loads(out)["ok"])

    def test_check_bad_kind_exit2(self):
        p = self._write(_inv(_ctrl(kind="firewall")))
        code, out, _ = self._run("--check", str(p))
        self.assertEqual(code, 2)
        self.assertIn("kind", json.dumps(json.loads(out)["violations"], ensure_ascii=False))

    def test_check_missing_evidence_exit2(self):
        p = self._write(_inv(_ctrl(evidence=[])))
        code, _, _ = self._run("--check", str(p))
        self.assertEqual(code, 2)

    def test_check_missing_file_exit1(self):
        code, _, _ = self._run("--check", str(self.d / "nope.json"))
        self.assertEqual(code, 1)

    def test_check_malformed_json_exit1(self):
        p = self.d / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        code, _, _ = self._run("--check", str(p))
        self.assertEqual(code, 1)

    def test_check_controls_not_list_exit2(self):
        p = self._write({"controls": "nope"})
        code, out, _ = self._run("--check", str(p))
        self.assertEqual(code, 2)

    # --- scope projection (main path) ---

    def test_main_missing_repo_exit2(self):
        p = self._write(_inv(_ctrl()))
        code, _, _ = self._run("--inventory", str(p))
        self.assertEqual(code, 2)

    def test_full_repo_all_in_scope(self):
        p = self._write(_inv(_ctrl("a"), _ctrl("b"), _ctrl("c")))
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc")
        self.assertEqual(code, 0)
        b = json.loads(out)
        self.assertEqual(b["total"], 3)
        self.assertEqual(b["in_scope_count"], 3)
        self.assertEqual(b["out_of_scope_count"], 0)
        self.assertEqual(len(b["in_scope"]), 3)
        self.assertEqual(b["out_of_scope_summary"], [])

    def test_projection_protects_hit(self):
        p = self._write(_inv(
            _ctrl("auth", kind="authz", protects=["src/api/**"]),
            _ctrl("waf", kind="waf", protects=["edge/**"])))
        scope = self._write({"in_scope": ["src/api/Ctrl.java"]}, "scope.json")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(scope))
        self.assertEqual(code, 0)
        b = json.loads(out)
        self.assertEqual(b["in_scope_count"], 1)
        self.assertEqual(b["out_of_scope_count"], 1)
        self.assertEqual(b["in_scope"][0]["name"], "auth")
        self.assertEqual(b["out_of_scope_summary"][0]["name"], "waf")

    def test_projection_entry_points_match(self):
        # no protects, but entry_points intersects the scanned scope
        p = self._write(_inv(_ctrl("ep", entry_points=["src/svc/Worker.c"])))
        scope = self._write(["src/svc/Worker.c"], "scope.json")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(scope))
        self.assertEqual(code, 0)
        b = json.loads(out)
        self.assertEqual(b["in_scope_count"], 1)

    def test_projection_underfilter_keeps_out_of_scope(self):
        # a control whose protects miss the scope is NOT deleted — it stays in summary (D5)
        p = self._write(_inv(_ctrl("miss", kind="seccomp", protects=["unrelated/**"])))
        scope = self._write({"in_scope": ["src/api/Ctrl.java"]}, "scope.json")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(scope))
        self.assertEqual(code, 0)
        b = json.loads(out)
        self.assertEqual(b["in_scope_count"], 0)
        self.assertEqual(b["out_of_scope_count"], 1)
        self.assertEqual(b["out_of_scope_summary"], [{"name": "miss", "kind": "sandbox"}])

    def test_bundle_invariants_and_shape(self):
        p = self._write(_inv(
            _ctrl("auth", kind="authz", protects=["src/api/**"]),
            _ctrl("waf", kind="waf", protects=["edge/**"])))
        scope = self._write({"in_scope": ["src/api/Ctrl.java"]}, "scope.json")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(scope))
        b = json.loads(out)
        self.assertEqual(b["source"], "mgh-init")
        self.assertEqual(b["inventory_path"], str(p))
        self.assertEqual(b["repo"], "/svc")
        self.assertEqual(b["total"], b["in_scope_count"] + b["out_of_scope_count"])
        # kind normalized to canonical in the in-scope summary
        self.assertEqual(b["in_scope"][0]["kind"], "auth")
        # summary carries the task-1.1 fields
        for f in ("name", "kind", "description", "usage", "evidence",
                  "entry_points", "protects", "gaps"):
            self.assertIn(f, b["in_scope"][0])

    def test_main_path_rejects_malformed_exit2_no_partial_emit(self):
        p = self._write(_inv(_ctrl(), {"kind": "auth", "evidence": ["a:1"]}))  # 2nd lacks name
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc")
        self.assertEqual(code, 2)
        d = json.loads(out)
        self.assertFalse(d["ok"])   # check report, not a partial bundle
        self.assertNotIn("in_scope", d)

    def test_in_scope_accepts_bare_list_and_newline(self):
        p = self._write(_inv(_ctrl("auth", protects=["src/api/**"])))
        scope = self._write(["src/api/Ctrl.java"], "scope.json")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(scope))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["in_scope_count"], 1)
        # newline-delimited fallback
        nl = self.d / "nl.txt"
        nl.write_text("src/api/Ctrl.java\n", encoding="utf-8")
        code, out, _ = self._run("--inventory", str(p), "--repo", "/svc", "--in-scope", str(nl))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["in_scope_count"], 1)


class TestLoadControlsStandalone(unittest.TestCase):
    """Runs as a REAL SUBPROCESS from a NON-script cwd (self-locate sys.path + zero-dep)."""

    def setUp(self):
        self.cwd = Path(tempfile.mkdtemp(prefix="mgh_lc_rt_"))

    def _run(self, *args):
        return subprocess.run([PY, str(SCRIPTS / "load_controls.py"), *args],
                              cwd=str(self.cwd), capture_output=True, text=True, encoding="utf-8")

    def test_runs_from_non_script_cwd(self):
        inv = self.cwd / "inv.json"
        inv.write_text(json.dumps(_inv(_ctrl("auth", kind="authz", protects=["src/api/**"])),
                                  ensure_ascii=False), encoding="utf-8")
        (self.cwd / "scope.json").write_text(
            json.dumps({"in_scope": ["src/api/Ctrl.java"]}), encoding="utf-8")
        r = self._run("--inventory", str(inv), "--repo", str(self.cwd),
                      "--in-scope", str(self.cwd / "scope.json"))
        self.assertEqual(r.returncode, 0,
                         f"failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        b = json.loads(r.stdout)
        self.assertEqual(b["in_scope_count"], 1)
        self.assertEqual(b["in_scope"][0]["kind"], "auth")

    def test_help_is_contract(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        for flag in ("--inventory", "--repo", "--in-scope", "--check"):
            self.assertIn(flag, r.stdout, f"--help lacks {flag}")

    def test_check_subprocess_exit_codes(self):
        ok = self.cwd / "ok.json"
        ok.write_text(json.dumps(_inv(_ctrl())), encoding="utf-8")
        bad = self.cwd / "bad.json"
        bad.write_text(json.dumps(_inv({"kind": "auth", "evidence": ["a:1"]})), encoding="utf-8")
        self.assertEqual(self._run("--check", str(ok)).returncode, 0)
        self.assertEqual(self._run("--check", str(bad)).returncode, 2)
        self.assertEqual(self._run("--check", str(self.cwd / "nope.json")).returncode, 1)


if __name__ == "__main__":
    unittest.main()
