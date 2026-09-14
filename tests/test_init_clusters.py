#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for cluster formation in discover_controls.py (D8/D12 isolation units)."""
import hashlib, importlib.util, sys, unittest, tempfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _controller(pkg: str, cls: str):
    return (f"package {pkg};\npublic class {cls} {{\n"
            f"  @PreAuthorize(\"hasRole('USER')\")\n"
            f"  public void m() {{}}\n}}\n")


def _safe(unit_id: str) -> str:
    """Mirror of list_clusters.py::_safe_name (`/`, `\\`, `:` → `_`). cluster_ids carry
    `::` (NTFS ADS separator → errno 22); the canonical id stays as envelope `cluster_id`
    + record `unit`, only the FILENAME is encoded."""
    return unit_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _sha12(key: str) -> str:
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def _file118(suffix: str) -> str:
    """A 118-char repo-relative file path → category + 2×file + sha12 = 267-char id."""
    return "pkg/" * 28 + suffix.ljust(6, "x")[:6]


def _overlong_cid(file: str, category: str = "authorization") -> str:
    """267-char cluster_id as if produced by an anchor-less centralized candidate
    (home == file; the path is stuffed into the class-name slot)."""
    key = f"{category}::{file}::{file}"
    return f"{key}::{_sha12(key)}"


class TestClusters(unittest.TestCase):
    def setUp(self):
        self.d = _load("discover_controls")
        self.repo = Path(tempfile.mkdtemp(prefix="mgh_cl_"))

    def _run(self, scope=None, scope_mode="defined", sample=8):
        import json
        seed, note = (self.d.resolve_seed(self.repo, scope) if scope else (None, "full-repo"))
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(self.repo, seed, 200000, 204800, None)
        out_of_scope = []
        if seed is not None and scope_mode == "defined":
            for c in cands:
                for ep in c["entry_points"]:
                    if ep not in seed and ep not in out_of_scope:
                        out_of_scope.append(ep)
        clusters = self.d.form_clusters(cands, rev, fw, seed, sample)
        return cands, clusters, out_of_scope

    def test_distributed_cluster_groups_annotation(self):
        _write(self.repo, "src/a/A.java", _controller("a", "A"))
        _write(self.repo, "src/b/B.java", _controller("b", "B"))
        cands, clusters, _ = self._run()
        dist = [c for c in clusters if c["shape"] == "distributed"
                and c["category"] == "authorization"]
        self.assertEqual(len(dist), 1, "@PreAuthorize across files → one distributed cluster")
        sites = dist[0]["usage_sites"]
        self.assertIn("src/a/A.java", sites)
        self.assertIn("src/b/B.java", sites)

    def test_sample_cap(self):
        for i in range(6):
            _write(self.repo, f"src/m/M{i}.java", _controller("m", f"M{i}"))
        _, clusters, _ = self._run(sample=3)
        dist = [c for c in clusters if c["shape"] == "distributed"]
        self.assertTrue(dist)
        self.assertLessEqual(len(dist[0]["usage_sites"]), 3, "usage sites capped at sample")

    def test_out_of_scope_cross_module_caller(self):
        # mask util (in scope) called by a controller OUTSIDE scope
        _write(self.repo, "src/util/MaskUtil.java",
               "package util;\npublic class MaskUtil {\n"
               "  public static String mask(String s){return s;}\n}\n")
        _write(self.repo, "src/api/Ctl.java",
               "package api;\nimport util.MaskUtil;\npublic class Ctl {\n"
               "  public void m(){ MaskUtil.mask(\"x\"); }\n}\n")
        seed, _ = self.d.resolve_seed(self.repo, "path:src/util")
        cands, fwd, rev, fw, trunc, scanned = self.d.scan(self.repo, seed, 200000, 204800, None)
        out = []
        for c in cands:
            for ep in c["entry_points"]:
                if ep not in seed and ep not in out:
                    out.append(ep)
        self.assertIn("src/api/Ctl.java", out, "cross-module caller disclosed in out_of_scope")

    # ---- cluster_id length bound (fix-mgh-init-cluster-id-length-ntfs, D1) ----

    def test_overlong_path_in_class_slot_cluster_id_bounded(self):
        # Anchor with NO class/method → `home` falls back to the full file path == `file`
        # (path stuffed into the class-name slot). The unbounded id would be 515 chars; the
        # bounded id MUST be ≤ 160, dedup the duplicated display slot (`::` × 2), and keep
        # the sha8 computed over the FULL untruncated key (discriminant identity unchanged).
        long_file = "src/" + "deep/" * 55 + "OverlongSecurityUtil.java"
        cand = {"id": "C-1", "file": long_file, "category": "authorization",
                "kind": "auth", "shape": "centralized", "anchor": {},
                "line": 1, "source": "test"}
        clusters = self.d.form_clusters([cand], {}, set(), None, 8)
        cid = clusters[0]["cluster_id"]
        key = f"authorization::{long_file}::{long_file}"
        self.assertGreater(len(key), self.d.MAX_CLUSTER_ID_CHARS)   # display really over budget
        self.assertLessEqual(len(cid), self.d.MAX_CLUSTER_ID_CHARS)
        self.assertEqual(cid.count("::"), 2)                        # dedup: one slot, not two
        self.assertTrue(cid.endswith(f"::{self.d._sha(key)}"))      # sha8 = hash of FULL key

    def test_short_cluster_id_byte_identical_after_bound(self):
        # Normal short id (class anchor + short path): cluster_id MUST be byte-identical to
        # the legacy `f'{key}::{_sha(key)}'` — the bound only affects overlong ids.
        cand = {"id": "C-1", "file": "src/SecCfg.java", "category": "authorization",
                "kind": "auth", "shape": "centralized",
                "anchor": {"class": "SecurityConfig"}, "line": 1, "source": "test"}
        clusters = self.d.form_clusters([cand], {}, set(), None, 8)
        key = "authorization::SecurityConfig::src/SecCfg.java"
        self.assertEqual(clusters[0]["cluster_id"], f"{key}::{self.d._sha(key)}")


