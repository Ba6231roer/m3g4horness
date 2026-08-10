#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""ut-init deterministic runtime (subprocess, from a non-script cwd — FD3 robustness).

Covers: classify product shape, extract/rules fan-out work-lists (absolute paths), shared-script
reuse via ut path args (chunk_sources / describe_artifact — task 2.3), the documented
plan_aggregate name-binding finding (NOT reused — ut synthesize is single-context + soft budget
disclosure), and --help-as-contract."""

import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
CLASSIFY = SCRIPTS / "classify_tests.py"
LIST = SCRIPTS / "list_test_groups.py"
CHUNK = SCRIPTS / "chunk_sources.py"
DESCRIBE = SCRIPTS / "describe_artifact.py"
PLAN_AGG = SCRIPTS / "plan_aggregate.py"
RESUME_UT = SCRIPTS / "resume_ut_init_state.py"
DERIVE = SCRIPTS / "derive_mutators.py"
PY = sys.executable

SERVICE_UNIT = """\
package com.acme.service;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.InjectMocks;
@ExtendWith(MockitoExtension.class)
class UserServiceTest {
  @InjectMocks UserService s;
  @Test void t() {}
}
"""


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestUtInitRuntime(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_utr_"))
        for i in range(4):
            _write(self.repo, f"src/test/java/com/acme/service/UserService{i}Test.java",
                   SERVICE_UNIT)
        self.out = Path(tempfile.mkdtemp(prefix="mgh_utr_out_"))
        self.cwd = self.repo

    def _run(self, script, *args):
        return subprocess.run([PY, str(script), *args], cwd=str(self.cwd),
                              capture_output=True, text=True, encoding="utf-8")

    def _classify(self):
        r = self._run(CLASSIFY, "--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(r.returncode, 0, f"classify failed:\n{r.stderr}")
        return json.loads((self.out / "test_groups.json").read_text(encoding="utf-8"))

    def test_classify_product_shape(self):
        data = self._classify()
        self.assertEqual(data["repo"], str(self.repo))
        self.assertIn("groups", data)
        self.assertIsInstance(data["scanned"], int)
        self.assertIn("truncated", data)
        svc = [g for g in data["groups"] if g["layer"] == "service"]
        self.assertTrue(svc)
        for g in svc:
            self.assertIn("id", g)
            self.assertIn("uniformity", g)
            self.assertTrue(g["members"])

    def test_extract_worklist_absolute_paths(self):
        self._classify()
        r = self._run(LIST, "--tier", "extract", "--groups", str(self.out / "test_groups.json"),
                      "--checkpoints", str(self.out / "checkpoints" / "extract"),
                      "--materialize", str(self.out / "inputs" / "extract"))
        self.assertEqual(r.returncode, 0, f"list extract failed:\n{r.stderr}")
        data = json.loads(r.stdout)
        self.assertEqual(data["tier"], "extract")
        self.assertGreater(data["total"], 0)
        for item in data["pending"]:
            for key in ("input_path", "checkpoint_path", "done_marker", "failed_marker"):
                self.assertIn(key, item)
                self.assertTrue(Path(item[key]).is_absolute(),
                                f"{key} not absolute: {item[key]}")
            self.assertTrue(Path(item["input_path"]).is_file(), item["input_path"])
            self.assertEqual(data["total"], data["done"] + data["failed"] + len(data["pending"]))

    def test_extract_resume_skips_done_group_with_arrow_unit(self):
        # a `::`-containing group id is _safe_name-encoded on disk; resume detection reads the
        # canonical `unit` from the sibling record, so a done group is skipped (not re-listed).
        data = self._classify()
        group_ids = {g["id"] for g in data["groups"]}
        self.assertTrue(any("::" in gid for gid in group_ids),
                        f"expected :: group ids, got {group_ids}")
        gid = sorted(g for g in group_ids if "::" in g)[0]
        safe = gid.replace(":", "_").replace("/", "_").replace("\\", "_")
        cp_dir = self.out / "checkpoints" / "extract"
        cp_dir.mkdir(parents=True, exist_ok=True)
        (cp_dir / f"{safe}.json").write_text(json.dumps({"unit": gid}), encoding="utf-8")
        (cp_dir / f"{safe}.json.done").write_text("", encoding="utf-8")
        r = self._run(LIST, "--tier", "extract", "--groups", str(self.out / "test_groups.json"),
                      "--checkpoints", str(cp_dir), "--materialize", str(self.out / "inputs" / "extract"))
        self.assertEqual(r.returncode, 0, r.stderr)
        data2 = json.loads(r.stdout)
        self.assertEqual(data2["done"], 1)
        self.assertNotIn(gid, [p["group_id"] for p in data2["pending"]])

    def test_rules_worklist_rule_path(self):
        inv = self.out / "test_rules_inventory.json"
        inv.write_text(json.dumps({"repo": ".", "rules": [
            {"category": "junit5", "name": "x", "layer": "service", "anchor": "a.java::A.t",
             "evidence": ["a.java::A.t"], "provenance": {"groups": ["g"], "strong": 1, "weak": 0},
             "confidence": 0.8}]}), encoding="utf-8")
        r = self._run(LIST, "--tier", "rules", "--inventory", str(inv), "--format", "opencode",
                      "--target", str(self.repo), "--rules-dir", "docs/test-conventions",
                      "--checkpoints", str(self.out / "checkpoints" / "rules"),
                      "--materialize", str(self.out / "inputs" / "rules"))
        self.assertEqual(r.returncode, 0, f"list rules failed:\n{r.stderr}")
        data = json.loads(r.stdout)
        self.assertEqual(data["tier"], "rules")
        item = data["pending"][0]
        self.assertTrue(Path(item["rule_path"]).is_absolute())
        self.assertEqual(Path(item["rule_path"]).name, "junit5.md")
        self.assertIn("test-conventions", item["rule_path"])
        self.assertTrue(Path(item["input_path"]).is_file())

    def test_chunk_sources_reuse_via_ut_paths(self):
        # task 2.3: shared chunk_sources.py is path-generic — reusable for ut slices. The
        # slice_dir comes VERBATIM from list_test_groups stdout (pre-created), never invented.
        self._classify()
        lst = self._run(LIST, "--tier", "extract", "--groups", str(self.out / "test_groups.json"),
                        "--checkpoints", str(self.out / "checkpoints" / "extract"),
                        "--materialize", str(self.out / "inputs" / "extract"))
        item = json.loads(lst.stdout)["pending"][0]
        slice_dir = Path(item["slice_dir"])
        self.assertTrue(slice_dir.is_dir(), "slice_dir not pre-created")
        big = _write(self.repo, "src/test/java/com/acme/BigTest.java",
                     SERVICE_UNIT + "\n// pad\n" * 200)
        r = self._run(CHUNK, "--in", str(big), "--big-file-bytes", "1000", "--line", "2",
                      "--out", str(slice_dir / "BigTest.slice.json"))
        self.assertEqual(r.returncode, 0, f"chunk_sources reuse failed:\n{r.stderr}")
        self.assertTrue((slice_dir / "BigTest.slice.json").is_file())

    def test_describe_artifact_reuse_via_ut_paths(self):
        # task 2.3: shared describe_artifact.py is path-generic — reusable for ut products.
        self._classify()
        r = self._run(DESCRIBE, "--in", str(self.out / "test_groups.json"), "--keys")
        self.assertEqual(r.returncode, 0, f"describe_artifact reuse failed:\n{r.stderr}")
        data = json.loads(r.stdout)
        self.assertIn("groups", data.get("keys", []))

    def test_plan_aggregate_name_bound_not_reused(self):
        # task 2.3 documented finding: plan_aggregate is INIT-name-bound (--node t2 reads
        # checkpoints/t1 and writes controls_inventory.json — init products). A ut run has
        # checkpoints/extract, NOT checkpoints/t1 — so plan_aggregate sees 0 records and
        # cannot serve the ut synthesize aggregate node (extract observations ->
        # test_rules_inventory.json). ut does NOT reuse it; synthesize is single-context +
        # soft --max-aggregate-bytes disclosure + --scope fallback.
        self._classify()
        r = self._run(PLAN_AGG, "--node", "t2", "--init-dir", str(self.out), "--budget", "1000")
        self.assertEqual(r.returncode, 0)
        data = json.loads(r.stdout)
        self.assertEqual(data["total_bytes"], 2)      # empty [] (ut run has no checkpoints/t1)
        self.assertFalse(data["needs_reduce"])
        # plan_aggregate node "t2" serves INIT products (init-synthesis / controls_inventory),
        # never the ut synthesize node — this is the documented name-binding (NOT reused).
        self.assertIn("init-synthesis", data["note"])

    def test_resume_help_is_contract(self):
        r = self._run(RESUME_UT, "--help")
        self.assertEqual(r.returncode, 0)
        for f in ("--target", "--init-dir", "--run-root", "--check"):
            self.assertIn(f, r.stdout)

    def test_derive_mutators_product_shape(self):
        r = self._run(DERIVE, "--repo", str(self.repo), "--out", str(self.out))
        self.assertEqual(r.returncode, 0, f"derive_mutators failed:\n{r.stderr}")
        data = json.loads(r.stdout)
        self.assertIn("source", data)
        self.assertIn("mutators", data)
        self.assertTrue(data["mutators"])
        product = json.loads((self.out / "default_mutators.json").read_text(encoding="utf-8"))
        self.assertEqual(product["source"], data["source"])
        self.assertTrue(product["mutators"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
