#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sensitive_catalog.py regression (closed-set sensitive-data catalog registry +
parse/validate/render).

Covers: --list enumerates the 10 PIPL/GB-T 35273 categories + the 37-item default
template; --parse renders a resolved catalog object (version/source/categories[]/
items[]/counts{}/directive) for a valid input; closed-set violations exit 2 with an
actionable stderr naming the offending item (unknown category / illegal mask /
malformed key / missing label / non-int version); malformed JSON exits 1; the
directive is deterministic (byte-identical across runs, registry order not input
order); inline JSON (starts with `{`), stdin (`-`), bare path, and `@path` input
forms; stdout=JSON / stderr=diagnostics split; runs from any cwd; zero runtime deps
(AST scan). Plus validate_resolved (null/valid/violation) and the anti-drift
assertion: DEFAULT_TEMPLATE ships exactly 37 items across the 10 closed-set categories.

Run: py tests/test_sensitive_catalog.py
"""
import ast, json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "sensitive_catalog.py"
SCRIPTS = HERE.parent / "core" / "scripts"
PY = sys.executable

# direct import (sibling) for registry / validate_resolved assertions
sys.path.insert(0, str(SCRIPTS))
import sensitive_catalog

VALID = ('{"version":1,"items":{'
         '"biometric/iris":{"label":"虹膜","mask":"full","rule":null},'
         '"financial/card-no":{"label":"银行卡号","mask":"partial","rule":"保留后4位"},'
         '"general-pii/name":{"label":"姓名","mask":"partial","rule":"保留姓"}}}')


def run(args, cwd=None, stdin=None):
    r = subprocess.run([PY, str(SCRIPT), *args], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8",
                       input=stdin)
    return r.returncode, r.stdout, r.stderr


class TestRegistry(unittest.TestCase):
    def test_list_ten_categories_and_37_item_template(self):
        rc, out, err = run(["--list"])
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual([c["key"] for c in d["categories"]], sensitive_catalog.CATEGORIES)
        self.assertEqual(len(d["categories"]), 10)
        self.assertEqual(d["mask_levels"], ["full", "partial"])
        tpl = d["default_template"]
        self.assertEqual(tpl["version"], 1)
        self.assertEqual(len(tpl["items"]), 37)
        # every template key's category is in the closed set
        for key in tpl["items"]:
            self.assertIn(key.split("/", 1)[0], sensitive_catalog.CATEGORIES)


class TestParse(unittest.TestCase):
    def test_valid_resolves_sorted_with_counts_and_directive(self):
        rc, out, err = run(["--parse", VALID])
        self.assertEqual(rc, 0, err)
        c = json.loads(out)
        self.assertEqual(c["version"], 1)
        self.assertEqual(c["source"], "inline")
        # registry order (biometric < financial < general-pii), not input order
        self.assertEqual([it["key"] for it in c["items"]],
                         ["biometric/iris", "financial/card-no", "general-pii/name"])
        self.assertEqual(c["counts"], {"items": 3, "full": 1, "partial": 2, "categories": 3})
        self.assertEqual(c["categories"], ["biometric", "financial", "general-pii"])
        self.assertIn("脱敏", c["directive"])
        self.assertIn("id-card/bank-card", c["directive"])  # legacy-6-facet note

    def test_each_item_carries_key_category_label_mask_rule(self):
        rc, out, _ = run(["--parse", VALID])
        for it in json.loads(out)["items"]:
            for f in ("key", "category", "label", "mask", "rule"):
                self.assertIn(f, it)


class TestViolationsExit2(unittest.TestCase):
    def _bad(self, spec, needle):
        rc, out, err = run(["--check", spec])
        self.assertEqual(rc, 2, err)
        self.assertFalse(json.loads(out)["ok"])
        self.assertIn(needle, err)

    def test_unknown_category(self):
        self._bad('{"version":1,"items":{"astrology/zodiac":{"label":"x","mask":"full","rule":null}}}',
                  "astrology")

    def test_illegal_mask(self):
        self._bad('{"version":1,"items":{"biometric/iris":{"label":"i","mask":"mostly","rule":null}}}',
                  "mask")

    def test_malformed_key_no_slash(self):
        self._bad('{"version":1,"items":{"iris":{"label":"i","mask":"full","rule":null}}}',
                  "<category>/<field-type>")

    def test_missing_label(self):
        self._bad('{"version":1,"items":{"biometric/iris":{"mask":"full","rule":null}}}',
                  "label")

    def test_non_int_version(self):
        rc, out, err = run(["--check", '{"version":"1","items":{"biometric/iris":{"label":"i","mask":"full","rule":null}}}'])
        self.assertEqual(rc, 2, err)
        self.assertFalse(json.loads(out)["ok"])

    def test_malformed_json_exits_1(self):
        rc, out, err = run(["--parse", "{not json"])
        self.assertEqual(rc, 1, err)

    def test_non_object_json_exits_2(self):
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "bad.json"
            fp.write_text('["biometric/iris"]', encoding="utf-8")
            rc, out, err = run(["--parse", str(fp)])
            self.assertEqual(rc, 2, err)


class TestDeterminism(unittest.TestCase):
    def test_directive_and_items_byte_identical_regardless_of_input_order(self):
        a = ('{"version":1,"items":{'
             '"financial/card-no":{"label":"银行卡号","mask":"partial","rule":"保留后4位"},'
             '"biometric/iris":{"label":"虹膜","mask":"full","rule":null}}}')
        b = ('{"version":1,"items":{'
             '"biometric/iris":{"label":"虹膜","mask":"full","rule":null},'
             '"financial/card-no":{"label":"银行卡号","mask":"partial","rule":"保留后4位"}}}')
        _, oa, _ = run(["--parse", a])
        _, ob, _ = run(["--parse", b])
        self.assertEqual(oa, ob)
        fa = json.loads(oa)
        # registry order, not input order
        self.assertEqual([it["key"] for it in fa["items"]],
                         ["biometric/iris", "financial/card-no"])


class TestInputForms(unittest.TestCase):
    def test_inline_bare_path_atpath_stdin(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            fp = td / "cat.json"
            fp.write_text(VALID, encoding="utf-8")
            inline = json.loads(run(["--parse", VALID])[1])
            bare = json.loads(run(["--parse", str(fp)])[1])
            at = json.loads(run(["--parse", f"@{fp}"])[1])
            stdin = json.loads(run(["--parse", "-"], stdin=VALID)[1])
            # source differs by input form (by design); everything deterministic is identical
            for c in (bare, at, stdin):
                self.assertEqual(c["items"], inline["items"])
                self.assertEqual(c["counts"], inline["counts"])
                self.assertEqual(c["directive"], inline["directive"])
            self.assertEqual(inline["source"], "inline")
            self.assertEqual(bare["source"], str(fp))
            self.assertEqual(stdin["source"], "stdin")

    def test_missing_file_exits_1(self):
        rc, out, err = run(["--parse", str(Path(tempfile.gettempdir()) / "nope-cat.json")])
        self.assertEqual(rc, 1, err)


class TestStreamSeparation(unittest.TestCase):
    def test_stdout_single_json_stderr_progress(self):
        rc, out, err = run(["--parse", VALID])
        self.assertEqual(rc, 0)
        json.loads(out)  # exactly one JSON value on stdout
        self.assertIn("[sensitive_catalog]", err)


class TestRunsFromAnyCwd(unittest.TestCase):
    def test_runs_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out, err = run(["--parse", VALID], cwd=td)
            self.assertEqual(rc, 0, err)
            self.assertEqual(len(json.loads(out)["items"]), 3)


class TestValidateResolved(unittest.TestCase):
    """sensitive_catalog.validate_resolved — backs the adapters' --check on the field."""

    def test_null_is_valid(self):
        self.assertEqual(sensitive_catalog.validate_resolved(None), [])

    def test_valid_object(self):
        c, _ = sensitive_catalog._load_input(VALID)
        resolved = sensitive_catalog._validate_and_build(c, "inline")
        self.assertEqual(sensitive_catalog.validate_resolved(resolved), [])

    def test_unknown_category(self):
        self.assertTrue(sensitive_catalog.validate_resolved(
            {"version": 1, "categories": ["bogus"], "items": [], "counts": {}}))

    def test_counts_mismatch(self):
        c, _ = sensitive_catalog._load_input(VALID)
        resolved = sensitive_catalog._validate_and_build(c, "inline")
        resolved["counts"]["items"] = 999  # corrupt
        self.assertTrue(sensitive_catalog.validate_resolved(resolved))