# ---- list_clusters.py: deterministic T1 work-list (wrapper unwrap + resume) ----
import contextlib, io, json

_LC_CLUSTERS = [
    {"cluster_id": "authorization::A::ab12", "category": "authorization",
     "kind": "auth", "shape": "centralized", "evidence_files": ["a.java"],
     "usage_sites": ["a.java"], "candidate_ids": ["C-1", "C-2"]},
    {"cluster_id": "data-masking::mask::cd34", "category": "data-masking",
     "kind": "other", "shape": "distributed", "evidence_files": ["b.java"],
     "usage_sites": ["b.java"], "candidate_ids": ["C-3"]},
    {"cluster_id": "crypto::Crypt::ef56", "category": "crypto",
     "kind": "other", "shape": "centralized", "evidence_files": ["c.java"],
     "usage_sites": ["c.java"], "candidate_ids": ["C-4", "C-5", "C-6"]},
]


class TestListClusters(unittest.TestCase):
    """list_clusters.py enumerates the wrapper dict correctly (NOT len() of top level)."""

    def setUp(self):
        self.lc = _load("list_clusters")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lc_"))

    def _run(self, clusters_path, checkpoints=None):
        argv = ["list_clusters.py", "--clusters", str(clusters_path)]
        if checkpoints is not None:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _write(self, clusters, truncated=False):
        p = self.d / "clusters.json"
        p.write_text(json.dumps({"repo": str(self.d), "clusters": clusters,
                                 "truncated": truncated}, ensure_ascii=False),
                     encoding="utf-8")
        return p

    def _mark_done(self, cluster_id):
        cp = self.d / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        rec = cp / f"{_safe(cluster_id)}.json"
        rec.write_text(json.dumps({"unit": cluster_id, "status": "done",
                                   "out": "x", "bytes": 1}), encoding="utf-8")
        rec.with_name(rec.name + ".done").write_text("", encoding="utf-8")

    def _mark_failed(self, cluster_id, reason="evidence parse error"):
        # mirror the orchestrator writing a .failed marker: filename sanitized, body
        # carries the CANONICAL cluster_id in `unit` (what _failed_ids matches on).
        cp = self.d / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{_safe(cluster_id)}.json.failed").write_text(
            json.dumps({"unit": cluster_id, "reason": reason, "tier": "t1"}), encoding="utf-8")

    def test_total_is_cluster_count_not_wrapper_key_count(self):
        # wrapper has 3 top-level keys; with 4 clusters total MUST be 4 (would be 3 if len()'d wrapper)
        p = self._write(_LC_CLUSTERS + [dict(_LC_CLUSTERS[0], cluster_id="x::Y::0001")])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 4)

    def test_pending_done_split_reads_record_unit(self):
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        self._mark_done("authorization::A::ab12")  # sanitized filename, unit=cluster_id
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["done"], 1)
        ids = [c["cluster_id"] for c in data["pending"]]
        self.assertNotIn("authorization::A::ab12", ids)
        self.assertEqual(len(ids), 2)
        # invariant: total == done + len(pending)
        self.assertEqual(data["total"], data["done"] + len(data["pending"]))

    def test_lite_shape_and_candidate_count(self):
        p = self._write(_LC_CLUSTERS)
        code, out, _ = self._run(p)
        by = {c["cluster_id"]: c for c in json.loads(out)["pending"]}
        self.assertEqual(by["crypto::Crypt::ef56"]["candidate_count"], 3)
        self.assertEqual(by["data-masking::mask::cd34"]["evidence_files"], ["b.java"])
        self.assertEqual(by["data-masking::mask::cd34"]["shape"], "distributed")

    def test_pending_emits_absolute_paths(self):
        # FD1: each pending cluster carries an authoritative ABSOLUTE checkpoint_path +
        # done_marker. cluster_id contains '::' (NTFS ADS separator) → the FILENAME component
        # is `_safe_name`-sanitized (`/ \ :` → `_`); the envelope cluster_id keeps canonical `::`.
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        for item in json.loads(out)["pending"]:
            cid = item["cluster_id"]
            exp = str((cp / f"{_safe(cid)}.json").resolve())
            self.assertEqual(item["checkpoint_path"], exp)
            self.assertEqual(item["done_marker"], exp + ".done")
            self.assertTrue(Path(item["checkpoint_path"]).is_absolute())
            self.assertTrue(Path(item["done_marker"]).is_absolute())
            # canonical identity preserved verbatim (NOT sanitized)
            self.assertIn("::", item["cluster_id"])
            self.assertNotIn("::", Path(item["checkpoint_path"]).name)

    def test_pending_checkpoint_path_sanitizes_colons_ntfs(self):
        # NTFS: cluster_id '::' is the Alternate-Data-Stream separator → the checkpoint_path
        # / done_marker FILENAME component has '::' (and '/' '\') replaced with '_'; the
        # envelope cluster_id field stays the canonical id with '::'. Guarantees the path is
        # writable on Windows (no errno 22) while identity semantics are unchanged.
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        by = {it["cluster_id"]: it for it in json.loads(out)["pending"]}
        cid = "authorization::A::ab12"
        item = by[cid]
        self.assertEqual(item["cluster_id"], cid)            # envelope keeps canonical '::'
        self.assertEqual(_safe(cid), "authorization__A__ab12")  # '::' → '__'
        self.assertTrue(item["checkpoint_path"].endswith(_safe(cid) + ".json"))
        self.assertTrue(item["done_marker"].endswith(_safe(cid) + ".json.done"))
        self.assertNotIn(":", Path(item["checkpoint_path"]).name)
        self.assertNotIn(":", Path(item["done_marker"]).name)

    def test_empty_clusters(self):
        p = self._write([])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["done"], 0)

    def test_truncated_passthrough(self):
        p = self._write(_LC_CLUSTERS, truncated=True)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["truncated"])

    def test_missing_checkpoints_dir_all_pending(self):
        p = self._write(_LC_CLUSTERS)
        code, out, _ = self._run(p, self.d / "nonexistent")
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)

    def test_missing_clusters_file_exit1(self):
        code, out, err = self._run(self.d / "nope.json")
        self.assertEqual(code, 1)

    # ---- .failed terminal marker (partial fan-out tolerance) ----

    def test_failed_excluded_from_pending_and_counted(self):
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        self._mark_failed("crypto::Crypt::ef56")
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        data = json.loads(out)
        ids = [c["cluster_id"] for c in data["pending"]]
        self.assertNotIn("crypto::Crypt::ef56", ids)   # terminal → excluded
        self.assertEqual(data["failed"], 1)
        # invariant (non-sharded): total == done + failed + len(pending)
        self.assertEqual(data["total"], data["done"] + data["failed"] + len(data["pending"]))

    def test_pending_item_carries_absolute_failed_marker(self):
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        code, out, _ = self._run(p, cp)
        for item in json.loads(out)["pending"]:
            self.assertIn("failed_marker", item)
            self.assertTrue(Path(item["failed_marker"]).is_absolute())
            # .failed sibling of checkpoint_path; filename has no ':' (NTFS-safe)
            self.assertEqual(item["failed_marker"], item["checkpoint_path"] + ".failed")
            self.assertNotIn(":", Path(item["failed_marker"]).name)

    def test_failed_without_record_body_still_excluded(self):
        # .failed marker whose sibling record body is absent (subagent failed before
        # writing the record): the marker body `unit` is authoritative → still excluded.
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{_safe('crypto::Crypt::ef56')}.json.failed").write_text(
            json.dumps({"unit": "crypto::Crypt::ef56", "reason": "r", "tier": "t1"}),
            encoding="utf-8")
        code, out, _ = self._run(p, cp)
        data = json.loads(out)
        self.assertNotIn("crypto::Crypt::ef56", [c["cluster_id"] for c in data["pending"]])
        self.assertEqual(data["failed"], 1)

    def test_lite_slice_dir_present_absolute_sanitized(self):
        # lite shell (no --materialize) also carries an ABSOLUTE slice_dir whose filename
        # component is `_safe_name`-sanitized (cluster_id '::' → '__'; no NTFS-ADS ':').
        p = self._write(_LC_CLUSTERS)
        cp = self.d / "checkpoints" / "t1"
        code, out, _ = self._run(p, cp)
        self.assertEqual(code, 0)
        for item in json.loads(out)["pending"]:
            self.assertIn("slice_dir", item)
            sd = Path(item["slice_dir"])
            self.assertTrue(sd.is_absolute())
            self.assertNotIn(":", sd.name)            # '::' sanitized out of the filename
            self.assertEqual(sd.name, _safe(item["cluster_id"]))

    # ---- _safe_name stem length truncation (fix-mgh-init-cluster-id-length-ntfs, D2) ----

    def test_safe_name_truncates_overlong_id_keeps_tail(self):
        # A 267-char id (legacy, pre-bound discover) → stem capped to exactly 200, keeping
        # the sanitized head AND the ~60-char discriminant tail (contains the sha8 tail).
        cid = _overlong_cid(_file118("U.java"))
        self.assertEqual(len(cid), 267)
        s = _safe(cid)                                          # sanitized (len unchanged)
        stem = self.lc._safe_name(cid)
        self.assertEqual(len(stem), self.lc.MAX_UNIT_FILENAME_STEM)
        self.assertTrue(stem.startswith(s[: self.lc.MAX_UNIT_FILENAME_STEM - 60]))
        self.assertTrue(stem.endswith(s[-59:]))                  # sha8-bearing tail preserved
        self.assertIn("~", stem)

    def test_safe_name_distinct_overlong_ids_do_not_collide(self):
        # Two distinct overlong ids (differing file suffix → differing sha8 in the preserved
        # tail) map to DIFFERENT stems — no on-disk filename collision.
        cid_a = _overlong_cid(_file118("U.java"))
        cid_b = _overlong_cid(_file118("V.java"))
        self.assertNotEqual(self.lc._safe_name(cid_a), self.lc._safe_name(cid_b))

    def test_safe_name_short_id_unchanged(self):
        # Short ids (overwhelming majority) pass through the stem cap untouched.
        cid = "authorization::SecCfg::ab12cd34"
        self.assertEqual(self.lc._safe_name(cid), _safe(cid))
        self.assertEqual(self.lc._safe_name(cid), "authorization__SecCfg__ab12cd34")


