#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for list_chunks.py (s4 fan-out enumeration).

Mirrors list_clusters.py / list_scout_batches.py (resume-aware pending work-list). The
s3 product is the vvah wrapper {rationale, chunks[]} where the unit key is chunks[].id
(e.g. "chunk-01") — NOT a top-level count. Asserts:
  - total = real chunk count, NOT wrapper key count;
  - chunk_id comes from chunks[].id;
  - pending excludes done chunks (.done marker); total == done + len(pending);
  - empty / bare-list handled without silent loss.
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


_CHUNKS = [
    {"id": "chunk-01", "size": "small", "files": ["a.c", "a.h"],
     "threat_id": "T1", "hypothesis": "h1", "related_cves": []},
    {"id": "chunk-02", "size": "medium", "files": ["b.c"],
     "threat_id": "T2", "hypothesis": "h2", "related_cves": ["CVE-2024-1"]},
    {"id": "chunk-03", "size": "large", "files": ["c.c"], "threat_id": "T3",
     "hypothesis": "h3", "focus_entry_points": ["parse"]},
]


class TestListChunks(unittest.TestCase):
    def setUp(self):
        self.m = _load("list_chunks")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lc_"))

    def _write(self, chunks, rationale="r"):
        p = self.d / "s3_chunks.json"
        p.write_text(json.dumps({"rationale": rationale, "chunks": chunks},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, chunks_path, checkpoints=None):
        argv = ["list_chunks.py", "--chunks", str(chunks_path)]
        if checkpoints:
            argv += ["--checkpoints", str(checkpoints)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _mark_done(self, cid):
        cp = self.d / "s4"
        cp.mkdir(parents=True, exist_ok=True)
        (cp / f"{cid}.json.done").write_text("", encoding="utf-8")

    def test_total_is_chunk_count_not_wrapper_keys(self):
        code, out, _ = self._run(self._write(_CHUNKS))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 3)

    def test_chunk_id_from_id_field(self):
        code, out, _ = self._run(self._write(_CHUNKS))
        ids = [c["chunk_id"] for c in json.loads(out)["pending"]]
        self.assertEqual(ids, ["chunk-01", "chunk-02", "chunk-03"])

    def test_resume_pending_excludes_done(self):
        p = self._write(_CHUNKS)
        cp = self.d / "s4"
        self._mark_done("chunk-02")
        code, out, _ = self._run(p, cp)
        data = json.loads(out)
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["done"], 1)
        ids = [c["chunk_id"] for c in data["pending"]]
        self.assertEqual(ids, ["chunk-01", "chunk-03"])
        self.assertEqual(data["total"], data["done"] + len(data["pending"]))

    def test_lite_shape(self):
        code, out, _ = self._run(self._write(_CHUNKS))
        by = {c["chunk_id"]: c for c in json.loads(out)["pending"]}
        self.assertEqual(by["chunk-02"]["files"], ["b.c"])
        self.assertEqual(by["chunk-02"]["threat_id"], "T2")
        self.assertEqual(by["chunk-02"]["hypothesis"], "h2")

    def test_empty_chunks(self):
        code, out, _ = self._run(self._write([]))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["pending"], [])
        self.assertEqual(data["done"], 0)

    def test_bare_list_accepted(self):
        p = self.d / "bare.json"
        p.write_text(json.dumps(_CHUNKS, ensure_ascii=False), encoding="utf-8")
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 3)

    def test_missing_checkpoints_all_pending(self):
        code, out, _ = self._run(self._write(_CHUNKS), self.d / "nope")
        data = json.loads(out)
        self.assertEqual(data["done"], 0)
        self.assertEqual(len(data["pending"]), 3)

    def test_missing_file_exit1(self):
        code, _, _ = self._run(self.d / "nope.json")
        self.assertEqual(code, 1)

    def test_malformed_wrapper_exit1(self):
        p = self.d / "bad.json"
        p.write_text(json.dumps({"rationale": "r", "not_chunks": []}), encoding="utf-8")
        code, _, _ = self._run(p)
        self.assertEqual(code, 1)


# ---- list_chunks.py: per-unit materialization + paging (request-context-budget) ----

