#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plan_aggregate.py — hard-budget aggregate map-reduce gate.

Asserts: ≤ budget → needs_reduce=false (single-context path); > budget → needs_reduce=true,
each shard ≤ budget, pending[] carries input_path; paging shrunk/effective_limit; t2 sharding
by category, scout-merge by batch cluster; absolute paths.
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
        expected_b = PA._byte_len([{**rec, "__source_file": "unit-000.json"}])
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
        self.assertEqual(len(d2["rollup"]["summary_paths"]), 2)

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
        # summary_paths still carries the full shard set (rollup eats all)
        self.assertEqual(len(d2["rollup"]["summary_paths"]), 3)
        self.assertEqual(len(d["rollup"]["summary_paths"]), 3)

    def test_scout_merge_not_marker_aware(self):
        """scout-merge (non-goal, hand-paged) keeps listing terminal shards — no total/done/failed."""
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
        # terminal-mark a shard → still listed (not marker-aware), no count fields added
        first_done = d["pending"][0]["done_marker"]
        Path(first_done).parent.mkdir(parents=True, exist_ok=True)
        Path(first_done).write_text("{}", encoding="utf-8")
        _, out2, _ = a.run("--node", "scout-merge", "--budget", "3000", "--materialize",
                           str(a.init / "shards"))
        d2 = json.loads(out2)
        self.assertNotIn("total", d2)
        self.assertNotIn("done", d2)
        self.assertNotIn("failed", d2)
        self.assertEqual(len(d2["pending"]), len(d["pending"]))  # all still pending

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

    def test_scout_merge_envelope_and_stdout_unchanged(self):
        """Part splitting is a t2-only feature: scout-merge items/inputs carry
        no part_index/part_count/slimmed and keep the legacy oversize warn+send
        disclosure (hand-paged non-goal, envelope byte-identical)."""
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
            self.assertNotIn("slimmed", item)
            body = json.loads(Path(item["input_path"]).read_text(encoding="utf-8"))
            self.assertNotIn("part_index", body)
            self.assertNotIn("part_count", body)
            self.assertEqual(body, {"node": "scout-merge", "shard_id": item["shard_id"],
                                    "records": body["records"]})


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
