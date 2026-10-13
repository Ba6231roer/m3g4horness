#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plan_aggregate.py — hard-budget aggregate map-reduce gate.

Asserts: ≤ budget → needs_reduce=false (single-context path); > budget → needs_reduce=true,
each shard ≤ budget, pending[] carries input_path; paging shrunk/effective_limit; t2 sharding
by category, scout-merge by candidate-granularity greedy packing (hard bound); absolute paths.
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


PA = _load("plan_aggregate")


class _Agg:
    def __init__(self):
        self.target = Path(tempfile.mkdtemp(prefix="mgh_pa_"))
        self.init = self.target / ".mgh-init"
        self.init.mkdir(parents=True, exist_ok=True)

    def write_t1(self, records):
        cp = self.init / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(records):
            (cp / f"unit-{i:03d}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def write_scout(self, records):
        cp = self.init / "checkpoints" / "scout"
        cp.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(records):
            (cp / f"scout-{i:03d}.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    def run(self, *extra):
        argv = ["plan_aggregate.py", "--init-dir", str(self.init)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = PA.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()


SMALL = [{"category": "authorization", "name": "a", "kind": "auth"},
         {"category": "crypto", "name": "b", "kind": "other"}]


class TestPlanAggregateT2(unittest.TestCase):
    def setUp(self):
        self.a = _Agg()

    def test_under_budget_single_context(self):
        self.a.write_t1(SMALL)
        code, out, _ = self.a.run("--node", "t2", "--budget", "100000")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertFalse(d["needs_reduce"])
        self.assertEqual(d["pending"], [])
        self.assertNotIn("rollup", d)
        # needs_reduce=false path is byte-identical to the pre-map-reduce release: the new
        # enumeration fields (repo / failed_marker) are emitted ONLY on the needs_reduce=true path.
        self.assertNotIn("repo", d)
        self.assertNotIn("failed_marker", d)

    def test_over_budget_needs_reduce_shards_by_category(self):
        # ① an over-budget category splits into deterministic ≤-budget parts;
        # ② mixed categories: only the over-budget ones split — a category
        # within budget keeps its whole-category shard_id + part fields 0/1.
        records = [{"category": "authorization", "name": f"n{i}", "kind": "auth", "pad": "x" * 2000}
                   for i in range(3)]
        records += [{"category": "crypto", "name": f"m{i}", "kind": "auth", "pad": "x" * 2000}
                    for i in range(3)]
        records += [{"category": "csrf", "name": f"k{i}", "kind": "auth", "pad": "x" * 500}
                    for i in range(3)]
        self.a.write_t1(records)
        shards_dir = self.a.init / "shards"
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(shards_dir))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertEqual(d["shards"], 5)  # authorization×2 + crypto×2 + csrf×1
        by_sid = {item["shard_id"]: item for item in d["pending"]}
        self.assertEqual(sorted(by_sid),
                         ["t2-authorization-part00", "t2-authorization-part01",
                          "t2-crypto-part00", "t2-crypto-part01", "t2-csrf"])
        for item in d["pending"]:
            self.assertLessEqual(item["bytes"], 4500)
            self.assertFalse(item["oversize"])  # dispatched t2 shards are ALWAYS ≤ budget
            self.assertEqual(item["slimmed"], {})  # no atomic oversize here
            self.assertTrue(Path(item["input_path"]).is_absolute())
            self.assertTrue(Path(item["checkpoint_path"]).is_absolute())
            self.assertTrue(item["done_marker"].endswith(".done"))
        a0, a1 = by_sid["t2-authorization-part00"], by_sid["t2-authorization-part01"]
        self.assertEqual((a0["part_index"], a0["part_count"]), (0, 2))
        self.assertEqual((a1["part_index"], a1["part_count"]), (1, 2))
        csrf = by_sid["t2-csrf"]
        self.assertEqual((csrf["part_index"], csrf["part_count"]), (0, 1))
        self.assertEqual(csrf["categories"], ["csrf"])
        self.assertIn("rollup", d)
        self.assertTrue(d["rollup"]["output"].endswith("controls_inventory.json"))
        # envelope carries the part identity (unsplit = 0/1); parts sum to the
        # whole category's record set
        body = json.loads(Path(csrf["input_path"]).read_text(encoding="utf-8"))
        self.assertEqual(body["part_index"], 0)
        self.assertEqual(body["part_count"], 1)
        total_auth = sum(
            len(json.loads(Path(by_sid[s]["input_path"]).read_text(encoding="utf-8"))["records"])
            for s in ("t2-authorization-part00", "t2-authorization-part01"))
        self.assertEqual(total_auth, 3)

    def test_part_split_is_deterministic(self):
        # ③ same records → same part partition, byte-identical materialized inputs
        records = [{"category": "authorization", "name": f"n{i}", "kind": "auth", "pad": "p" * 900}
                   for i in range(5)]
        self.a.write_t1(records)
        layout, blobs = [], []
        for run in range(2):
            sd = self.a.init / f"shards-{run}"
            code, out, _ = self.a.run("--node", "t2", "--budget", "3000", "--materialize", str(sd))
            self.assertEqual(code, 0)
            d = json.loads(out)
            layout.append([(i["shard_id"], i["part_index"], i["part_count"], i["bytes"])
                           for i in d["pending"]])
            blobs.append({i["shard_id"]: Path(i["input_path"]).read_bytes()
                          for i in d["pending"]})
        self.assertEqual(layout[0], layout[1])
        self.assertEqual(blobs[0], blobs[1])

    def test_atomic_oversize_record_slimmed_at_materialization(self):
        # ④ a single record > budget is slim-projected (prose fields only) —
        # evidence anchors untouched, t1 original NEVER rewritten, shard ≤ budget
        rec = {"category": "authorization", "name": "big", "kind": "auth",
               "description": "D" * 90000,
               "usage": "U" * 5000, "protects": ["P" * 100] * 100,
               "gaps": ["G" * 50] * 60,
               "entry_points": [f"ep{i}" for i in range(40)],
               "evidence": [{"file": "src/auth/Filter.java", "line": 42,
                             "anchor": "Filter:doFilter"}],
               "pad": "x" * 300}
        self.a.write_t1([rec])
        t1_file = self.a.init / "checkpoints" / "t1" / "unit-000.json"
        original = t1_file.read_bytes()
        code, out, _ = self.a.run("--node", "t2", "--budget", "16384", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(len(d["pending"]), 1)
        item = d["pending"][0]
        self.assertEqual(item["shard_id"], "t2-authorization-part00")
        self.assertEqual((item["part_index"], item["part_count"]), (0, 1))
        self.assertLessEqual(item["bytes"], 16384)
        self.assertFalse(item["oversize"])
        self.assertTrue(item["slimmed"])
        slim_entry = next(iter(item["slimmed"].values()))
        self.assertGreater(slim_entry["original_bytes"], 16384)
        self.assertIn("description", slim_entry["truncated"])
        self.assertIn("entry_points", slim_entry["truncated"])
        # projection touches ONLY the materialized input — the t1 original is intact
        self.assertEqual(t1_file.read_bytes(), original)
        body = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))
        slim_rec = body["records"][0]
        self.assertEqual(slim_rec["_slimmed"]["description"], 90002)  # "D"*90000 + quotes
        self.assertLessEqual(PA._byte_len(slim_rec["description"]), 4096)
        self.assertTrue(slim_rec["description"].endswith("…"))
        self.assertEqual(slim_rec["evidence"], rec["evidence"])  # anchors NEVER truncated
        self.assertEqual(len(slim_rec["entry_points"]), 16)
        self.assertEqual(slim_rec["pad"], "x" * 300)  # unknown fields untouched

    def test_atomic_oversize_beyond_slim_exits_2(self):
        # ⑤ pathological record (structural field over budget) → exit 2,
        # stderr names the record file + bytes, zero stdout listing (no dispatch)
        rec = {"category": "authorization", "name": "patho", "kind": "auth",
               "evidence": [{"file": "x" * 90000, "line": 1}]}
        self.a.write_t1([rec])
        code, out, err = self.a.run("--node", "t2", "--budget", "8192")
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("unit-000.json", err)
        self.assertIn("atomic-oversize", err)
        # disclosed size = MATERIALIZED caliber (the file the subagent would read),
        # not the compact serialization
        expected_b = PA._materialized_bytes(PA._t2_body(
            "t2-authorization-part00", "authorization",
            [{**rec, "__source_file": "unit-000.json"}], 0, 1))
        self.assertIn(f"({expected_b}B > 8192B)", err)

    def test_marker_aware_part_shards(self):
        # ⑥ part shards converge through the same marker-aware re-list: a
        # finished part drops out of pending, summary_paths stays the full set
        records = [{"category": "authorization", "name": f"n{i}", "kind": "auth", "pad": "x" * 2000}
                   for i in range(3)]
        self.a.write_t1(records)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual((d["shards"], d["total"]), (2, 2))
        done_item = next(i for i in d["pending"] if i["part_index"] == 0)
        Path(done_item["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(done_item["done_marker"]).write_text("{}", encoding="utf-8")
        code2, out2, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                    str(self.a.init / "shards"))
        self.assertEqual(code2, 0)
        d2 = json.loads(out2)
        self.assertEqual(d2["done"], 1)
        self.assertEqual(d2["total"], 2)
        self.assertEqual([i["shard_id"] for i in d2["pending"]],
                         ["t2-authorization-part01"])
        # full shard-summary set rides the manifest (stdout carries only its path)
        manifest = json.loads(Path(d2["rollup"]["summary_paths_manifest"])
                              .read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["summary_paths"]), 2)

    def test_small_repo_stdout_byte_identical(self):
        # ⑦ needs_reduce=false path is BYTE-identical to the pre-part-split
        # release (no repo/part_index/part_count/slimmed fields ever appear)
        self.a.write_t1(SMALL)
        # total_bytes counts the records as read from disk (incl. __source_file)
        total = PA._byte_len([{**r, "__source_file": f"unit-{i:03d}.json"}
                              for i, r in enumerate(SMALL)])
        expected = (
            '{"node": "t2", "total_bytes": %d, "budget": 100000, "needs_reduce": false, '
            '"shards": 0, "pending": [], "truncated": false, "offset": 0, "limit": 0, '
            '"effective_limit": 0, "shrunk": false, "note": "aggregate input %dB <= budget '
            '100000B — use single-context init-synthesis"}' % (total, total))
        code, out, _ = self.a.run("--node", "t2", "--budget", "100000")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), expected)

    def test_t2_enumeration_fields_repo_and_failed_marker(self):
        records = [{"category": "authorization", "name": f"n{i}", "kind": "auth", "pad": "x" * 2000}
                   for i in range(2)]
        records += [{"category": "crypto", "name": f"m{i}", "kind": "auth", "pad": "y" * 2000}
                    for i in range(2)]
        self.a.write_t1(records)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        # repo = --init-dir resolve parent == <target> absolute root (dispatcher anchor)
        self.assertEqual(Path(d["repo"]).resolve(), self.a.target.resolve())
        self.assertTrue(Path(d["repo"]).is_absolute())
        self.assertTrue(d["pending"])
        for item in d["pending"]:
            self.assertIn("failed_marker", item)
            fm = Path(item["failed_marker"])
            self.assertTrue(fm.is_absolute())
            # failed_marker: same directory as done_marker, filename `.<shard_id>.json.failed`
            self.assertEqual(fm.parent, Path(item["done_marker"]).parent)
            self.assertTrue(item["failed_marker"].endswith(f".{item['shard_id']}.json.failed"))
            # unsplit category shards carry the part identity 0/1
            self.assertEqual((item["part_index"], item["part_count"]), (0, 1))

    def test_t2_include_failed_relists_failed_shard_canonical(self):
        # --include-failed (t2): a shard whose dot-prefixed .failed marker exists
        # re-enters pending[] under its canonical shard_id with the same
        # forward-derived marker path; failed stays counted, done stays 0
        records = [{"category": "authorization", "name": f"n{i}", "kind": "auth",
                    "pad": "x" * 2000} for i in range(2)]
        records += [{"category": "crypto", "name": f"m{i}", "kind": "auth",
                     "pad": "y" * 2000} for i in range(2)]
        self.a.write_t1(records)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        victim = json.loads(out)["pending"][0]
        fm = Path(victim["failed_marker"])
        fm.parent.mkdir(parents=True, exist_ok=True)
        fm.write_text(json.dumps({"unit": victim["shard_id"], "reason": "r",
                                  "tier": "t2"}), encoding="utf-8")
        # default: the failed shard is terminal (excluded, counted)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"))
        d = json.loads(out)
        self.assertNotIn(victim["shard_id"],
                         [i["shard_id"] for i in d["pending"]])
        self.assertEqual(d["failed"], 1)
        # opt-in: canonical re-entry
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"), "--include-failed")
        self.assertEqual(code, 0)
        d = json.loads(out)
        relisted = {i["shard_id"]: i for i in d["pending"]}
        self.assertIn(victim["shard_id"], relisted)
        self.assertEqual(relisted[victim["shard_id"]]["failed_marker"],
                         str(fm))
        self.assertEqual(d["failed"], 1)
        self.assertEqual(d["done"], 0)

    def test_t2_pending_excludes_terminal_shards_and_counts(self):
        records = [{"category": "authorization", "name": "a", "kind": "auth", "pad": "x" * 2000},
                   {"category": "authorization", "name": "a2", "kind": "auth", "pad": "x" * 2000},
                   {"category": "crypto", "name": "b", "kind": "auth", "pad": "y" * 2000},
                   {"category": "crypto", "name": "b2", "kind": "auth", "pad": "y" * 2000},
                   {"category": "csrf", "name": "c", "kind": "auth", "pad": "z" * 2000},
                   {"category": "csrf", "name": "c2", "kind": "auth", "pad": "z" * 2000}]
        self.a.write_t1(records)
        code, out, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                  str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertEqual(d["shards"], 3)   # full set disclosed
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["done"], 0)
        self.assertEqual(d["failed"], 0)
        self.assertEqual(len(d["pending"]), 3)
        # 2 shards finish (touch .done), 1 fails (touch .failed) → pending excludes all three
        shard_cp = self.a.init / "checkpoints" / "t2" / "shards"
        done_markers, failed_markers = [], []
        for item in d["pending"]:
            if item["categories"][0] in ("authorization", "crypto"):
                Path(item["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
                Path(item["done_marker"]).write_text("{}", encoding="utf-8")
                done_markers.append(item)
            else:
                Path(item["failed_marker"]).parent.mkdir(parents=True, exist_ok=True)
                Path(item["failed_marker"]).write_text("{}", encoding="utf-8")
                failed_markers.append(item)
        code2, out2, _ = self.a.run("--node", "t2", "--budget", "4500", "--materialize",
                                    str(self.a.init / "shards"))
        self.assertEqual(code2, 0)
        d2 = json.loads(out2)
        self.assertTrue(d2["needs_reduce"])
        self.assertEqual(d2["shards"], 3)     # disclosure still full
        self.assertEqual(d2["total"], 3)
        self.assertEqual(d2["done"], 2)
        self.assertEqual(d2["failed"], 1)
        self.assertEqual(d2["pending"], [])   # marker-aware: nothing left to dispatch
        # manifest still carries the full shard set (rollup eats all)
        manifest = json.loads(Path(d2["rollup"]["summary_paths_manifest"])
                              .read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["summary_paths"]), 3)
        manifest1 = json.loads(Path(d["rollup"]["summary_paths_manifest"])
                               .read_text(encoding="utf-8"))
        self.assertEqual(len(manifest1["summary_paths"]), 3)

    def test_scout_merge_marker_aware_terminal_exclusion(self):
        """scout-merge is dispatcher-consumed: a shard whose .done marker exists
        drops out of pending[], total/done/failed appear, summary_paths stays full."""
        a = _Agg()
        records = [{"batch_id": f"scout-{i:03d}", "candidates": [{"pad": "y" * 2000}]}
                   for i in range(4)]
        a.write_scout(records)
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertGreater(d["shards"], 1)
        self.assertEqual(d["total"], d["shards"])
        self.assertEqual((d["done"], d["failed"]), (0, 0))
        self.assertEqual(len(d["pending"]), d["shards"])
        # terminal-mark one shard → re-list excludes it, counts update
        first_done = d["pending"][0]["done_marker"]
        Path(first_done).parent.mkdir(parents=True, exist_ok=True)
        Path(first_done).write_text("{}", encoding="utf-8")
        _, out2, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                           str(a.init / "shards"))
        d2 = json.loads(out2)
        self.assertEqual(d2["done"], 1)
        self.assertEqual(d2["total"], d["shards"])
        self.assertEqual([i["shard_id"] for i in d2["pending"]],
                         [i["shard_id"] for i in d["pending"][1:]])
        manifest = json.loads(Path(d2["rollup"]["summary_paths_manifest"])
                              .read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["summary_paths"]), d["shards"])

    def test_paging_and_shrink(self):
        # each category's 2 small records stay within the 500B budget (no part
        # split / no atomic oversize); the aggregate still exceeds it
        records = [{"category": f"cat-{i}", "name": f"n{j}", "kind": "auth", "pad": "x" * 100}
                   for i in range(6) for j in range(2)]
        self.a.write_t1(records)
        self.a.run("--node", "t2", "--budget", "500", "--materialize", str(self.a.init / "shards"))
        _, out, _ = self.a.run("--node", "t2", "--budget", "500", "--offset", "0", "--limit", "2",
                               "--materialize", str(self.a.init / "shards"))
        d = json.loads(out)
        self.assertLessEqual(len(d["pending"]), 2)
        _, out2, _ = self.a.run("--node", "t2", "--budget", "500", "--orch-budget-bytes", "60",
                                "--materialize", str(self.a.init / "shards"))
        self.assertTrue(json.loads(out2)["shrunk"])

    def test_empty_records_single_context(self):
        code, out, _ = self.a.run("--node", "t2", "--budget", "1000")
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["needs_reduce"])


