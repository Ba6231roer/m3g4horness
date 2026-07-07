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


if __name__ == "__main__":
    unittest.main()
