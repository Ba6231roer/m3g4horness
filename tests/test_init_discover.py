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


if __name__ == "__main__":
    unittest.main()
