#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_scout_batches.py forward marker-path done/failed judgment
(fix-mgh-init-done-marker-identity, scout same-shape rewrite).

The scout enumeration previously recovered identity from each checkpoint record's
`batch_id` field with a filename-stem fallback — aligned today only because batch_ids
are clean `scout-NNN` slugs (coincidence, not structure). These tests lock the
forward-computation semantics: judgment = canonical batch_id → encoded marker path →
`is_file()`; identity NEVER from a record body or a stem (an overlong batch id's
truncated stem ≠ canonical id). Also locks list_rule_jobs' filename-decoding immunity
for overlong category names (task 2.3).

In-process (io redirect) like tests/test_list_scout_batches.py; the subprocess-level
enumeration contract is covered there. Zero runtime deps (Python >=3.10 stdlib).
"""
import contextlib, importlib.util, io, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _overlong_bid(file: str) -> str:
    """A >200-char batch_id (as if a future planner emitted path-bearing ids)."""
    return "scout-" + ("pkg/" * 40) + file + "-" + "9" * 40


_BATCHES = [
    {"batch_id": "scout-001", "targets": [{"file": "a.java"}], "bytes": 100,
     "needs_slice": []},
    {"batch_id": "scout-002", "targets": [{"file": "b.java"}], "bytes": 200,
     "needs_slice": []},
    {"batch_id": "scout-003", "targets": [{"file": "c.java"}], "bytes": 300,
     "needs_slice": []},
]


class TestScoutForwardJudgment(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_scout_batches")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_sbf_"))
        self.cp = self.d / "checkpoints" / "scout"

    def _write(self, batches):
        p = self.d / "scout_plan.json"
        p.write_text(json.dumps({"repo": str(self.d), "targets_total": len(batches),
                                 "truncated": False, "batches": batches},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, plan):
        argv = ["list_scout_batches.py", "--scout-plan", str(plan),
                "--checkpoints", str(self.cp)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_short_id_done_marker_judges_done(self):
        p = self._write(_BATCHES)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "scout-002.json.done").write_text("", encoding="utf-8")
        code, out, err = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["done"], 1)
        self.assertNotIn("scout-002", [b["batch_id"] for b in data["pending"]])
        self.assertNotIn("could not read batch_id from", err)  # old warn path deleted

    def test_overlong_batch_id_done_without_record_body(self):
        # >200-char batch_id: encoded stem truncates (≠ canonical id). A done marker +
        # record at the ENCODED path (record body lacks batch_id) must still judge done —
        # the exact failure shape that stranded the t1 tier, guarded against here.
        bid = _overlong_bid("Reader.java")
        p = self._write([{"batch_id": bid, "targets": [{"file": "r.java"}],
                          "bytes": 10, "needs_slice": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        enc = self.m._safe_name(bid)
        self.assertNotEqual(enc, bid)
        self.assertLessEqual(len(enc), 200)
        (self.cp / f"{enc}.json").write_text(json.dumps({"status": "done"}),
                                             encoding="utf-8")
        (self.cp / f"{enc}.json.done").write_text("", encoding="utf-8")
        code, out, err = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["done"], 1)                 # forward judgment: DONE
        self.assertEqual(data["pending"], [])             # NOT re-dispatched
        self.assertNotIn("could not read batch_id from", err)

    def test_failed_marker_terminal_for_overlong_id(self):
        bid = _overlong_bid("Crash.java")
        p = self._write([{"batch_id": bid, "targets": [], "bytes": 0,
                          "needs_slice": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        enc = self.m._safe_name(bid)
        (self.cp / f"{enc}.json.failed").write_text(
            json.dumps({"reason": "boom", "tier": "scout"}), encoding="utf-8")
        code, out, _ = self._run(p)
        data = json.loads(out)
        self.assertEqual(data["failed"], 1)
        self.assertEqual(data["pending"], [])

    def test_tier_level_merge_audit_markers_excluded_by_construction(self):
        # merge.json.done / audit.json.failed are tier-level expected state: they match
        # no canonical batch id → forward computation never counts them, and the orphan
        # audit excludes them by name (expected, not a legacy artifact).
        p = self._write(_BATCHES)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "merge.json.done").write_text("", encoding="utf-8")
        (self.cp / "audit.json.failed").write_text("{}", encoding="utf-8")
        code, out, err = self._run(p)
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(data["failed"], 0)
        self.assertEqual(len(data["pending"]), 3)
        self.assertNotIn("orphan marker", err)            # tier-level ≠ orphan

    def test_orphan_marker_warned_not_counted(self):
        # a legacy run's marker at a non-canonical encoded name → warn only, no count.
        p = self._write(_BATCHES)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "legacy__batch__x.json.done").write_text("", encoding="utf-8")
        code, out, err = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)
        self.assertIn("legacy__batch__x.json.done", err)

    def test_record_body_batch_id_never_load_bearing(self):
        # a record whose body claims batch_id of a DIFFERENT unit must not flip judgment:
        # no marker → pending, regardless of the body.
        p = self._write(_BATCHES)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "scout-001.json").write_text(
            json.dumps({"batch_id": "scout-001"}), encoding="utf-8")  # record, NO marker
        code, out, _ = self._run(p)
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)


class TestRuleJobsOverlongCategoryImmunity(unittest.TestCase):
    """list_rule_jobs decodes category from `<category>.<fmt>.json.done` filenames —
    no truncation encoding exists in that path (categories are clean slugs), so it is
    structurally immune to the identity-drift shape. This locks the shape (task 2.3)."""

    def setUp(self):
        self.m = _load("list_rule_jobs")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_rji_"))
        self.cp = self.d / "checkpoints" / "t3"

    def _run(self, controls, fmt="opencode"):
        p = self.d / "controls_inventory.json"
        p.write_text(json.dumps({"format": fmt, "controls": controls},
                                ensure_ascii=False), encoding="utf-8")
        argv = ["list_rule_jobs.py", "--inventory", str(p), "--format", fmt,
                "--checkpoints", str(self.cp), "--target", str(self.d)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_overlong_category_done_decoded_from_filename(self):
        # a long-but-writable category slug (~200 chars) decodes losslessly: the marker
        # filename embeds the category verbatim (no sanitize/truncate step in t3 path).
        long_cat = "audit-logging-" + "sub" * 62          # 200 chars, still a slug
        self.assertEqual(len(long_cat), 200)
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / f"{long_cat}.opencode.json.done").write_text("", encoding="utf-8")
        code, out, _ = self._run([{"name": "n", "category": long_cat}])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["done"], 1)                 # filename decode: done
        self.assertEqual(data["pending"], [])

    def test_long_category_pending_marker_path_roundtrip(self):
        long_cat = "crypto-" + "sub" * 64
        code, out, _ = self._run([{"name": "n", "category": long_cat}])
        item = json.loads(out)["pending"][0]
        # done_marker embeds the FULL category verbatim (no truncation) → a subagent
        # touching it lets the next enumeration decode the identical category back.
        self.assertEqual(Path(item["done_marker"]).name,
                         f"{long_cat}.opencode.json.done")
        self.cp.mkdir(parents=True, exist_ok=True)
        Path(item["done_marker"]).write_text("", encoding="utf-8")
        code, out, _ = self._run([{"name": "n", "category": long_cat}])
        data = json.loads(out)
        self.assertEqual(data["done"], 1)
        self.assertEqual(data["pending"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
