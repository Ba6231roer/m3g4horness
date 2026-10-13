#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for describe_artifact.py (FD5 sanctioned inspection primitive).

Covers each mode's output shape + the wrapper-dict miscount warn (prevents
`len({repo,clusters,truncated}) == 3` being mistaken for the cluster count).
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


class TestDescribeArtifact(unittest.TestCase):
    def setUp(self):
        self.m = _load("describe_artifact")
        self.d = Path(tempfile.mkdtemp(prefix="mgh_da_"))

    def _run(self, args):
        argv = ["describe_artifact.py", "--in", str(self.art), *args]
        old, sys.argv = sys.argv, argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = self.m.main()
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def _wrap(self, payload):
        self.art = self.d / "art.json"
        self.art.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def test_keys(self):
        self._wrap({"repo": "r", "clusters": [1, 2, 3], "truncated": False})
        code, out, _ = self._run(["--keys"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["type"], "dict")
        self.assertIn("clusters", d["keys"])

    def test_count_warns_on_wrapper_dict(self):
        self._wrap({"repo": "r", "clusters": [{"x": 1}, {"x": 2}], "truncated": False})
        code, out, err = self._run(["--count"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(d["counts"]["clusters"], 2)
        self.assertEqual(d["top_level_keys"], 3)
        self.assertIn("NOT a collection count", err)

    def test_count_on_top_level_list(self):
        self.art = self.d / "list.json"
        self.art.write_text(json.dumps([1, 2, 3, 4]), encoding="utf-8")
        code, out, _ = self._run(["--count"])
        self.assertEqual(json.loads(out)["count"], 4)

    def test_sample_picks_first_list_key(self):
        self._wrap({"repo": "r", "batches": [{"id": 1}, {"id": 2}]})
        code, out, _ = self._run(["--sample", "1"])
        self.assertEqual(code, 0)
        d = json.loads(out)
        self.assertEqual(len(d["sample"]), 1)
        self.assertEqual(d["over"], "batches")

    def test_shape_element_type(self):
        self._wrap({"repo": "r", "batches": [{"batch_id": "x", "bytes": 10}]})
        code, out, _ = self._run(["--shape"])
        self.assertEqual(code, 0)
        sh = json.loads(out)["shape"]
        self.assertEqual(sh["batches"]["type"], "list")
        self.assertEqual(sh["batches"]["element"]["batch_id"], "str")
        self.assertEqual(sh["batches"]["element"]["bytes"], "int")

    def test_field_navigate_and_index(self):
        self._wrap({"batches": [{"batch_id": "scout-001"}]})
        code, out, _ = self._run(["--field", "batches.0.batch_id"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["value"], "scout-001")

    def test_field_unicode_digit_segment_fails_gracefully(self):
        # fix-mgh-sdr-docs-shell-alignment M12: isdigit() accepts `²` but int() rejects
        # it — the old guard/apply mismatch escaped as a bare traceback; now the
        # malformed segment is the ordinary graceful field-path error (exit 1)
        self._wrap({"batches": [{"batch_id": "x"}]})
        for bad in ("batches.²", "batches.٥", "batches."):
            with self.subTest(bad=bad):
                code, out, err = self._run(["--field", bad])
                self.assertEqual(code, 1)
                self.assertIn("field path not found", err)
                self.assertNotIn("Traceback", err)

    def test_field_negative_index_is_out_of_range_not_crash(self):
        self._wrap({"batches": [{"batch_id": "x"}]})
        code, _, err = self._run(["--field", "batches.-1"])
        self.assertEqual(code, 1)
        self.assertIn("field path not found", err)

    def test_chinese_value_output_under_reconfigure(self):
        # fix-mgh-sdr-docs-shell-alignment M13: this script is the family's only one
        # without the console utf-8 reconfigure — ensure_ascii=False Chinese values
        # crashed on a cp936 console. The block now matches every sibling's shape.
        self._wrap({"风险": "密码明文存储:高危,须加密", "batches": []})
        code, out, err = self._run(["--field", "风险"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["value"], "密码明文存储:高危,须加密")
        self.assertIn("密码明文存储", out)   # ensure_ascii=False passthrough, not \u escapes

    def test_no_mode_exit2(self):
        self._wrap({"a": 1})
        code, _, _ = self._run([])
        self.assertEqual(code, 2)

    def test_missing_file_exit1(self):
        self.art = self.d / "nope.json"
        code, _, _ = self._run(["--keys"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
