#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for discover_controls.py (stdlib unittest)."""
import importlib.util, sys, unittest, tempfile
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


def _has_dot(rel: str) -> bool:
    """True if any path component of `rel` starts with '.' (the walk_sources prune)."""
    return any(part.startswith(".") for part in Path(rel).parts)


CONTROLLER = """\
package com.bank.api;
import com.bank.util.MaskUtil;
public class TransferController {
  @PreAuthorize("hasRole('USER')")
  public String transfer(@Valid String card) {
    return MaskUtil.mask(card);
  }
}
"""
MASK = """\
package com.bank.util;
public class MaskUtil {
  public static String mask(String s) { return s.substring(0,2); }
}
"""
CRYPTO = """\
package com.bank.crypto;
import javax.crypto.Cipher;
public class AesUtil {
  public byte[] enc(byte[] k) throws Exception {
    Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
    return c.doFinal(k);
  }
}
"""
EXCLUDED = """\
package build;
public class Generated {
  @PreAuthorize("hasRole('X')")
  public void g() {}
}
"""
ISOLATED_CONTROLLER = """\
package com.bank.api2;
@RestController
public class OrphanController {
  public void ping() { System.out.println("hi"); }
}
"""

# ── dot-prefixed tooling sources (would yield a candidate IF scanned) ──
DOT_OPENCODE = ".opencode/plugins/crypto_guard.ts"
DOT_CLAUDE = ".claude/hooks/auth_hook.py"
DOT_CODEGRAPH = ".codegraph/mask_tool.py"
DOT_TOOL_TS = """\
// installed tooling guard (.opencode/plugins)
import { Cipher } from "crypto";
export class CryptoGuard { enc(k) { const c = new Cipher(); return c; } }
"""
DOT_TOOL_PY_AUTH = """\
# installed tooling hook (.claude/hooks)
def hash_pw(pw):
    return BCrypt().hash(pw)
"""
DOT_TOOL_PY_MASK = """\
# installed tooling mask (.codegraph)
def mask_secret(s):
    return s[:2]
"""

# ── non-dot build/cache sources (pruned by EXCLUDE_DIR, not the dot rule) ──
NONDOT_NODEMOD = "node_modules/dep/lib.py"
NONDOT_BUILD = "build/out/Gen.java"
NODEMOD_DEP = """\
# vendored dependency (node_modules)
from crypto import Cipher
def enc(k): return Cipher()
"""
BUILD_GEN = """\
package build;
public class Gen { @PreAuthorize("x") public void g() {} }
"""


# ── test source-tree sources (net noise for production-control discovery) ──
# Maven/Gradle src/test | Python tests/ | JS __tests__/ | Ruby spec/ — skipped by
# default (no candidates, counted in tests_skipped), re-included w/ --include-tests.
TEST_MAVEN = "src/test/java/com/acme/SecurityTest.java"
TEST_MAVEN_SRC = (
    "package com.acme;\n"
    "@EnableMethodSecurity\n"
    "public class SecurityTest { public void check() {} }\n"
)
TEST_PY_DIR = "tests/test_auth.py"
TEST_PY_DIR_SRC = (
    "from crypto import Cipher\n"
    "def test_enc(): return Cipher()\n"
)
TEST_JSTS_DIR = "src/__tests__/auth.ts"
TEST_JSTS_DIR_SRC = (
    "export class AuthTest { mask(s:string):string { return s; } }\n"
)
TEST_SPEC_DIR = "spec/auth_spec.rb"
TEST_SPEC_DIR_SRC = (
    "class AuthSpec; def mask(s); s[0,2]; end; end\n"
)
# Singular bare `test` dir segment under src/main = PRODUCTION code (helper pkg) —
# MUST stay discovered (regression guard: matcher excludes bare singular `test`).
PROD_SINGULAR_TEST = "src/main/java/com/acme/test/Helper.java"
PROD_SINGULAR_TEST_SRC = (
    "package com.acme.test;\n"
    'public class Helper { @PreAuthorize("x") public void h() {} }\n'
)
TEST_PATHS = (TEST_MAVEN, TEST_PY_DIR, TEST_JSTS_DIR, TEST_SPEC_DIR)


