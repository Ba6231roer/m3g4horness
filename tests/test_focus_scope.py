#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""focus_scope.py regression (closed-set dimension-focus registry + parse/validate/render).

Covers: --list enumerates the 9 dimensions + facet counts; --parse renders a resolved
focus object (dimensions/facets/directive) for a valid subset and null for all-9;
closed-set violations exit 2 with an actionable stderr naming the offending key (unknown
dimension / unknown facet / facet on a facet-less dimension / facets entry for a
dimension not in dimensions / empty dimensions); malformed JSON exits 1; the directive is
deterministic (byte-identical across runs, registry order not input order); inline JSON
(starts with `{`), bare path, and `@path` input forms; stdout=JSON / stderr=diagnostics
split; runs from any cwd. Plus the anti-drift assertion: the registry's 9 dimension keys
are identical to the security-dimensions.md 维度键 column.

Run: py tests/test_focus_scope.py
"""
import json, re, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "focus_scope.py"
CATALOG = HERE.parent / "core" / "prompts" / "fragments" / "security-dimensions.md"
PY = sys.executable

# direct import (sibling) for registry / anti-drift assertions
sys.path.insert(0, str(HERE.parent / "core" / "scripts"))
import focus_scope


def run(args, cwd=None):
    r = subprocess.run([PY, str(SCRIPT), *args], cwd=str(cwd) if cwd else None,
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


class TestRegistry(unittest.TestCase):
    def test_list_nine_dimensions_with_facet_counts(self):
        rc, out, err = run(["--list"])
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        dims = d["dimensions"]
        self.assertEqual([x["key"] for x in dims], focus_scope.DIMENSION_KEYS)
        self.assertEqual(len(dims), 9)
        by_key = {x["key"]: x for x in dims}
        self.assertEqual([f["key"] for f in by_key["sensitive-data"]["facets"]],
                         ["id-card", "bank-card", "phone", "email", "password", "token"])
        self.assertEqual([f["key"] for f in by_key["injection"]["facets"]],
                         ["sqli", "xss", "command-injection", "path-traversal",
                          "ssrf", "deserialization", "xxe"])
        for k in ("horizontal-authz", "vertical-authz", "authentication",
                  "integrity", "audit", "rate-limiting", "secrets"):
            self.assertEqual(by_key[k]["facets"], [])


class TestParse(unittest.TestCase):
    def test_valid_subset_with_facets(self):
        rc, out, err = run(["--parse",
                            '{"dimensions":["sensitive-data","horizontal-authz"],'
                            '"facets":{"sensitive-data":["id-card","bank-card"]}}'])
        self.assertEqual(rc, 0, err)
        f = json.loads(out)
        self.assertEqual(f["dimensions"], ["sensitive-data", "horizontal-authz"])
        self.assertEqual(f["facets"], {"sensitive-data": ["id-card", "bank-card"]})
        self.assertIn("敏感数据", f["directive"])
        self.assertIn("范围外", f["directive"])

    def test_star_resolves_to_null(self):
        rc, out, _ = run(["--parse", '{"dimensions":"*"}'])
        self.assertEqual(rc, 0)
        self.assertIsNone(json.loads(out))

    def test_omitted_dimensions_resolves_to_null(self):
        rc, out, _ = run(["--parse", "{}"])
        self.assertEqual(rc, 0)
        self.assertIsNone(json.loads(out))

    def test_render_is_alias_of_parse(self):
        spec = '{"dimensions":["authentication"]}'
        _, a, _ = run(["--parse", spec])
        _, b, _ = run(["--render", spec])
        self.assertEqual(a, b)


class TestViolationsExit2(unittest.TestCase):
    def _bad(self, spec, needle):
        rc, out, err = run(["--check", spec])
        self.assertEqual(rc, 2, err)
        self.assertFalse(json.loads(out)["ok"])
        self.assertIn(needle, err)

    def test_unknown_dimension(self):
        self._bad('{"dimensions":["authz-broken"]}', "authz-broken")

    def test_unknown_facet(self):
        self._bad('{"dimensions":["sensitive-data"],"facets":{"sensitive-data":["ssn"]}}',
                  "ssn")

    def test_facet_on_facetless_dimension(self):
        self._bad('{"dimensions":["horizontal-authz"],"facets":{"horizontal-authz":["idor"]}}',
                  "horizontal-authz")

    def test_facet_for_dimension_not_in_dimensions(self):
        self._bad('{"dimensions":["authentication"],"facets":{"injection":["sqli"]}}',
                  "injection")

    def test_empty_dimensions_rejected(self):
        rc, out, err = run(["--check", '{"dimensions":[]}'])
        self.assertEqual(rc, 2, err)
        self.assertFalse(json.loads(out)["ok"])

    def test_malformed_json_exits_1(self):
        rc, out, err = run(["--parse", "{not json"])
        self.assertEqual(rc, 1, err)

    def test_non_object_json_exits_2(self):
        # a FILE holding syntactically-valid but non-object JSON → closed-set violation
        # (exit 2), not a read/parse failure (exit 1). (inline non-object is impossible:
        # only values beginning with `{` are inline JSON; any other value is a path.)
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "bad.json"
            fp.write_text('["sensitive-data"]', encoding="utf-8")
            rc, out, err = run(["--parse", str(fp)])
            self.assertEqual(rc, 2, err)


class TestDeterminism(unittest.TestCase):
    def test_directive_byte_identical_regardless_of_input_order(self):
        a = '{"dimensions":["injection","sensitive-data"],"facets":{"sensitive-data":["token","phone"]}}'
        b = '{"dimensions":["sensitive-data","injection"],"facets":{"sensitive-data":["phone","token"]}}'
        _, oa, _ = run(["--parse", a])
        _, ob, _ = run(["--parse", b])
        self.assertEqual(oa, ob)
        # registry order, not input order
        fa = json.loads(oa)
        self.assertEqual(fa["dimensions"], ["sensitive-data", "injection"])
        self.assertEqual(fa["facets"]["sensitive-data"], ["phone", "token"])


class TestInputForms(unittest.TestCase):
    def test_inline_bare_path_and_atpath(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            fp = td / "focus.json"
            fp.write_text('{"dimensions":["audit"]}', encoding="utf-8")
            inline = run(["--parse", '{"dimensions":["audit"]}'])[1]
            bare = run(["--parse", str(fp)])[1]
            at = run(["--parse", f"@{fp}"])[1]
            self.assertEqual(inline, bare)
            self.assertEqual(bare, at)

    def test_missing_file_exits_1(self):
        rc, out, err = run(["--parse", str(Path(tempfile.gettempdir()) / "nope-focus.json")])
        self.assertEqual(rc, 1, err)


class TestStreamSeparation(unittest.TestCase):
    def test_stdout_is_single_json_stderr_progress(self):
        rc, out, err = run(["--parse", '{"dimensions":["audit"]}'])
        self.assertEqual(rc, 0)
        # stdout parses as exactly one JSON value (the resolved focus)
        json.loads(out)
        self.assertIn("[focus_scope]", err)


class TestRunsFromAnyCwd(unittest.TestCase):
    def test_runs_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            rc, out, err = run(["--parse", '{"dimensions":["secrets"]}'], cwd=td)
            self.assertEqual(rc, 0, err)
            self.assertEqual(json.loads(out)["dimensions"], ["secrets"])


class TestValidateResolved(unittest.TestCase):
    """focus_scope.validate_resolved — backs the adapters' --check on change_context.focus."""

    def test_null_is_valid(self):
        self.assertEqual(focus_scope.validate_resolved(None), [])

    def test_valid_object(self):
        f = {"dimensions": ["sensitive-data"], "facets": {"sensitive-data": ["id-card"]},
             "directive": "..."}
        self.assertEqual(focus_scope.validate_resolved(f), [])

    def test_unknown_dimension(self):
        v = focus_scope.validate_resolved({"dimensions": ["bogus"]})
        self.assertTrue(v)

    def test_facet_dimension_mismatch(self):
        v = focus_scope.validate_resolved(
            {"dimensions": ["authentication"], "facets": {"injection": ["sqli"]}})
        self.assertTrue(v)


class TestAntiDrift(unittest.TestCase):
    """registry 9 dimension keys == security-dimensions.md 维度键 column (task 8.5)."""

    def _catalog_dim_keys(self):
        text = CATALOG.read_text(encoding="utf-8")
        keys = []
        for line in text.splitlines():
            if not line.startswith("|") or "---" in line:
                continue
            cols = [c.strip() for c in line.split("|")]
            # dimension table: | 维度 | 维度键 | 检查什么 | 典型缺口 | category |
            if len(cols) >= 6:
                m = re.match(r"`([a-z][a-z-]*)`$", cols[2])
                if m:
                    keys.append(m.group(1))
        return keys

    def test_registry_keys_match_catalog(self):
        self.assertEqual(self._catalog_dim_keys(), focus_scope.DIMENSION_KEYS)

    def test_registry_facet_keys_present_in_catalog(self):
        text = CATALOG.read_text(encoding="utf-8")
        for fc in focus_scope.FACETS["sensitive-data"]:
            self.assertIn(f"`{fc}`", text)
        for fc in focus_scope.FACETS["injection"]:
            self.assertIn(f"`{fc}`", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