class TestT2MaterializedCaliber(unittest.TestCase):
    """H8: the t2 shard budget is measured on the MATERIALIZED caliber — the same
    envelope + indent + CRLF serialization that `_write_shard_input` puts on disk —
    so every dispatched shard's FILE is ≤ budget. Pre-fix the t2 packer measured
    compact `json.dumps` bytes (scout-merge already used the materialized family):
    a 96KB-class budget materialized ~1.23× over, and `pending[].bytes` under-
    reported (compact) instead of equaling the file's `st_size`. `total_bytes`
    (the needs_reduce disclosure of raw input scale) stays compact — it is not
    the dispatch bound."""

    def setUp(self):
        self.a = _Agg()

    def _records(self, n=10):
        # many short fields → materialized ≈ 1.47× compact (real checkpoint records
        # have the same many-small-fields shape)
        recs = [{"category": "authorization", "name": f"n{i}", "kind": "auth",
                 **{f"f{j}": "v" * 12 for j in range(12)}} for i in range(n)]
        return recs

    def test_dispatched_shard_file_within_budget_and_bytes_eq_st_size(self):
        self.a.write_t1(self._records())
        shards_dir = self.a.init / "shards"
        code, out, _ = self.a.run("--node", "t2", "--budget", "2000",
                                  "--materialize", str(shards_dir))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertTrue(d["pending"])
        for item in d["pending"]:
            fsize = Path(item["input_path"]).stat().st_size
            self.assertLessEqual(fsize, 2000,
                                 f"{item['shard_id']}: materialized {fsize}B > budget 2000B")
            self.assertEqual(item["bytes"], fsize)       # bytes backfilled = st_size
            self.assertFalse(item["oversize"])
        # the whole category's record set is still covered exactly once
        seen = sum(len(json.loads(Path(i["input_path"]).read_text(encoding="utf-8"))["records"])
                   for i in d["pending"])
        self.assertEqual(seen, 10)