class TestAntiDrift(unittest.TestCase):
    """DEFAULT_TEMPLATE = exactly 37 items; every key's category is closed-set."""

    def test_template_has_37_items(self):
        self.assertEqual(len(sensitive_catalog.DEFAULT_TEMPLATE["items"]), 37)

    def test_template_keys_use_closed_set_categories(self):
        for key in sensitive_catalog.DEFAULT_TEMPLATE["items"]:
            self.assertTrue(sensitive_catalog._KEY_RX.match(key), key)
            self.assertIn(key.split("/", 1)[0], sensitive_catalog.CATEGORIES)

    def test_categories_count_is_ten(self):
        self.assertEqual(len(sensitive_catalog.CATEGORIES), 10)

    def test_committed_example_matches_default_template(self):
        # The committed core/scripts/sensitive_catalog.json.example IS the shipped 37-item
        # template (install.sh copies it). It MUST stay byte-equivalent to DEFAULT_TEMPLATE
        # so --list and the file never drift (single source of truth = the script registry).
        import json as _json
        example = HERE.parent / "core" / "scripts" / "sensitive_catalog.json.example"
        self.assertTrue(example.is_file(), "sensitive_catalog.json.example missing")
        on_disk = _json.loads(example.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, sensitive_catalog.DEFAULT_TEMPLATE,
                         "committed sensitive_catalog.json.example drifted from "
                         "DEFAULT_TEMPLATE — regenerate via `sensitive_catalog.py --list`")


class TestZeroDeps(unittest.TestCase):
    def test_imports_only_stdlib(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        stdlib = set(sys.stdlib_module_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for n in node.names:
                    self.assertIn(n.name.split(".")[0], stdlib, f"non-stdlib import: {n.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                self.assertIn(node.module.split(".")[0], stdlib,
                              f"non-stdlib from-import: {node.module}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