# ---- list_clusters.py: per-unit materialization + paging (request-context-budget) ----

_LC_CANDS = [
    {"id": "C-1", "file": "a.java", "line": 1, "category": "authorization",
     "kind": "auth", "snippet": "s1"},
    {"id": "C-2", "file": "a.java", "line": 2, "category": "authorization",
     "kind": "auth", "snippet": "s2"},
    {"id": "C-3", "file": "c.java", "line": 3, "category": "crypto",
     "kind": "other", "snippet": "s3"},
    {"id": "C-4", "file": "c.java", "line": 4, "category": "crypto",
     "kind": "other", "snippet": "s4"},
    {"id": "C-5", "file": "c.java", "line": 5, "category": "crypto",
     "kind": "other", "snippet": "s5"},
    {"id": "C-6", "file": "c.java", "line": 6, "category": "crypto",
     "kind": "other", "snippet": "s6"},
]


class TestListClustersMaterialize(unittest.TestCase):
    """--materialize: slim envelope + per-unit input files + paging + oversize sharding."""

    def setUp(self):
        self.lc = _load("list_clusters")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lcm_"))
        self.inputs = self.d / "inputs" / "t1"
        self.cp = self.d / "checkpoints" / "t1"

    def _write(self, clusters, cands=None):
        p = self.d / "clusters.json"
        p.write_text(json.dumps({"repo": str(self.d), "clusters": clusters,
                                 "truncated": False}, ensure_ascii=False), encoding="utf-8")
        if cands is not None:
            (self.d / "controls_candidates.json").write_text(
                json.dumps({"candidates": cands}, ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, clusters_path, *extra):
        argv = ["list_clusters.py", "--clusters", str(clusters_path),
                "--checkpoints", str(self.cp),
                "--candidates", str(self.d / "controls_candidates.json"),
                "--materialize", str(self.inputs)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_slim_envelope_no_variable_payload(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        # paging fields present
        for k in ("offset", "limit", "effective_limit", "shrunk"):
            self.assertIn(k, data)
        item = data["pending"][0]
        # slim: NO evidence_files/usage_sites; HAS input_path/bytes/oversize
        self.assertNotIn("evidence_files", item)
        self.assertNotIn("usage_sites", item)
        for k in ("input_path", "bytes", "oversize", "checkpoint_path", "done_marker"):
            self.assertIn(k, item)
        # input file written + carries the sunk payload (evidence_files + candidates)
        ip = Path(item["input_path"])
        self.assertTrue(ip.is_file())
        self.assertEqual(item["bytes"], ip.stat().st_size)
        inp = json.loads(ip.read_text(encoding="utf-8"))
        self.assertIn("evidence_files", inp)
        self.assertIn("candidates", inp)

    def test_input_carries_candidate_hits(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        _, out, _ = self._run(p)
        by = {it["cluster_id"]: it for it in json.loads(out)["pending"]}
        # crypto cluster has 3 candidate_ids (C-3,4,5) all present in candidates
        crypto = by["crypto::Crypt::ef56"]
        self.assertEqual(crypto["candidate_count"], 3)
        inp = json.loads(Path(crypto["input_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(inp["candidates"]), 3)

    def test_input_carries_top_level_repo_anchor(self):
        # fan-out input anchor: each materialized unit input carries the ABSOLUTE repo
        # root as a top-level field (reader subagent anchors tool paths on it without
        # re-deriving; poisoned-path rejection judges against this anchor).
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        for it in json.loads(out)["pending"]:
            inp = json.loads(Path(it["input_path"]).read_text(encoding="utf-8"))
            self.assertEqual(inp.get("repo"), str(self.d.resolve()),
                             f"{it['cluster_id']} input.json missing the top-level repo anchor")
            self.assertTrue(Path(inp["repo"]).is_absolute())

    def test_paging_offset_limit(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        _, out, _ = self._run(p, "--offset", "1", "--limit", "1")
        data = json.loads(out)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["pending"]), 1)
        self.assertEqual(data["effective_limit"], 1)

    def test_page_shrinks_to_orch_budget(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        _, out, _ = self._run(p, "--orch-budget-bytes", "250")
        data = json.loads(out)
        self.assertTrue(data["shrunk"])
        self.assertLessEqual(data["effective_limit"], len(_LC_CLUSTERS))
        # the returned page serialized bytes <= budget (or a single unavoidable item)
        page_bytes = len(json.dumps(data["pending"]).encode("utf-8"))
        self.assertTrue(page_bytes <= 250 or data["effective_limit"] == 1)

    def test_oversize_cluster_is_sharded_within_budget(self):
        big = [dict(_LC_CLUSTERS[0], cluster_id="big::X::zz",
                    candidate_ids=[f"C-{i}" for i in range(1, 7)])]
        cands = [{"id": f"C-{i}", "file": "x", "line": i, "category": "authorization",
                  "kind": "auth", "snippet": "S" * 3000} for i in range(1, 7)]
        p = self._write(big, cands)
        _, out, _ = self._run(p, "--max-unit-bytes", "4000")
        data = json.loads(out)
        ids = [it["cluster_id"] for it in data["pending"]]
        self.assertTrue(all(i.startswith("big::X::zz::shard-") for i in ids), ids)
        self.assertGreater(len(ids), 1)  # was actually sharded
        # each shard input <= budget; each oversize flag set
        for it in data["pending"]:
            self.assertLessEqual(it["bytes"], 4000)
            self.assertTrue(it["oversize"])
            self.assertTrue(Path(it["input_path"]).is_file())

    def test_resume_skips_done_unit(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        _, out, _ = self._run(p)  # first run materializes everything
        first = json.loads(out)["pending"]
        # mark one unit done via its checkpoint. The checkpoint FILENAME is sanitized
        # on disk (cluster_id contains `::` = NTFS ADS separator, unwritable on Windows;
        # `_safe` mirrors `_safe_name`), but the record's `unit` field carries the canonical
        # cluster_id — that is what _done_ids matches on.
        self.cp.mkdir(parents=True, exist_ok=True)
        cid = first[0]["cluster_id"]
        rec = self.cp / f"{_safe(cid)}.json"
        rec.write_text(json.dumps({"unit": cid}), encoding="utf-8")
        rec.with_name(rec.name + ".done").write_text("", encoding="utf-8")
        _, out2, _ = self._run(p)
        data = json.loads(out2)
        self.assertNotIn(cid, [it["cluster_id"] for it in data["pending"]])
        self.assertEqual(data["done"], 1)

    def test_resume_roundtrip_sanitized_path_canonical_unit(self):
        # End-to-end resume across the sanitization fix: the subagent writes its checkpoint
        # record at the verbatim `checkpoint_path` from stdout (now `_safe_name`-sanitized —
        # previously raw `::`, which errno-22s on Windows), with the CANONICAL cluster_id in
        # the `unit` field, then touches `done_marker`. _done_ids reads the `unit` field and
        # correctly marks the unit done → resume does NOT re-run it.
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        _, out, _ = self._run(p)
        first = json.loads(out)["pending"]
        target = next(it for it in first if "::" in it["cluster_id"])  # a '::' cluster_id
        cid = target["cluster_id"]
        cp_path = target["checkpoint_path"]            # sanitized absolute path (no '::')
        self.assertNotIn(":", Path(cp_path).name)
        self.assertEqual(target["cluster_id"], cid)    # envelope identity still canonical
        # subagent writes the record at the verbatim sanitized path + unit=canonical
        Path(cp_path).parent.mkdir(parents=True, exist_ok=True)
        Path(cp_path).write_text(json.dumps({"unit": cid, "status": "done",
                                             "out": "x", "bytes": 1}), encoding="utf-8")
        Path(target["done_marker"]).write_text("", encoding="utf-8")
        _, out2, _ = self._run(p)
        data = json.loads(out2)
        self.assertNotIn(cid, [it["cluster_id"] for it in data["pending"]])
        self.assertEqual(data["done"], 1)

    def test_no_materialize_keeps_backward_compat_lite(self):
        # WITHOUT --materialize the lite shell still carries evidence_files[]
        p = self._write(_LC_CLUSTERS)
        argv = ["list_clusters.py", "--clusters", str(p), "--checkpoints", str(self.cp)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        item = json.loads(out.getvalue())["pending"][0]
        self.assertIn("evidence_files", item)
        self.assertNotIn("input_path", item)

    def test_bad_budget_exit2(self):
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        code, _, _ = self._run(p, "--max-unit-bytes", "-1")
        self.assertEqual(code, 2)

    def test_slice_dir_absolute_in_tree_and_sanitized(self):
        # slice_dir = <init-dir>/slices/t1/<safe(cluster_id)>/ ; <init-dir> = grandparent of
        # the checkpoint dir (= self.d). Absolute, resolve()-stable, in the
        # <init-dir>/slices/t1/ subtree. cluster_id '::' (NTFS ADS separator) sanitized in the
        # filename component; envelope cluster_id stays canonical.
        p = self._write(_LC_CLUSTERS, _LC_CANDS)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        init_dir = self.d.resolve()
        for item in json.loads(out)["pending"]:
            cid = item["cluster_id"]
            self.assertIn("slice_dir", item)
            sd = Path(item["slice_dir"])
            self.assertTrue(sd.is_absolute(), "slice_dir must be absolute")
            self.assertEqual(sd, sd.resolve(),
                             "slice_dir resolve()-stable (no '..' residual)")
            # in-tree + sanitized filename component (== _safe(cid))
            self.assertEqual(sd.relative_to(init_dir),
                             Path("slices") / "t1" / _safe(cid))
            self.assertEqual(sd.name, _safe(cid))
            for bad in (":", "/", "\\"):  # NTFS-ADS / path separators absent
                self.assertNotIn(bad, sd.name)
            # canonical identity preserved in the envelope (NOT sanitized)
            self.assertIn("::", cid)
            # existing additive fields still present (regression: slice_dir is additive)
            for k in ("input_path", "checkpoint_path", "done_marker", "failed_marker",
                      "bytes", "oversize"):
                self.assertIn(k, item)

    # ---- overlong cluster_id materialization (fix-mgh-init-cluster-id-length-ntfs, D2/D3) ----

    def test_overlong_cluster_id_materialize_and_resume(self):
        # A legacy 267-char cluster_id: --materialize MUST succeed (exit 0), write a
        # stem-capped (≤ 200) input file, keep the FULL canonical id in the envelope + input
        # record; marking done at the truncated-stem checkpoint path with `unit`=canonical →
        # --resume skips it (identity is the record's `unit` field, not the filename).
        cid = _overlong_cid(_file118("U.java"))
        clusters = [{"cluster_id": cid, "category": "authorization", "kind": "auth",
                     "shape": "centralized", "evidence_files": ["a.java"],
                     "usage_sites": ["a.java"], "candidate_ids": ["C-1"]}]
        p = self._write(clusters, _LC_CANDS[:1])
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        item = json.loads(out)["pending"][0]
        self.assertEqual(item["cluster_id"], cid)                    # envelope keeps canonical
        ipath = Path(item["input_path"])
        self.assertTrue(ipath.is_file())
        base = ipath.name[: -len(".input.json")]    # id-derived stem (before materialization suffix)
        self.assertLessEqual(len(base), self.lc.MAX_UNIT_FILENAME_STEM)
        inp = json.loads(ipath.read_text(encoding="utf-8"))
        self.assertEqual(inp["cluster_id"], cid)                     # record keeps canonical
        # resume: subagent writes the record at the verbatim (truncated-stem) path with
        # unit=canonical, touches done_marker → skipped on the next listing
        Path(item["checkpoint_path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(item["checkpoint_path"]).write_text(json.dumps(
            {"unit": cid, "status": "done", "out": "x", "bytes": 1}), encoding="utf-8")
        Path(item["done_marker"]).write_text("", encoding="utf-8")
        _, out2, _ = self._run(p)
        data = json.loads(out2)
        self.assertNotIn(cid, [it["cluster_id"] for it in data["pending"]])
        self.assertEqual(data["done"], 1)

    def test_materialize_oserror_isolated_to_failed_marker(self):
        # A cluster whose materialization write fails (OSError) MUST NOT abort the batch:
        # its `.failed` terminal marker is written (body unit=canonical), `failed` +1, and
        # the remaining clusters still materialize; exit code stays 0.
        bad = {"cluster_id": "bad::X::zz", "category": "authorization", "kind": "auth",
               "shape": "centralized", "evidence_files": ["bad.java"],
               "usage_sites": ["bad.java"], "candidate_ids": ["C-1"]}
        good = dict(_LC_CLUSTERS[0])
        p = self._write([bad, good], _LC_CANDS[:1])
        real = self.lc._resolve_units

        def _boom(cid, cluster, hits, max_unit_bytes, inputs_dir, repo_path):
            if cid == "bad::X::zz":
                raise OSError("boom: materialize failed")
            return real(cid, cluster, hits, max_unit_bytes, inputs_dir, repo_path)

        with mock.patch.object(self.lc, "_resolve_units", side_effect=_boom):
            code, out, err = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        ids = [it["cluster_id"] for it in data["pending"]]
        self.assertNotIn("bad::X::zz", ids)             # terminal → excluded from pending
        self.assertIn("authorization::A::ab12", ids)    # good cluster still materialized
        self.assertEqual(data["failed"], 1)
        fm = self.cp / f"{_safe('bad::X::zz')}.json.failed"
        self.assertTrue(fm.is_file())
        body = json.loads(fm.read_text(encoding="utf-8"))
        self.assertEqual(body["unit"], "bad::X::zz")    # canonical identity in the body
        self.assertEqual(body["tier"], "t1")
        self.assertIn("materialize failed", body["reason"])
        self.assertIn("materialize failed", err)        # stderr reports the failure
        good_item = next(it for it in data["pending"]
                         if it["cluster_id"] == "authorization::A::ab12")
        self.assertTrue(Path(good_item["input_path"]).is_file())


# ---- forward marker-path done/failed judgment (fix-mgh-init-done-marker-identity) ----

class TestForwardDoneJudgment(unittest.TestCase):
    """done/failed 判定 = 正向 marker 路径计算(与物化同源编码),身份免疫:
    判定 NEVER 依赖记录体字段或文件名 stem 反推;孤儿 marker 只告警不进计数。"""

    def setUp(self):
        self.lc = _load("list_clusters")
        self.it = _load("init_tier")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_fwd_"))
        self.cp = self.d / "checkpoints" / "t1"

    def _write(self, clusters):
        p = self.d / "clusters.json"
        p.write_text(json.dumps({"repo": str(self.d), "clusters": clusters,
                                 "truncated": False}, ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, clusters_path, *extra):
        argv = ["list_clusters.py", "--clusters", str(clusters_path),
                "--checkpoints", str(self.cp)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.lc.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_roundtrip_overlong_id_done_without_unit_field(self):
        # THE bug shape: ≥200-char cluster_id with an existing truncated-stem
        # `<encoded>.json` + `<encoded>.json.done` whose record body carries NO `unit`
        # field (the pre-fix producer never wrote one). Forward computation must judge
        # it DONE — never the old glob+stem misjudgment (forever-pending → re-dispatch).
        cid = _overlong_cid(_file118("U.java"))
        p = self._write([{"cluster_id": cid, "category": "authorization", "kind": "auth",
                          "shape": "centralized", "evidence_files": ["a.java"],
                          "usage_sites": ["a.java"], "candidate_ids": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        enc = self.lc._safe_name(cid)
        self.assertNotEqual(enc, _safe(cid))          # really truncated (stem ≠ canonical)
        self.assertLessEqual(len(enc), self.lc.MAX_UNIT_FILENAME_STEM)
        rec = self.cp / f"{enc}.json"
        rec.write_text(json.dumps({"cluster_id": cid, "status": "done"}), encoding="utf-8")
        rec.with_name(rec.name + ".done").write_text("", encoding="utf-8")
        code, out, err = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["done"], 1)             # forward judgment: DONE
        self.assertEqual(data["pending"], [])         # NOT re-dispatched
        self.assertNotIn("could not read unit from", err)  # old warn path deleted

    def test_roundtrip_overlong_id_failed_without_unit_field(self):
        # same shape for the terminal-failure set: truncated-stem .failed marker → failed
        cid = _overlong_cid(_file118("V.java"))
        p = self._write([{"cluster_id": cid, "category": "crypto", "kind": "other",
                          "shape": "centralized", "evidence_files": ["c.java"],
                          "usage_sites": ["c.java"], "candidate_ids": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        enc = self.lc._safe_name(cid)
        (self.cp / f"{enc}.json.failed").write_text(
            json.dumps({"reason": "boom", "tier": "t1"}), encoding="utf-8")  # no `unit`
        code, out, _ = self._run(p)
        data = json.loads(out)
        self.assertEqual(data["failed"], 1)           # forward judgment: terminal-failed
        self.assertEqual(data["pending"], [])

    def test_shard_id_forward_done(self):
        # `<cid>::shard-<n>` units are canonical ids too: with --materialize, a shard
        # done-marker at the encoded shard filename judges THAT shard done — it drops
        # from pending while sibling shards stay.
        cid = "big::Y::aa"
        cands = [{"id": f"C-{i}", "file": "x", "line": i, "category": "crypto",
                  "kind": "other", "snippet": "S" * 500} for i in range(1, 7)]
        p = self._write([{"cluster_id": cid, "category": "crypto", "kind": "other",
                          "shape": "centralized", "evidence_files": ["x.java"],
                          "usage_sites": ["x.java"],
                          "candidate_ids": [c["id"] for c in cands]}])
        (self.d / "controls_candidates.json").write_text(
            json.dumps({"candidates": cands}), encoding="utf-8")
        inputs = self.d / "inputs" / "t1"
        self.cp.mkdir(parents=True, exist_ok=True)
        code, out, _ = self._run(p, "--candidates", str(self.d / "controls_candidates.json"),
                                 "--materialize", str(inputs), "--max-unit-bytes", "2000")
        self.assertEqual(code, 0)
        first = json.loads(out)["pending"]
        self.assertGreater(len(first), 1)                    # genuinely sharded
        shard0 = first[0]
        Path(shard0["done_marker"]).write_text("", encoding="utf-8")
        code, out, _ = self._run(p, "--candidates", str(self.d / "controls_candidates.json"),
                                 "--materialize", str(inputs), "--max-unit-bytes", "2000")
        data = json.loads(out)
        ids = [it["cluster_id"] for it in data["pending"]]
        self.assertNotIn(shard0["cluster_id"], ids)          # shard-0 done → dropped
        self.assertEqual(len(ids), len(first) - 1)           # siblings remain

    def test_record_body_unit_field_never_load_bearing(self):
        # A record body whose `unit` field DISAGREES with the canonical id must NOT flip
        # the judgment either way: marker absent → pending (even though body says done).
        cid = "auth::Z::bb"
        p = self._write([{"cluster_id": cid, "category": "authorization", "kind": "auth",
                          "shape": "centralized", "evidence_files": ["a.java"],
                          "usage_sites": ["a.java"], "candidate_ids": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / f"{self.lc._safe_name(cid)}.json").write_text(
            json.dumps({"unit": cid, "status": "done"}), encoding="utf-8")  # record, NO marker
        code, out, _ = self._run(p)
        data = json.loads(out)
        self.assertEqual(data["done"], 0)             # no marker → pending (marker is the truth)
        self.assertEqual(len(data["pending"]), 1)

    def test_orphan_marker_warned_not_counted(self):
        # a .done marker whose encoded filename maps to no canonical id (renamed run):
        # stderr warn + NOT in done/failed/pending (fail-soft, never blocks).
        p = self._write([{"cluster_id": "auth::W::cc", "category": "authorization",
                          "kind": "auth", "shape": "centralized",
                          "evidence_files": [], "usage_sites": [], "candidate_ids": []}])
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "legacy__renamed__id.json.done").write_text("", encoding="utf-8")
        code, out, err = self._run(p)
        self.assertEqual(code, 0)                     # fail-soft
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 1)
        self.assertIn("orphan marker", err)
        self.assertIn("legacy__renamed__id.json.done", err)

    def test_forward_predicates_direct(self):
        # shared init_tier predicates: round-trip encode → marker → done/failed sets;
        # orphan list; tier-level markers excluded for scout.
        ids = ["a::b::c", _overlong_cid(_file118("W.java"))]
        self.cp.mkdir(parents=True, exist_ok=True)
        Path(self.it.forward_marker_paths(self.cp, ids[0])[1]).write_text("", encoding="utf-8")
        Path(self.it.forward_marker_paths(self.cp, ids[1])[2]).write_text("", encoding="utf-8")
        self.assertEqual(self.it.forward_done_ids(self.cp, ids), {ids[0]})
        self.assertEqual(self.it.forward_failed_ids(self.cp, ids), {ids[1]})
        self.assertEqual(self.it.orphan_markers(self.cp, ids), [])
        # scout exclusion shape: merge.json.done is tier-level, not an orphan
        (self.cp / "merge.json.done").write_text("", encoding="utf-8")
        self.assertEqual(self.it.orphan_markers(self.cp, ids, exclude=("merge.json",)), [])

    def test_pack_level_markers_not_orphans(self):
        # t1 packing: a pack-level .failed marker (pack::<category>::<sha8>, encoded
        # `pack__...`) is a legit dispatch-unit terminal — NEVER audited as an orphan
        # (pack ids are not members of the canonical cluster-id set by design).
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "pack__crypto__ab12cd34.json.failed").write_text(
            json.dumps({"unit": "pack::crypto::ab12cd34", "reason": "r", "tier": "t1"}),
            encoding="utf-8")
        (self.cp / "pack__crypto__deadbeef.json.done").write_text("", encoding="utf-8")
        self.assertEqual(self.it.orphan_markers(self.cp, ["crypto::X::01"]), [])
        # a genuinely unknown marker still audits
        (self.cp / "legacy__renamed.json.done").write_text("", encoding="utf-8")
        self.assertEqual(self.it.orphan_markers(self.cp, ["crypto::X::01"]),
                         ["legacy__renamed.json.done"])


if __name__ == "__main__":
    unittest.main()