class TestRollupManifest(unittest.TestCase):
    """M5: needs_reduce stdout NEVER carries the full `summary_paths` array (1000
    shards ≈ 100KB punches through the 64KB orchestrator single-reply budget);
    the rollup section carries the manifest ABSOLUTE path instead, and the
    manifest FILE carries the full path set (atomic, idempotent overwrite) for
    the rollup subagent to Read. needs_reduce:false stays byte-identical (no
    manifest, no rollup key)."""

    def setUp(self):
        self.a = _Agg()

    def _many_categories(self, n=50):
        # one small record per category → one ≤-budget shard per category
        return [{"category": f"crypto-{i:02d}", "name": f"n{i}", "kind": "other",
                 "pad": "p" * 200} for i in range(n)]

    def _run(self, *extra):
        return self.a.run("--node", "t2", *extra)

    def test_stdout_carries_manifest_not_array(self):
        self.a.write_t1(self._many_categories())
        code, out, _ = self._run("--budget", "4000", "--orch-budget-bytes", "4000",
                                 "--materialize", str(self.a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertEqual(d["shards"], 50)
        self.assertEqual(set(d["rollup"].keys()),
                         {"summary_paths_manifest", "output", "done_marker"})
        self.assertNotIn("summary_paths", d["rollup"])
        self.assertTrue(Path(d["rollup"]["summary_paths_manifest"]).is_absolute())
        # single-reply budget: the stdout stays within the page budget + a small
        # FIXED envelope (repo/total_bytes/note/manifest-path — constant, does not
        # scale with shard count; pre-fix the 50-path array alone added ~6KB here)
        self.assertLessEqual(len(out), 4000 + 1024,
                             "stdout exceeded --orch-budget-bytes + fixed envelope")

    def test_manifest_carries_full_path_set_idempotently(self):
        self.a.write_t1(self._many_categories())
        _, out1, _ = self._run("--budget", "4000", "--materialize",
                               str(self.a.init / "shards"))
        mpath = Path(json.loads(out1)["rollup"]["summary_paths_manifest"])
        self.assertEqual(mpath, (self.a.init / "checkpoints" / "t2" / "shards"
                                 / "rollup_manifest.json"))
        body1 = mpath.read_text(encoding="utf-8")
        manifest = json.loads(body1)
        self.assertEqual(len(manifest["summary_paths"]), 50)
        self.assertTrue(all(Path(p).is_absolute() for p in manifest["summary_paths"]))
        self.assertTrue(manifest["output"].endswith("controls_inventory.json"))
        self.assertTrue(manifest["done_marker"].endswith("synthesis.json.done"))
        # idempotent: a re-run (markers advanced) rewrites the SAME content
        d2_item = json.loads(out1)["pending"][0]
        Path(d2_item["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(d2_item["done_marker"]).write_text("{}", encoding="utf-8")
        _, out2, _ = self._run("--budget", "4000", "--materialize",
                               str(self.a.init / "shards"))
        d2 = json.loads(out2)
        self.assertEqual(d2["done"], 1)          # marker-aware counts still work
        self.assertEqual(Path(d2["rollup"]["summary_paths_manifest"]).read_text(
            encoding="utf-8"), body1)            # FULL set, unchanged

    def test_under_budget_no_manifest_byte_identical(self):
        self.a.write_t1(SMALL)
        code, out, _ = self._run("--budget", "100000")
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertFalse(d["needs_reduce"])
        self.assertNotIn("rollup", d)
        self.assertFalse((self.a.init / "checkpoints" / "t2" / "shards"
                          / "rollup_manifest.json").exists())


class TestPlanAggregateScoutMerge(unittest.TestCase):
    def test_over_budget_batches_packed_into_shards(self):
        a = _Agg()
        records = [{"batch_id": f"scout-{i:03d}", "candidates": [{"pad": "y" * 2000}]}
                   for i in range(8)]
        a.write_scout(records)
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        self.assertGreater(d["shards"], 1)
        self.assertTrue(d["rollup"]["output"].endswith("scout_candidates.json"))
        self.assertTrue(d["rollup"]["done_marker"].endswith("merge.json.done"))
        # `batches` = deduped batch_id list the shard covers (int count retired);
        # every candidate lands exactly once across shards, in glob order.
        all_batches = [b for item in d["pending"] for b in item["batches"]]
        self.assertEqual(sorted(set(all_batches)), sorted(all_batches))
        seen = [c["pad"] for item in d["pending"]
                for rec in json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))["records"]
                for c in rec.get("candidates", [])]
        self.assertEqual(len(seen), 8)
        # HARD invariant: the MATERIALIZED file ≤ budget, and bytes == file size
        for item in d["pending"]:
            self.assertLessEqual(item["bytes"], 3000)
            self.assertEqual(item["bytes"], Path(item["input_path"]).stat().st_size)

    def test_oversize_batch_splits_across_shards(self):
        # ① one batch whose candidates exceed the budget is cut across shards at
        # candidate granularity; its `unresolved` rides the shard of its LAST candidate.
        a = _Agg()
        a.write_scout([{"batch_id": "scout-000",
                        "candidates": [{"id": i, "pad": "y" * 1500} for i in range(6)],
                        "unresolved": ["src/X.java"]}])
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertGreater(d["shards"], 1)
        ids, shards_with_unres = [], []
        for item in d["pending"]:
            recs = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))["records"]
            self.assertEqual(len(recs), 1)
            ids += [c["id"] for c in recs[0].get("candidates", [])]
            if "unresolved" in recs[0]:
                shards_with_unres.append(item["shard_id"])
        self.assertEqual(ids, list(range(6)))            # no loss, no duplication
        self.assertEqual(shards_with_unres, [d["pending"][-1]["shard_id"]])
        self.assertEqual(d["pending"][0]["batches"], ["scout-000"])
        # every record keeps its batch identity across the split
        for item in d["pending"]:
            recs = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))["records"]
            self.assertEqual(recs[0]["batch_id"], "scout-000")

    def test_atomic_oversize_candidate_slimmed(self):
        # ② a single candidate > budget is prose-slimmed at materialization
        # (evidence_snippet/snippet/entry_points only); structural fields and the
        # checkpoints/scout original NEVER touched; shard carries `slimmed`.
        a = _Agg()
        cand = {"file": "src/Auth.java", "line": 7, "category": "authorization",
                "anchor": {"class": "Auth", "method": "check"}, "source": "scout",
                "evidence_snippet": "E" * 20000, "snippet": "S" * 1000,
                "entry_points": [f"ep{i}" for i in range(40)]}
        a.write_scout([{"batch_id": "scout-000", "candidates": [cand]}])
        cp_file = a.init / "checkpoints" / "scout" / "scout-000.json"
        original = cp_file.read_bytes()
        code, out, _ = a.run("--node", "scout-merge", "--budget", "8192", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(len(d["pending"]), 1)
        item = d["pending"][0]
        self.assertFalse(item["oversize"])
        self.assertLessEqual(item["bytes"], 8192)
        self.assertEqual(item["bytes"], Path(item["input_path"]).stat().st_size)
        self.assertEqual(cp_file.read_bytes(), original)  # original NEVER rewritten
        slim = item["slimmed"]["scout-000.json#0"]
        self.assertGreater(slim["original_bytes"], 8192)
        self.assertIn("evidence_snippet", slim["truncated"])
        self.assertIn("entry_points", slim["truncated"])
        self.assertNotIn("snippet", slim["truncated"])  # under cap → untouched
        body = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))
        sc = body["records"][0]["candidates"][0]
        self.assertEqual(sc["anchor"], cand["anchor"])       # structural fields intact
        self.assertEqual(sc["file"], "src/Auth.java")
        self.assertEqual(len(sc["entry_points"]), 16)
        self.assertLessEqual(PA._byte_len(sc["evidence_snippet"]), 4096)
        self.assertEqual(sc["snippet"], "S" * 1000)
        self.assertEqual(sc["_slimmed"]["evidence_snippet"], 20002)  # "E"*20000 + quotes

    def test_atomic_oversize_candidate_beyond_slim_exits_2(self):
        # ③ pathological candidate (STRUCTURAL fields alone exceed budget) →
        # exit 2 fail-loud, zero stdout, zero materialized files.
        a = _Agg()
        a.write_scout([{"batch_id": "scout-000",
                        "candidates": [{"file": "x" * 90000, "line": 1,
                                        "category": "crypto"}]}])
        shards_dir = a.init / "shards"
        code, out, err = a.run("--node", "scout-merge", "--budget", "8192",
                               "--materialize", str(shards_dir))
        self.assertEqual(code, 2)
        self.assertEqual(out.strip(), "")
        self.assertIn("atomic-oversize", err)
        self.assertIn("scout-000.json", err)
        self.assertFalse(shards_dir.exists())

    def test_marker_aware_scout_relist(self):
        # ④ dispatcher convergence: done/failed terminal shards excluded from
        # re-list; counts marker-derived; --include-failed re-enters canonically.
        a = _Agg()
        a.write_scout([{"batch_id": f"scout-{i:03d}", "candidates": [{"pad": "y" * 2000}]}
                       for i in range(4)])
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        victim = d["pending"][1]
        Path(victim["done_marker"]).parent.mkdir(parents=True, exist_ok=True)
        Path(victim["done_marker"]).write_text("{}", encoding="utf-8")
        fm = Path(d["pending"][2]["failed_marker"])
        fm.write_text(json.dumps({"unit": victim["shard_id"], "reason": "r",
                                  "tier": "scout-merge"}), encoding="utf-8")
        _, out2, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                           str(a.init / "shards"))
        d2 = json.loads(out2)
        self.assertEqual((d2["done"], d2["failed"]), (1, 1))
        self.assertNotIn(victim["shard_id"], [i["shard_id"] for i in d2["pending"]])
        _, out3, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                           str(a.init / "shards"), "--include-failed")
        d3 = json.loads(out3)
        relisted = {i["shard_id"]: i for i in d3["pending"]}
        failed_sid = fm.name.removeprefix(".").removesuffix(".json.failed")
        self.assertIn(failed_sid, relisted)
        self.assertEqual(relisted[failed_sid]["failed_marker"], str(fm))
        self.assertEqual(d3["failed"], 1)
        self.assertEqual(d3["done"], 1)

    def test_scout_merge_under_budget_stdout_byte_identical(self):
        # ⑤ ≤ budget → needs_reduce=false path byte-identical to pre-adoption
        # release (no repo/total/done/failed/shard fields leak in).
        a = _Agg()
        records = [{"batch_id": "scout-000", "candidates": [{"pad": "y" * 10}]}]
        a.write_scout(records)
        total = PA._byte_len([{**r, "__source_file": f"scout-{i:03d}.json"}
                              for i, r in enumerate(records)])
        expected = (
            '{"node": "scout-merge", "total_bytes": %d, "budget": 3000, "needs_reduce": false, '
            '"shards": 0, "pending": [], "truncated": false, "offset": 0, "limit": 0, '
            '"effective_limit": 0, "shrunk": false, "note": "aggregate input %dB <= budget '
            '3000B — use single-context init-scout-merge"}' % (total, total))
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), expected)

    def test_scout_merge_envelope_unchanged_no_part_fields(self):
        """Part splitting stays a t2-only concept: scout-merge items/inputs carry
        no part_index/part_count (slimmed IS now present, {} when nothing was
        cut); the input envelope keeps {node, shard_id, records}."""
        a = _Agg()
        a.write_scout([{"batch_id": f"scout-{i:03d}", "candidates": [{"pad": "y" * 2000}]}
                       for i in range(4)])
        code, out, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                             str(a.init / "shards"))
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertTrue(d["needs_reduce"])
        for item in d["pending"]:
            self.assertNotIn("part_index", item)
            self.assertNotIn("part_count", item)
            self.assertEqual(item["slimmed"], {})
            body = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("part_index", body)
            self.assertNotIn("part_count", body)
            self.assertEqual(body, {"node": "scout-merge", "shard_id": item["shard_id"],
                                    "records": body["records"]})