def _write_test_sources(repo):
    for rel, src in ((TEST_MAVEN, TEST_MAVEN_SRC), (TEST_PY_DIR, TEST_PY_DIR_SRC),
                     (TEST_JSTS_DIR, TEST_JSTS_DIR_SRC), (TEST_SPEC_DIR, TEST_SPEC_DIR_SRC)):
        _write(repo, rel, src)


class TestDiscover(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_init_"))
        _write(self.repo, "src/main/java/com/bank/api/TransferController.java", CONTROLLER)
        _write(self.repo, "src/main/java/com/bank/util/MaskUtil.java", MASK)
        _write(self.repo, "src/main/java/com/bank/crypto/AesUtil.java", CRYPTO)
        _write(self.repo, "target/gen/Generated.java", EXCLUDED)  # EXCLUDE_DIR
        _write(self.repo, "src/main/java/com/bank/api2/OrphanController.java", ISOLATED_CONTROLLER)
        # dot-prefixed tooling (must be skipped by default; re-included w/ --include-dotfiles)
        _write(self.repo, DOT_OPENCODE, DOT_TOOL_TS)
        _write(self.repo, DOT_CLAUDE, DOT_TOOL_PY_AUTH)
        _write(self.repo, DOT_CODEGRAPH, DOT_TOOL_PY_MASK)
        # non-dot build/cache dirs (still pruned by EXCLUDE_DIR)
        _write(self.repo, NONDOT_NODEMOD, NODEMOD_DEP)
        _write(self.repo, NONDOT_BUILD, BUILD_GEN)

    def _scan(self, seed=None, include_dotfiles=False):
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(
            self.repo, seed, 200000, 204800, None, include_dotfiles=include_dotfiles)
        return cands, rev, fw

    def _run_main(self, mod, argv):
        old = sys.argv
        sys.argv = argv
        try:
            return mod.main()
        finally:
            sys.argv = old

    def test_categories_detected(self):
        cands, _, _ = self._scan()
        cats = {c["category"] for c in cands}
        self.assertIn("authorization", cats)   # @PreAuthorize
        self.assertIn("input-validation", cats)  # @Valid
        self.assertIn("data-masking", cats)    # mask(...)
        self.assertIn("crypto", cats)          # Cipher

    def test_exclude_dir_skipped(self):
        cands, _, _ = self._scan()
        self.assertFalse(any(c["file"].startswith("target/") for c in cands),
                         "target/ (EXCLUDE_DIR) must not yield candidates")

    def test_reverse_wiring_entry_points(self):
        cands, rev, _ = self._scan()
        maskutil = "src/main/java/com/bank/util/MaskUtil.java"
        ctl = "src/main/java/com/bank/api/TransferController.java"
        self.assertIn(ctl, rev.get(maskutil, set()),
                      "controller calls mask() → must be a reverse caller")
        mask_cand = next(c for c in cands if c["file"] == maskutil)
        self.assertIn(ctl, mask_cand["entry_points"])

    def test_kind_normalization(self):
        cands, _, _ = self._scan()
        authz = [c for c in cands if c["category"] == "authorization"]
        self.assertTrue(all(c["kind"] == "auth" for c in authz))
        iv = [c for c in cands if c["category"] == "input-validation"]
        self.assertTrue(all(c["kind"] == "input-validation" for c in iv))

    def test_aop_orphan_in_unresolved(self):
        # OrphanController has @RestController (FRAMEWORK_RX) but no textual edge
        # to any control candidate → should land in unresolved[] via main().
        import json
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        rc = 0
        sys.argv = ["discover_controls.py", "--repo", str(self.repo), "--out", str(outdir)]
        try:
            rc = self.d.main()
        finally:
            pass
        self.assertEqual(rc, 0)
        data = json.loads((outdir / "controls_candidates.json").read_text(encoding="utf-8"))
        self.assertIn("src/main/java/com/bank/api2/OrphanController.java", data["unresolved"])

    def test_no_silent_truncation_flag(self):
        # --max-files=1 on a multi-file repo → truncated=True (warn, not silent drop)
        cands, _, _, fw, trunc, scanned = self.d.scan(self.repo, None, 1, 204800, None)
        self.assertTrue(trunc)

    def test_dotfiles_skipped_by_default(self):
        # Spec scenario 1: installed tooling under .opencode/.claude/.codegraph is
        # NOT discovered by default — no candidates from dot-prefixed sources.
        cands, _, _ = self._scan()
        cand_files = {c["file"] for c in cands}
        for dot in (DOT_OPENCODE, DOT_CLAUDE, DOT_CODEGRAPH):
            self.assertNotIn(dot, cand_files,
                             f"{dot}: dot-prefixed tooling must not yield candidates")

    def test_include_dotfiles_reincludes(self):
        # Spec scenario 2: --include-dotfiles re-includes dot-prefixed sources
        # (behavior equivalent to before this requirement).
        cands, _, _ = self._scan(include_dotfiles=True)
        cand_files = {c["file"] for c in cands}
        for dot in (DOT_OPENCODE, DOT_CLAUDE, DOT_CODEGRAPH):
            self.assertIn(dot, cand_files,
                          f"{dot}: must be re-included under --include-dotfiles")

    def test_dot_skip_consistent_across_stages(self):
        # Spec scenario 3: skeleton, call graph, AND scout targets all exclude dot
        # paths (single chokepoint — not only the regex candidate path).
        import json
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(
            self.repo, None, 200000, 204800, None, outdir=outdir)
        # scan() writes skeleton.json (not controls_candidates.json, which is main()'s
        # job); write a minimal candidates wrapper so plan_scout can read regex-covered
        # files and produce scout targets.
        (outdir / "controls_candidates.json").write_text(
            json.dumps({"repo": str(self.repo), "candidates": cands}),
            encoding="utf-8")
        sk = json.loads((outdir / "skeleton.json").read_text(encoding="utf-8"))
        self.assertFalse(any(_has_dot(f["file"]) for f in sk["files"]),
                         "skeleton.json must contain no dot-prefixed path")
        self.assertFalse(any(_has_dot(f) for f in rev),
                         "call graph (reverse keys) must contain no dot-prefixed path")
        # scout targets derive from skeleton.json via plan_scout.py → assert dot-free
        ps = _load("plan_scout")
        plan_path = outdir / "scout_plan.json"
        rc = self._run_main(ps, ["plan_scout.py",
                                 "--skeleton", str(outdir / "skeleton.json"),
                                 "--candidates", str(outdir / "controls_candidates.json"),
                                 "--out", str(plan_path)])
        self.assertEqual(rc, 0)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        scout_files = [t["file"] for b in plan.get("batches", [])
                       for t in b.get("targets", [])]
        self.assertFalse(any(_has_dot(f) for f in scout_files),
                         "scout targets must contain no dot-prefixed path")

    def test_nondot_build_dirs_still_excluded(self):
        # Spec scenario 4: node_modules/target/build still pruned by EXCLUDE_DIR
        # (the new dot rule must not weaken existing build/cache pruning).
        cands, _, _ = self._scan()
        cand_files = {c["file"] for c in cands}
        for nd in (NONDOT_NODEMOD, NONDOT_BUILD, "target/gen/Generated.java"):
            self.assertNotIn(nd, cand_files,
                             f"{nd}: EXCLUDE_DIR build/cache dir must still be pruned")

    def test_repo_root_not_mis_excluded(self):
        # Spec scenario 5 / D5: a repo/drive-root component never starts with '.',
        # so normal sources are still discovered (Windows C:\... safety).
        self.assertFalse(any(part.startswith(".") for part in self.repo.parts),
                         "test repo path itself must have no dot component")
        _write(self.repo, "RootSvc.java",
               'public class RootSvc { @PreAuthorize("x") public void m() {} }')
        cands, _, _ = self._scan()
        self.assertIn("RootSvc.java", {c["file"] for c in cands},
                      "root-level normal source must be discovered (no dot-root false skip)")

    # ── test source-tree skip (--include-tests) — mirrors the dotfiles tests above ──

    def _scan_tests(self, include_tests, seed=None):
        tests_skipped = [0]
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(
            self.repo, seed, 200000, 204800, None,
            include_tests=include_tests, tests_skipped=tests_skipped)
        return cands, rev, fw, tests_skipped[0]

    def test_tests_skipped_by_default(self):
        # Spec: src/test | tests | __tests__ | spec are NOT discovered by default.
        _write_test_sources(self.repo)
        cands, _, _, n = self._scan_tests(include_tests=False)
        cand_files = {c["file"] for c in cands}
        for rel in TEST_PATHS:
            self.assertNotIn(rel, cand_files,
                             f"{rel}: test source must not yield candidates by default")
        self.assertGreaterEqual(n, 4, "tests_skipped must count the 4 pruned test sources")

    def test_singular_test_dir_kept_as_production(self):
        # Spec regression guard: bare singular `test` dir segment under src/main is
        # production code — NOT matched by the test-dir rule, stays discovered.
        _write(self.repo, PROD_SINGULAR_TEST, PROD_SINGULAR_TEST_SRC)
        cands, _, _, _ = self._scan_tests(include_tests=False)
        self.assertIn(PROD_SINGULAR_TEST, {c["file"] for c in cands},
                      "singular bare test/ production dir must stay discovered")

    def test_include_tests_reincludes(self):
        # Spec: --include-tests re-includes test source trees (eq. to before this rule).
        _write_test_sources(self.repo)
        cands, _, _, n = self._scan_tests(include_tests=True)
        cand_files = {c["file"] for c in cands}
        for rel in TEST_PATHS:
            self.assertIn(rel, cand_files,
                          f"{rel}: must be re-included under --include-tests")
        self.assertEqual(n, 0, "tests_skipped is 0 when --include-tests re-includes all")

    def test_test_skip_consistent_across_stages(self):
        # Spec: test-dir skip is a single chokepoint — skeleton.json, call graph, AND
        # scout targets all exclude test paths (not only the regex candidate path).
        import json
        _write_test_sources(self.repo)
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(
            self.repo, None, 200000, 204800, None, outdir=outdir)  # include_tests=False default
        (outdir / "controls_candidates.json").write_text(
            json.dumps({"repo": str(self.repo), "candidates": cands}), encoding="utf-8")
        sk = json.loads((outdir / "skeleton.json").read_text(encoding="utf-8"))
        self.assertFalse(any(f["file"] in TEST_PATHS for f in sk["files"]),
                         "skeleton.json must contain no test-source-tree path")
        self.assertFalse(any(f in TEST_PATHS for f in rev),
                         "call graph (reverse keys) must contain no test-source-tree path")
        ps = _load("plan_scout")
        plan_path = outdir / "scout_plan.json"
        rc = self._run_main(ps, ["plan_scout.py",
                                 "--skeleton", str(outdir / "skeleton.json"),
                                 "--candidates", str(outdir / "controls_candidates.json"),
                                 "--out", str(plan_path)])
        self.assertEqual(rc, 0)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        scout_files = [t["file"] for b in plan.get("batches", [])
                       for t in b.get("targets", [])]
        self.assertFalse(any(f in TEST_PATHS for f in scout_files),
                         "scout targets must contain no test-source-tree path")

    def test_walk_sources_and_collect_dir_test_prune(self):
        # 7.2: direct unit test of the shared chokepoint (expand_scope). include_tests=True
        # includes; False excludes prefix+segments, keeps singular test, counts correctly.
        es = _load("expand_scope")
        repo = Path(tempfile.mkdtemp(prefix="mgh_walk_"))
        _write(repo, "src/test/java/Foo.java", "class Foo {}")
        _write(repo, "tests/x.py", "def f(): pass")
        _write(repo, "src/__tests__/y.ts", "export class Y {}")
        _write(repo, "spec/z.rb", "class Z; end")
        _write(repo, "src/main/java/com/acme/test/Keep.java", "class Keep {}")  # singular prod

        def collected(include_tests):
            box = [0]
            files = sorted(p.relative_to(repo).as_posix()
                           for p, _ in es.walk_sources(repo, include_tests=include_tests,
                                                       tests_skipped=box))
            return files, box[0]

        inc, n_inc = collected(True)
        for present in ("src/test/java/Foo.java", "tests/x.py", "src/__tests__/y.ts",
                        "spec/z.rb", "src/main/java/com/acme/test/Keep.java"):
            self.assertIn(present, inc)
        self.assertEqual(n_inc, 0)

        exc, n_exc = collected(False)
        for absent in ("src/test/java/Foo.java", "tests/x.py", "src/__tests__/y.ts", "spec/z.rb"):
            self.assertNotIn(absent, exc)
        self.assertIn("src/main/java/com/acme/test/Keep.java", exc)  # singular kept
        self.assertGreaterEqual(n_exc, 4)

        # collect_dir parity (--path/--package scope resolves through the same prune)
        d = repo / "src"
        cd_inc = es.collect_dir(repo, d, include_tests=True)
        cd_exc = es.collect_dir(repo, d, include_tests=False)
        self.assertIn("src/__tests__/y.ts", cd_inc)
        self.assertIn("src/test/java/Foo.java", cd_inc)
        self.assertNotIn("src/__tests__/y.ts", cd_exc)
        self.assertNotIn("src/test/java/Foo.java", cd_exc)
        # singular prod `test` under src/main stays in both
        self.assertIn("src/main/java/com/acme/test/Keep.java", cd_inc)
        self.assertIn("src/main/java/com/acme/test/Keep.java", cd_exc)

    def test_check_validates_tests_skipped_field(self):
        # R5.9 / task 2.5: discover --check validates the wrapper's tests_skipped field.
        # A normal main() run writes it (non-negative int) → --check returns 0; stripping
        # it fails loud (exit 2).
        import json
        _write(self.repo, TEST_MAVEN, TEST_MAVEN_SRC)
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        rc = self._run_main(self.d, ["discover_controls.py", "--repo", str(self.repo),
                                     "--out", str(outdir)])
        self.assertEqual(rc, 0)
        cd = json.loads((outdir / "controls_candidates.json").read_text(encoding="utf-8"))
        self.assertEqual(cd.get("tests_skipped"), 1)  # TEST_MAVEN is the one test source
        # check passes on the just-written products
        self.assertEqual(self._run_main(self.d, ["discover_controls.py", "--check", str(outdir)]), 0)
        # check fails loud if tests_skipped is stripped from the wrapper
        cd.pop("tests_skipped", None)
        (outdir / "controls_candidates.json").write_text(json.dumps(cd), encoding="utf-8")
        self.assertEqual(self._run_main(self.d, ["discover_controls.py", "--check", str(outdir)]), 2)

    def _check_capture(self, outdir):
        """Run discover --check capturing stdout (violations JSON) + rc."""
        import contextlib, importlib.util, io
        spec = importlib.util.spec_from_file_location(
            "dc_capture", SCRIPTS / "discover_controls.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = sys.argv
        sys.argv = ["discover_controls.py", "--check", str(outdir)]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = mod.main()
        finally:
            sys.argv = old
        return rc, buf.getvalue()

    def test_check_wrong_shape_candidates_no_traceback(self):
        # M1: legal JSON with a wrong-shape wrapper (top-level list where the
        # wrapper dict is expected) reports violations + exit 2 — NEVER a bare
        # TypeError traceback (the orchestrator gate recipe only recognizes 2).
        import json
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        (outdir / "controls_candidates.json").write_text("[1, 2, 3]", encoding="utf-8")
        (outdir / "clusters.json").write_text(
            json.dumps({"repo": "r", "clusters": [], "truncated": False}),
            encoding="utf-8")
        rc, out = self._check_capture(outdir)
        self.assertEqual(rc, 2)
        self.assertIn("wrapper must be", out)

    def test_check_wrong_shape_clusters_no_traceback(self):
        import json
        outdir = Path(tempfile.mkdtemp(prefix="mgh_init_out_"))
        (outdir / "controls_candidates.json").write_text(
            json.dumps({"repo": "r", "candidates": [], "tests_skipped": 0}),
            encoding="utf-8")
        (outdir / "clusters.json").write_text("[4, 5]", encoding="utf-8")
        rc, out = self._check_capture(outdir)
        self.assertEqual(rc, 2)
        self.assertIn("wrapper must be", out)

class TestCallGraphOrderIndependence(unittest.TestCase):
    """H5: expand_scope.build_call_graph MUST be two-pass (complete def index
    first, then resolve calls) — cross-file edges NEVER depend on rglob order.
    Before the fix, a file only resolved defs from files EARLIER in the walk,
    silently dropping ~half the cross-file edges."""

    def _pair_repo(self, first_content_name, second_content_name):
        repo = Path(tempfile.mkdtemp(prefix="mgh_cg_"))
        src = repo / "src"
        src.mkdir()
        (src / first_content_name).write_text(
            "public class A { public String mask(String s) { return s; } "
            "public void callB() { B b = new B(); b.check(); } }",
            encoding="utf-8")
        (src / second_content_name).write_text(
            "public class B { public void check() { } "
            "public void callA() { A a = new A(); a.mask(\"x\"); } }",
            encoding="utf-8")
        return repo

    def _edge_set(self, repo):
        es = _load("expand_scope")
        forward, _reverse, _n2f, _fw = es.build_call_graph(repo)
        return {(a, b) for a, tgts in forward.items() for b in tgts}

    def test_cross_file_edges_both_directions_under_filename_swap(self):
        # rglob walks alphabetically: A.java first in both repos — but its
        # CONTENT differs (class A in repo1, class B in repo2). A two-pass
        # build yields BOTH directions in both layouts; the single-pass build
        # lost whichever cross call sat in the first-walked file.
        r1 = self._pair_repo("A.java", "B.java")
        r2 = self._pair_repo("B.java", "A.java")   # contents swapped
        e1 = self._edge_set(r1)
        e2 = self._edge_set(r2)
        # both repos carry the same two directed edges between the two files
        expected1 = {("src/A.java", "src/B.java"), ("src/B.java", "src/A.java")}
        expected2 = {("src/A.java", "src/B.java"), ("src/B.java", "src/A.java")}
        self.assertEqual(e1, expected1)
        self.assertEqual(e2, expected2)

class TestWalkSourcesLimitQuota(unittest.TestCase):
    """H6: the walk quota counts SOURCE files only; cap hit warns on stderr and
    raises the limit_hit accumulator (never a silent stop). Non-source assets
    (.txt/…) MUST NOT consume quota — discover's max_files+1 truncated sentinel
    is built on source-only counting."""

    def _repo(self, files):
        repo = Path(tempfile.mkdtemp(prefix="mgh_lim_"))
        for name, content in files:
            p = repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        return repo

    def test_non_source_files_do_not_consume_quota(self):
        es = _load("expand_scope")
        repo = self._repo([("a.txt", "x"), ("b.txt", "x"), ("c.txt", "x"),
                           ("d.txt", "x"), ("e.java", "class E {}"),
                           ("f.java", "class F {}")])
        got = {p.name for p, _ in es.walk_sources(repo, limit_files=5)}
        self.assertEqual(got, {"e.java", "f.java"})   # before: only e.java

    def test_cap_hit_warns_and_flags(self):
        import contextlib, io
        es = _load("expand_scope")
        repo = self._repo([("a.java", "class A {}"), ("b.java", "class B {}"),
                           ("c.java", "class C {}")])
        limit_hit = [False]
        err = io.StringIO()
        got = set()
        with contextlib.redirect_stderr(err):
            for p, _ in es.walk_sources(repo, limit_files=2, limit_hit=limit_hit):
                got.add(p.name)
        self.assertEqual(got, {"a.java", "b.java"})
        self.assertTrue(limit_hit[0])
        self.assertIn("limit", err.getvalue().lower())

    def test_discover_truncated_sentinel_on_mixed_repo(self):
        # mixed repo: 2 .txt + 3 .java with --max-files 2 — before the fix the
        # quota was eaten by the .txt files, the sentinel never fired, and 2 of
        # the 3 source files were silently dropped (truncated:false).
        import contextlib, importlib.util, io, json
        repo = self._repo([("a.txt", "x"), ("b.txt", "x"),
                           ("c.java", 'class C { @PreAuthorize("x") void m() {} }'),
                           ("d.java", 'class D { @PreAuthorize("x") void m() {} }'),
                           ("e.java", 'class E { @PreAuthorize("x") void m() {} }')])
        outdir = Path(tempfile.mkdtemp(prefix="mgh_tr_out_"))
        spec = importlib.util.spec_from_file_location(
            "dc_tr", SCRIPTS / "discover_controls.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = sys.argv
        sys.argv = ["discover_controls.py", "--repo", str(repo), "--out", str(outdir),
                    "--max-files", "2"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                mod.main()
        finally:
            sys.argv = old
        summary = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertTrue(summary.get("truncated"))

class TestScopeAmbiguityFailLoud(unittest.TestCase):
    """H7: --path to a nonexistent dir / --package with zero matching dirs exit
    2 with a recipe — NEVER a silent empty-seed "success" (a typo'd scope
    produced a wrong 'no controls here' conclusion). A dir that EXISTS but has
    no source files stays exit 0 + empty note."""

    def setUp(self):
        import tempfile
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_h7_"))
        (self.repo / "src" / "pay").mkdir(parents=True)
        (self.repo / "src" / "pay" / "A.java").write_text(
            "class A {}", encoding="utf-8")
        self.tmp_out = Path(tempfile.mkdtemp(prefix="mgh_h7o_")) / "scope.json"

    def _run_es(self, *args):
        import contextlib, importlib.util, io
        spec = importlib.util.spec_from_file_location(
            "es_h7", SCRIPTS / "expand_scope.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        argv = ["expand_scope.py", "--repo", str(self.repo),
                "--out", str(self.tmp_out), *args]
        old, sys.argv = sys.argv, argv
        buf, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                rc = mod.main()
        finally:
            sys.argv = old
        return rc, buf.getvalue(), err.getvalue()

    def test_nonexistent_path_exit_2(self):
        rc, _, err = self._run_es("--path", "src/paymant")   # typo
        self.assertEqual(rc, 2)
        self.assertIn("src/paymant", err)

    def test_no_match_package_exit_2(self):
        rc, _, err = self._run_es("--package", "com.acme.nomatch")
        self.assertEqual(rc, 2)
        self.assertIn("com.acme.nomatch", err)

    def test_existing_dir_without_sources_stays_empty_success(self):
        (self.repo / "src" / "empty").mkdir(parents=True)
        rc, out, _ = self._run_es("--path", "src/empty")
        self.assertEqual(rc, 0)
        self.assertIn("empty seed set", out)


class TestPruningIgnoresAncestors(unittest.TestCase):
    """M8: pruning (EXCLUDE_DIR + dot-prefix) judges repo-RELATIVE parts only —
    a repo placed under a `build`/`.cache`-named ANCESTOR still scans. Before:
    absolute-parts pruning emptied the whole repo silently (exit 0, zero
    candidates). Covers walk_sources AND collect_dir (the shared chokepoints)."""

    def test_walk_sources_under_excluded_named_ancestor(self):
        import tempfile
        outer = Path(tempfile.mkdtemp(prefix="mgh_m8a_"))
        repo = outer / "build" / "repo"
        repo.mkdir(parents=True)
        (repo / "A.java").write_text("class A {}", encoding="utf-8")
        es = _load("expand_scope")
        self.assertEqual([p.name for p, _ in es.walk_sources(repo)], ["A.java"])

    def test_walk_sources_under_dot_prefixed_ancestor(self):
        import tempfile
        outer = Path(tempfile.mkdtemp(prefix="mgh_m8b_"))
        repo = outer / ".cache" / "repo"
        repo.mkdir(parents=True)
        (repo / "A.java").write_text("class A {}", encoding="utf-8")
        es = _load("expand_scope")
        self.assertEqual([p.name for p, _ in es.walk_sources(repo)], ["A.java"])

    def test_collect_dir_under_excluded_named_ancestor(self):
        import tempfile
        outer = Path(tempfile.mkdtemp(prefix="mgh_m8c_"))
        repo = outer / "build" / "repo"
        repo.mkdir(parents=True)
        (repo / "A.java").write_text("class A {}", encoding="utf-8")
        es = _load("expand_scope")
        self.assertEqual(es.collect_dir(repo, repo), ["A.java"])


if __name__ == "__main__":
    unittest.main()