class TestListChunksMaterialize(unittest.TestCase):
    """--materialize: slim envelope + per-chunk input files + paging + oversize/needs_slice."""

    def setUp(self):
        self.m = _load("list_chunks")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_lcm_"))
        self.inputs = self.d / "inputs" / "s4"
        self.cp = self.d / "checkpoints" / "s4"

    def _write(self, chunks):
        p = self.d / "s3_chunks.json"
        p.write_text(json.dumps({"rationale": "r", "chunks": chunks},
                                ensure_ascii=False), encoding="utf-8")
        return p

    def _run(self, chunks_path, *extra):
        argv = ["list_chunks.py", "--chunks", str(chunks_path),
                "--checkpoints", str(self.cp),
                "--materialize", str(self.inputs), "--repo", str(self.d)] + list(extra)
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_slim_envelope_no_variable_payload(self):
        p = self._write(_CHUNKS)
        code, out, _ = self._run(p)
        self.assertEqual(code, 0)
        data = json.loads(out)
        for k in ("offset", "limit", "effective_limit", "shrunk"):
            self.assertIn(k, data)
        it = data["pending"][0]
        # slim: NO files[]/hypothesis; HAS input_path/bytes/oversize/needs_slice
        self.assertNotIn("files", it)
        self.assertNotIn("hypothesis", it)
        for k in ("input_path", "bytes", "oversize", "needs_slice", "files_count",
                  "checkpoint_path", "done_marker"):
            self.assertIn(k, it)
        # input file written + carries the sunk payload (files[] + threat_id + hypothesis)
        ip = Path(it["input_path"])
        self.assertTrue(ip.is_file())
        self.assertEqual(it["bytes"], ip.stat().st_size)
        inp = json.loads(ip.read_text(encoding="utf-8"))
        self.assertIn("files", inp)
        self.assertEqual(inp["threat_id"], "T1")

    def test_input_path_and_checkpoint_absolute(self):
        p = self._write(_CHUNKS)
        _, out, _ = self._run(p)
        for it in json.loads(out)["pending"]:
            self.assertTrue(Path(it["input_path"]).is_absolute())
            self.assertTrue(Path(it["checkpoint_path"]).is_absolute())
            self.assertTrue(it["done_marker"].endswith(".done"))

    def test_paging_offset_limit(self):
        p = self._write(_CHUNKS)
        _, out, _ = self._run(p, "--offset", "1", "--limit", "1")
        data = json.loads(out)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["pending"]), 1)
        self.assertEqual(data["effective_limit"], 1)

    def test_page_shrinks_to_orch_budget(self):
        p = self._write(_CHUNKS)
        _, out, _ = self._run(p, "--orch-budget-bytes", "250")
        data = json.loads(out)
        self.assertTrue(data["shrunk"])
        page_bytes = len(json.dumps(data["pending"]).encode("utf-8"))
        self.assertTrue(page_bytes <= 250 or data["effective_limit"] == 1)

    def test_oversize_needs_slice_big_file(self):
        # a real source file > --big-file-bytes -> needs_slice + oversize (NOT sharded)
        (self.d / "huge.c").write_text("x" * 300, encoding="utf-8")
        (self.d / "a.c").write_text("small", encoding="utf-8")
        chunks = [{"id": "chunk-big", "files": ["huge.c", "a.c"],
                   "threat_id": "T9", "hypothesis": "h"}]
        p = self._write(chunks)
        _, out, _ = self._run(p, "--big-file-bytes", "200")
        it = json.loads(out)["pending"][0]
        self.assertEqual(it["needs_slice"], ["huge.c"])
        self.assertTrue(it["oversize"])
        self.assertEqual(it["chunk_id"], "chunk-big")  # chunk is the plan unit, not sharded

    def test_resume_skips_done_unit(self):
        p = self._write(_CHUNKS)
        self._run(p)  # materialize all
        self.cp.mkdir(parents=True, exist_ok=True)
        (self.cp / "chunk-01.json.done").write_text("", encoding="utf-8")
        _, out, _ = self._run(p)
        data = json.loads(out)
        ids = [it["chunk_id"] for it in data["pending"]]
        self.assertNotIn("chunk-01", ids)
        self.assertEqual(data["done"], 1)

    def test_no_materialize_keeps_backward_compat_lite(self):
        # WITHOUT --materialize the lite shell still carries files[] (no input_path)
        p = self._write(_CHUNKS)
        argv = ["list_chunks.py", "--chunks", str(p), "--checkpoints", str(self.cp)]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        it = json.loads(out.getvalue())["pending"][0]
        self.assertIn("files", it)            # lite retains files[]
        self.assertNotIn("input_path", it)    # no materialization

    def test_bad_budget_exit2(self):
        p = self._write(_CHUNKS)
        code, _, _ = self._run(p, "--max-unit-bytes", "-1")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