class TestDefaultBudgetConsistency(unittest.TestCase):
    """--max-aggregate-bytes default MUST be 98304 (96KB) in EVERY declaring script,
    asserted on the `--help` contract surface (R5.1) — plan_aggregate.DEFAULT_BUDGET,
    write_runconfig / write_ut_runconfig / render_report DEFAULT_MAX_AGGREGATE_BYTES."""

    HELPERS = ("plan_aggregate.py", "write_runconfig.py", "write_ut_runconfig.py",
               "render_report.py")

    def test_help_declares_98304(self):
        import subprocess
        for script in self.HELPERS:
            with self.subTest(script=script):
                r = subprocess.run([sys.executable, str(SCRIPTS / script), "--help"],
                                   capture_output=True, text=True, encoding="utf-8")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("98304", r.stdout,
                              f"{script} --help must declare the 98304 aggregate default")

    def test_constants_are_98304(self):
        wr = _load("write_runconfig")
        wu = _load("write_ut_runconfig")
        rr = _load("render_report")
        self.assertEqual(PA.DEFAULT_BUDGET, 98304)
        self.assertEqual(wr.DEFAULT_MAX_AGGREGATE_BYTES, 98304)
        self.assertEqual(wu.DEFAULT_MAX_AGGREGATE_BYTES, 98304)
        self.assertEqual(rr.DEFAULT_MAX_AGGREGATE_BYTES, 98304)


class TestBadInput(unittest.TestCase):
    def test_negative_budget_exit2(self):
        a = _Agg()
        code, _, _ = a.run("--node", "t2", "--budget", "-1")
        self.assertEqual(code, 2)

    def test_init_dir_missing_exit1(self):
        argv = ["plan_aggregate.py", "--node", "t2", "--init-dir", "/no/such/dir"]
        old, sys.argv = sys.argv, argv
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = PA.main()
        finally:
            sys.argv = old
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
