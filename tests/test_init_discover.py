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


class TestDiscover(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_init_"))
        _write(self.repo, "src/main/java/com/bank/api/TransferController.java", CONTROLLER)
        _write(self.repo, "src/main/java/com/bank/util/MaskUtil.java", MASK)
        _write(self.repo, "src/main/java/com/bank/crypto/AesUtil.java", CRYPTO)
        _write(self.repo, "target/gen/Generated.java", EXCLUDED)  # EXCLUDE_DIR
        _write(self.repo, "src/main/java/com/bank/api2/OrphanController.java", ISOLATED_CONTROLLER)

    def _scan(self, seed=None):
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(
            self.repo, seed, 200000, 204800, None)
        return cands, rev, fw

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


if __name__ == "__main__":
    unittest.main()
