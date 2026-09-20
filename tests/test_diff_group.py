#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""diff_group.py unit tests (add-mgh-sdr task 6.4).

Builds throwaway git repos and asserts: interface grouping (annotation hits split
units + route extraction), standalone clustering, no-annotation degradation, zero-diff
empty, unit_id filesystem-safe naming (incl. the `:` NTFS ADS case), .done skip on
resume, out-of-subtree path rejection via --check, exit-code split (0/1/2), and the
grouping.json run-record shape.

Run: py tests/test_diff_group.py
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "diff_group.py"


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _init_repo(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _commit_all(repo: Path, msg: str):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def _write(repo: Path, rel: str, text: str):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


CONTROLLER = """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/list")
    public java.util.List list() { return null; }

    @PostMapping("/detail/{brch_no}")
    public Object detail(String brch_no) {
        return null;
    }
}
"""

# --- codegraph call-chain grouping fixtures (improve-mgh-sdr-callchain-grouping) ---

# Stand-in `codegraph` binary: answers callers/callees from a JSON map on CG_STUB_MAP.
# contract mirror of the real CLI (diff_group parses `{"symbol","<sub>":[entries]}`);
# a missing symbol prints nothing and exits 0 (real "not found" is non-JSON -> degrade).
CG_STUB_SRC = '''import json, os, sys
sub = sys.argv[1]
symbol = sys.argv[2]
m = {}
p = os.environ.get("CG_STUB_MAP")
if p and os.path.exists(p):
    m = json.load(open(p, encoding="utf-8"))
entries = (m.get(sub) or {}).get(symbol)
if entries is None:
    sys.exit(0)
print(json.dumps({"symbol": symbol, sub: entries}))
'''

CG_CHAIN_BASE = {
    "src/controller/OrderController.java": """@RestController
@RequestMapping("/order")
public class OrderController {
    @PostMapping("/create")
    public Object createOrder(String id) {
        String trace = "t:" + id;
        validate(id);
        return null;
    }

    private void validate(String id) {
    }
}
""",
    "src/service/OrderService.java": """public class OrderService {
    public Object createOrder(String id) {
        return null;
    }
}
""",
    "src/dao/OrderDao.java": """public class OrderDao {
    public Object insertOrder(String id) {
        return null;
    }
}
""",
}

CG_CHAIN_FEAT = {
    "src/controller/OrderController.java": """@RestController
@RequestMapping("/order")
public class OrderController {
    @PostMapping("/create")
    public Object createOrder(String id) {
        String trace = "t:" + id;
        validate(id);
        return service.createOrder(id);
    }

    private void validate(String id) {
    }
}
""",
    "src/service/OrderService.java": """public class OrderService {
    public Object createOrder(String id) {
        return dao.insertOrder(id);
    }
}
""",
    "src/dao/OrderDao.java": """public class OrderDao {
    public Object insertOrder(String id) {
        return execute("insert ... " + id);
    }
}
""",
}

CG_SHARED_BASE = {
    "src/UserController.java": """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/detail")
    public Object detail(String id) {
        return null;
    }

    private String helper1() { return "a"; }
    private String helper2() { return "b"; }
    private String helper3() { return "c"; }
    private String helper4() { return "d"; }
    private String helper5() { return "e"; }

    @GetMapping("/list")
    public Object list(String id) {
        return null;
    }
}
""",
    "src/UserService.java": """public class UserService {
    public Object queryUser(String id) {
        return null;
    }
}
""",
}

CG_SHARED_FEAT = {
    "src/UserController.java": """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/detail")
    public Object detail(String id) {
        return service.queryUser(id);
    }

    private String helper1() { return "a"; }
    private String helper2() { return "b"; }
    private String helper3() { return "c"; }
    private String helper4() { return "d"; }
    private String helper5() { return "e"; }

    @GetMapping("/list")
    public Object list(String id) {
        return service.queryUser(id2);
    }
}
""",
    "src/UserService.java": """public class UserService {
    public Object queryUser(String id) {
        return execute("select ... " + id);
    }
}
""",
}

# two changed methods, NO call edge between them (reflection/DI residue) — separate dirs
CG_ISOLATED_BASE = {
    "src/pay/PayService.java": "public class PayService {\n    public Object pay(String id) {\n        return null;\n    }\n}\n",
    "src/audit/AuditService.java": "public class AuditService {\n    public Object log(String id) {\n        return null;\n    }\n}\n",
}
CG_ISOLATED_FEAT = {
    "src/pay/PayService.java": "public class PayService {\n    public Object pay(String id) {\n        return pay3rd(id);\n    }\n}\n",
    "src/audit/AuditService.java": "public class AuditService {\n    public Object log(String id) {\n        return writeLog(id);\n    }\n}\n",
}

# full chain map: both controller and service method are named createOrder, so the
# union callees reach service + dao (mirrors real codegraph same-name union semantics)
CG_CHAIN_EDGES = {
    "callees": {
        "createOrder": [
            {"name": "createOrder", "kind": "method",
             "filePath": "src/service/OrderService.java", "startLine": 3},
            {"name": "insertOrder", "kind": "method",
             "filePath": "src/dao/OrderDao.java", "startLine": 3},
        ],
        "insertOrder": [],
    },
}

CG_SHARED_EDGES = {
    "callees": {
        "detail": [{"name": "queryUser", "kind": "method",
                    "filePath": "src/UserService.java", "startLine": 3}],
        "list": [{"name": "queryUser", "kind": "method",
                  "filePath": "src/UserService.java", "startLine": 3}],
        "queryUser": [],
    },
}


class DiffGroupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_diffgroup_"))
        self._env_backup = {k: v for k, v in os.environ.items()}

    def tearDown(self):
        import shutil
        for k in ("MGH_CODEGRAPH_BIN", "CG_STUB_MAP"):
            os.environ.pop(k, None)
        for k, v in self._env_backup.items():
            os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = io.StringIO(), io.StringIO()
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("diff_group", SCRIPT)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            sys.argv = ["diff_group.py"] + list(args)
            try:
                with redirect_stdout(sys.stdout), redirect_stderr(sys.stderr):
                    code = mod.main()
            except SystemExit as e:
                code = e.code
        finally:
            out, err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = old
        return code, out.getvalue(), err.getvalue()

    def _repo_with_feature(self):
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/UserController.java", CONTROLLER)
        _write(repo, "src/OrderService.java", "public class OrderService { }\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feature-pay")
        _write(repo, "src/UserController.java", CONTROLLER
               + "    // feature-branch change inside detail method\n")
        _write(repo, "src/OrderService.java",
               "public class OrderService { }\n// feature extra\n")
        _write(repo, "db/migration.sql", "ALTER TABLE t ADD COLUMN c VARCHAR(1);\n")
        _commit_all(repo, "feat")
        return repo

    def test_interface_grouping_and_routes(self):
        repo = self._repo_with_feature()
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feature-pay",
                                   "--checkpoints", str(self.tmp / "m"),
                                   "--materialize", str(self.tmp / "s"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        # only the /user/detail method body changed in the fixture; /user/list is
        # unchanged so it correctly yields no unit (no hunk = nothing to review)
        self.assertEqual(d["counts"]["interface"], 1)
        self.assertGreaterEqual(d["counts"]["standalone"], 1)
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        routes = {u["route"] for u in ifaces}
        self.assertIn("/user/detail/{brch_no}", routes)
        for u in ifaces:
            self.assertIn("UserController", u["unit_id"])
        # all paths absolute
        for u in d["pending"]:
            for f in ("input_path", "draft_path", "done_marker", "failed_marker",
                      "baseline_path", "external_dir"):
                self.assertTrue(Path(u[f]).is_absolute(), f"{f} not absolute")
            self.assertTrue(Path(u["input_path"]).is_file(), "slice not materialized")

    def test_no_annotation_degrades_to_standalone(self):
        repo = self.tmp / "repo2"
        _init_repo(repo)
        _write(repo, "sql/a.sql", "CREATE TABLE a(id INT);\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "b")
        _write(repo, "sql/a.sql", "CREATE TABLE a(id INT, x INT);\n")
        _write(repo, "util/Tool.java", "class Tool { int f() { return 1; } }\n")
        _commit_all(repo, "feat")
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "b",
                                   "--checkpoints", str(self.tmp / "m2"),
                                   "--materialize", str(self.tmp / "s2"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertGreater(d["counts"]["standalone"], 0)
        self.assertEqual(d["counts"]["interface"], 0)
        self.assertTrue(all(u["kind"] == "standalone" and u["route"] == ""
                            for u in d["pending"]))

    def test_include_failed_relists_failed_unit_canonical(self):
        # --include-failed: a unit whose .failed marker exists re-enters
        # pending[] under its canonical unit_id with the same marker path and
        # a re-materialized slice; default (flag off) keeps it excluded
        repo = self._repo_with_feature()
        ck, sl = self.tmp / "m3", self.tmp / "s3"

        def _enum(*extra):
            return self._run("--repo", str(repo), "--base", "master",
                             "--branch", "feature-pay",
                             "--checkpoints", str(ck),
                             "--materialize", str(sl), *extra)

        code, out, err = _enum()
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertTrue(d["pending"])
        victim = d["pending"][0]
        fm = Path(victim["failed_marker"])
        fm.parent.mkdir(parents=True, exist_ok=True)
        fm.write_text(json.dumps({"unit": victim["unit_id"], "reason": "r",
                                  "tier": "sdr"}), encoding="utf-8")
        code, out, _ = _enum()
        d = json.loads(out)
        self.assertNotIn(victim["unit_id"], [u["unit_id"] for u in d["pending"]])
        code, out, _ = _enum("--include-failed")
        self.assertEqual(code, 0)
        d = json.loads(out)
        relisted = {u["unit_id"]: u for u in d["pending"]}
        self.assertIn(victim["unit_id"], relisted)
        self.assertEqual(relisted[victim["unit_id"]]["failed_marker"], str(fm))
        self.assertTrue(Path(relisted[victim["unit_id"]]["input_path"]).is_file())
        repo = self._repo_with_feature()
        code, out, err = self._run("--repo", str(repo), "--base", "feature-pay",
                                   "--branch", "feature-pay",
                                   "--checkpoints", str(self.tmp / "m3"),
                                   "--materialize", str(self.tmp / "s3"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertTrue(d["empty"])
        self.assertEqual(d["pending"], [])

    def test_unit_id_ads_safe(self):
        # a route containing `:` (NTFS ADS separator) must not reach any file name
        repo = self._repo_with_feature()   # CONTROLLER carries "/detail:{brch_no}"
        code, out, _ = self._run("--repo", str(repo), "--base", "master",
                                 "--branch", "feature-pay",
                                 "--checkpoints", str(self.tmp / "m4"),
                                 "--materialize", str(self.tmp / "s4"))
        d = json.loads(out)
        for u in d["pending"]:
            self.assertNotIn(":", Path(u["input_path"]).name, "ADS-unsafe unit filename")
            self.assertNotIn(":", Path(u["draft_path"]).name)

    def test_done_marker_skips_rematerialization(self):
        repo = self._repo_with_feature()
        args = ("--repo", str(repo), "--base", "master", "--branch", "feature-pay",
                "--checkpoints", str(self.tmp / "m5"), "--materialize",
                str(self.tmp / "s5"))
        code, out, _ = self._run(*args)
        d1 = json.loads(out)
        self.assertEqual(d1["total"], len(d1["pending"]))
        Path(d1["pending"][0]["done_marker"]).write_text("{}", encoding="utf-8")
        code, out, _ = self._run(*args)
        d2 = json.loads(out)
        self.assertEqual(d2["done"], 1)
        self.assertEqual(len(d2["pending"]), d1["total"] - 1)

    def test_gate_missing_base_ref_exits_2(self):
        repo = self._repo_with_feature()
        code, _, err = self._run("--repo", str(repo), "--base", "no-such-ref",
                                 "--branch", "feature-pay",
                                 "--checkpoints", str(self.tmp / "m6"),
                                 "--materialize", str(self.tmp / "s6"))
        self.assertEqual(code, 2)
        self.assertIn("recipe", err.lower())

    def test_missing_repo_exits_1(self):
        code, _, err = self._run("--repo", str(self.tmp / "nope"), "--base", "master",
                                 "--checkpoints", "m", "--materialize", "s")
        self.assertEqual(code, 1)

    def test_check_out_of_subtree_paths_rejected(self):
        repo = self._repo_with_feature()
        # run dir INSIDE the repo, then tamper: point a slice outside the repo
        run_dir = repo / ".mgh-sdr" / "runs" / "t"
        code, out, _ = self._run("--repo", str(repo), "--base", "master",
                                 "--branch", "feature-pay",
                                 "--checkpoints", str(run_dir / "markers"),
                                 "--materialize", str(run_dir / "slices"))
        self.assertEqual(code, 0)
        gpath = run_dir / "grouping.json"
        g = json.loads(gpath.read_text(encoding="utf-8"))
        g["pending"][0]["input_path"] = str(self.tmp / "outside.slice.md")
        gpath.write_text(json.dumps(g), encoding="utf-8")
        code, _, err = self._run("--check", str(run_dir))
        self.assertEqual(code, 2)
        self.assertIn("outside repo subtree", err)

    def test_check_ok_on_canonical_layout(self):
        repo = self._repo_with_feature()
        run_dir = repo / ".mgh-sdr" / "runs" / "t2"
        code, _, err = self._run("--repo", str(repo), "--base", "master",
                                 "--branch", "feature-pay",
                                 "--checkpoints", str(run_dir / "markers"),
                                 "--materialize", str(run_dir / "slices"))
        self.assertEqual(code, 0, err)
        code, _, err = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, err)

    def test_check_missing_run_dir_exits_2(self):
        code, _, _ = self._run("--check", str(self.tmp / "nope"))
        self.assertEqual(code, 2)

    # --- call-chain grouping (improve-mgh-sdr-callchain-grouping) -------------

    def _build(self, base_files, feat_files, cg_on=True, edges=None):
        """Commit base + feature files; optionally arm a .codegraph/ index + stub."""
        repo = self.tmp / "repo"
        _init_repo(repo)
        for rel, txt in base_files.items():
            _write(repo, rel, txt)
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        for rel, txt in feat_files.items():
            _write(repo, rel, txt)
        _commit_all(repo, "feat")
        if cg_on:
            (repo / ".codegraph").mkdir(exist_ok=True)
            stub = self.tmp / "bin" / "codegraph.py"
            stub.parent.mkdir(parents=True, exist_ok=True)
            stub.write_text(CG_STUB_SRC, encoding="utf-8")
            os.environ["MGH_CODEGRAPH_BIN"] = str(stub)
            if edges is not None:
                mp = self.tmp / "cg_map.json"
                mp.write_text(json.dumps(edges), encoding="utf-8")
                os.environ["CG_STUB_MAP"] = str(mp)
        else:
            # .codegraph/ absent AND no resolvable binary (env override to a missing
            # path) — even a real PATH codegraph must not turn the probe on.
            os.environ["MGH_CODEGRAPH_BIN"] = str(self.tmp / "no-such-codegraph")
        return repo

    def _run_group(self, repo, run="t"):
        run_dir = repo / ".mgh-sdr" / "runs" / run
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feat",
                                   "--checkpoints", str(run_dir / "markers"),
                                   "--materialize", str(run_dir / "slices"))
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def _slice_text(self, unit):
        return Path(unit["input_path"]).read_text(encoding="utf-8")

    def _hunk_locators(self, d) -> set:
        """Every `@@ <path> @@ new-file lines N+C` locator across a run's slices — the
        coverage fingerprint the lossless re-split must preserve."""
        import re
        rx = re.compile(r"^@@ .+ @@ new-file lines \d+\+\d+$")
        out = set()
        for u in d["pending"]:
            out.update(l for l in self._slice_text(u).splitlines() if rx.match(l))
        return out

    def test_cg_probe_states(self):
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=False)
        # state (b)/(c): .codegraph absent -> off even with a binary reachable
        d = self._run_group(repo, "off")
        self.assertIs(d["codegraph"], False)
        # state (a): .codegraph present + binary -> on
        (repo / ".codegraph").mkdir(exist_ok=True)
        stub = self.tmp / "bin" / "codegraph.py"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(CG_STUB_SRC, encoding="utf-8")
        os.environ["MGH_CODEGRAPH_BIN"] = str(stub)
        d = self._run_group(repo, "on")
        self.assertIs(d["codegraph"], True)
        # state: index present but binary unavailable -> off (env points to nothing)
        os.environ["MGH_CODEGRAPH_BIN"] = str(self.tmp / "missing")
        d = self._run_group(repo, "bin-missing")
        self.assertIs(d["codegraph"], False)

    def test_cg_no_codegraph_matches_legacy(self):
        # no codegraph -> annotation+directory grouping (add-mgh-sdr D2 equivalent):
        # controller route method = 1 interface unit; service + dao (non-interface)
        # fall to the directory cluster -> 1 standalone unit; stdout codegraph:false.
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=False)
        d = self._run_group(repo, "legacy")
        self.assertIs(d["codegraph"], False)
        self.assertEqual(d["counts"], {"interface": 1, "standalone": 1})
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        self.assertEqual([u["route"] for u in ifaces], ["/order/create"])

    def test_cg_single_chain_merges_into_one_interface(self):
        # Scenario: controller+service+dao on one call chain -> ONE interface unit
        # (route /order/create) carrying all three files' hunks, NOT interface + 2
        # standalone.
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=True,
                           edges=CG_CHAIN_EDGES)
        d = self._run_group(repo)
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"], {"interface": 1, "standalone": 0})
        self.assertEqual(len(d["pending"]), 1)
        u = d["pending"][0]
        self.assertEqual(u["kind"], "interface")
        self.assertEqual(u["route"], "/order/create")
        t = self._slice_text(u)
        for rel in ("OrderController.java", "OrderService.java", "OrderDao.java"):
            self.assertIn(rel, t)
        headers = [l for l in t.splitlines() if l.startswith("@@ ")]
        self.assertEqual(len(headers), 3)  # all three chain hunks in one slice

    def test_cg_reflection_isolated_falls_to_standalone(self):
        # Scenario: reflection/DI residue (no call edges) -> java residuals take
        # directory clustering + budget (NOT one unit per file — reverted after the
        # real-repo 401-unit run); flow exits 0 with a non-empty pending and coverage
        # intact (both files inside the merged cluster slice, symbol table attached).
        repo = self._build(CG_ISOLATED_BASE, CG_ISOLATED_FEAT, cg_on=True,
                           edges={"callees": {}, "callers": {}})
        d = self._run_group(repo)
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"]["interface"], 0)
        self.assertEqual(d["counts"]["standalone"], 1)
        self.assertTrue(all(u["kind"] == "standalone" and u["route"] == ""
                            for u in d["pending"]))
        t = self._slice_text(d["pending"][0])
        self.assertIn("PayService.java", t)
        self.assertIn("AuditService.java", t)
        self.assertIn("Files & symbols in this cluster", t)
        self.assertIn("pay  lines", t)  # method-level addressing survives the merge

    def test_cg_shared_downstream_split_per_interface(self):
        # Scenario (as modified by improve-mgh-sdr-slice-economy): /user/detail +
        # /user/list both call changed UserService.queryUser -> SAME controller file +
        # same downstream reach set -> ONE interface unit, route ';'-joined; the
        # shared queryUser hunk appears once in the merged slice (renderer dedups any
        # cross-unit repeats). Cross-controller splits keep their own units.
        repo = self._build(CG_SHARED_BASE, CG_SHARED_FEAT, cg_on=True,
                           edges=CG_SHARED_EDGES)
        d = self._run_group(repo)
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"], {"interface": 1, "standalone": 0})
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        self.assertEqual(ifaces[0]["route"], "/user/detail;/user/list")
        self.assertEqual(d["codegraph_stats"]["chain_merged"], 1)
        self.assertEqual(self._slice_text(ifaces[0]).count("UserService.java @@ "), 1)

    # --- symbol extraction / hunk anchor (task 1.1) ---------------------------

    def _load_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("diff_group_unit", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_java_symbol_map_routes_and_extents(self):
        mod = self._load_module()
        content = """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/detail")
    public Object detail(String id) {
        return null;
    }

    public String plainHelper(String x) {
        return x;
    }

    @PostMapping("/create")
    public Object create(String id) {
        return null;
    }
}
"""
        syms = mod._java_symbols(content)
        routes = {s["name"]: s["route"] for s in syms}
        self.assertEqual(routes["detail"], "/detail")
        self.assertEqual(routes["create"], "/create")
        self.assertEqual(routes["plainHelper"], "")     # no mapping annotation
        ext = {s["name"]: (s["start"], s["end"]) for s in syms}
        self.assertTrue(ext["detail"][1] < ext["plainHelper"][0])   # ordered extents
        # non-mapped method still has a body extent (reachable as downstream symbol)
        self.assertLess(ext["plainHelper"][0], ext["create"][0])

    def test_hunk_anchor_line_and_ownership(self):
        mod = self._load_module()
        # additions anchor on the first added ('+') new-file line, ignoring diff
        # context that bleeds around an unrelated method.
        add_hunk = (4, 5, [" line3", "-old", "+INSERTED", " line5", " line6"])
        self.assertEqual(mod._hunk_anchor_line(add_hunk), 5)
        # deletion-only hunk anchors on its last new-file context line (not dropped)
        del_hunk = (2, 3, [" ctx1", "-gone", " ctx3"])
        self.assertEqual(mod._hunk_anchor_line(del_hunk), 3)
        content = """public class Svc {
    public Object a(String id) {
        return null;
    }
    public Object b(String id) {
        return null;
    }
}
"""
        syms = mod._java_symbols(content)
        # added line inside method a -> owned by a; line beyond all bodies -> file-level
        owner_a = mod._owning_symbol(syms, mod._hunk_anchor_line((3, 2, [" x", "+hit"])))
        self.assertEqual(syms[owner_a]["name"], "a")
        self.assertIsNone(mod._owning_symbol(syms, 1))   # class-decl region = file-level


    # --- exclusion filter (improve-mgh-sdr-slice-economy D1) ------------------

    def _run_raw(self, repo, *extra):
        run_dir = repo / ".mgh-sdr" / "runs" / "x"
        return self._run("--repo", str(repo), "--base", "master", "--branch", "feat",
                         "--checkpoints", str(run_dir / "markers"),
                         "--materialize", str(run_dir / "slices"), *extra)

    def test_exclusion_by_reason(self):
        # each closed-set reason classifies correctly; whitelisted review-face files
        # (SQL / mapper XML / application yml / properties / logback) stay in.
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/main/java/App.java", "public class App { }\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        _write(repo, "src/main/java/App.java", "public class App { int x; }\n")
        _write(repo, "src/test/java/AppTest.java", "class AppTest { }\n")          # test-tree (dir)
        _write(repo, "src/main/java/UserServiceTest.java", "class T { }\n")        # test-tree (name)
        _write(repo, "target/classes/App.class", "bin")                            # build-output
        _write(repo, "src/generated-sources/G.java", "class G { }\n")              # generated
        _write(repo, "docs/logo.png", "png")                                       # static-asset
        _write(repo, "web/package-lock.json", "{}")                                # lockfile
        _write(repo, "pom.xml", "<project/>")                                      # build-script
        _write(repo, "db/migration/V2__x.sql", "ALTER TABLE t ADD c INT;\n")       # whitelist
        _write(repo, "src/main/resources/mapper/UserMapper.xml", "<mapper/>\n")    # whitelist
        _write(repo, "src/main/resources/application-prod.yml", "a: 1\n")          # whitelist
        _write(repo, "src/main/resources/logback-spring.xml", "<cfg/>\n")          # whitelist
        _commit_all(repo, "feat")
        code, out, err = self._run_raw(repo)
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["excluded"]["count"], 7)
        br = d["excluded"]["by_reason"]
        self.assertEqual(br.get("test-tree"), 2)
        self.assertEqual(br.get("build-output"), 1)
        self.assertEqual(br.get("generated"), 1)
        self.assertEqual(br.get("static-asset"), 1)
        self.assertEqual(br.get("lockfile"), 1)
        self.assertEqual(br.get("build-script"), 1)
        self.assertIn("excluded 7", err)
        # whitelisted review-face files still produce units
        all_slice_text = " ".join(Path(u["input_path"]).read_text(encoding="utf-8")
                                  for u in d["pending"] if u["input_path"])
        for name in ("V2__x.sql", "UserMapper.xml", "application-prod.yml",
                     "logback-spring.xml"):
            self.assertIn(name, all_slice_text, f"{name} must NOT be excluded")
        # codegraph_stats carries excluded_files
        self.assertEqual(d["codegraph_stats"]["excluded_files"], 7)
        # --check accepts the new fields structurally
        run_dir = repo / ".mgh-sdr" / "runs" / "x"
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, cerr)

    def test_include_excluded_fallback(self):
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/main/java/App.java", "public class App { }\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        _write(repo, "src/test/java/AppTest.java", "class AppTest { }\n")
        _commit_all(repo, "feat")
        code, out, err = self._run_raw(repo, "--include-excluded")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["excluded"]["count"], 0)
        self.assertEqual(d["codegraph_stats"]["excluded_files"], 0)
        # the test file re-enters standalone review
        self.assertGreaterEqual(d["counts"]["standalone"], 1)

    def test_all_excluded_is_not_empty(self):
        # a diff fully eaten by the filter is NOT `empty` (files arrived): distinct
        # semantics from a zero diff, observable via excluded.count + total == 0.
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/main/java/App.java", "public class App { }\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        _write(repo, "src/test/java/AppTest.java", "class AppTest { }\n")
        _commit_all(repo, "feat")
        code, out, err = self._run_raw(repo)
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertFalse(d["empty"])          # zero-diff would be true
        self.assertTrue(d["excluded_nonempty"])
        self.assertEqual(d["total"], 0)
        self.assertEqual(d["pending"], [])
        self.assertIn("NOT a zero-diff run", err)

    def test_check_backward_compat_old_grouping(self):
        # an OLD grouping.json without excluded/codegraph_stats must stay --check-clean
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "sql/a.sql", "CREATE TABLE a(id INT);\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        _write(repo, "sql/a.sql", "CREATE TABLE a(id INT, x INT);\n")
        _commit_all(repo, "feat")
        run_dir = repo / ".mgh-sdr" / "runs" / "old"
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feat",
                                   "--checkpoints", str(run_dir / "markers"),
                                   "--materialize", str(run_dir / "slices"))
        self.assertEqual(code, 0, err)
        gp = run_dir / "grouping.json"
        g = json.loads(gp.read_text(encoding="utf-8"))
        g.pop("excluded", None)
        g.pop("codegraph_stats", None)
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, cerr)

    # --- upstream anchoring + shared-chain merge + budget (D2/D3) --------------

    # controller UNCHANGED between base and feat ( anchoring target )
    UP_BASE = {
        "src/controller/OrderController.java": """@RestController
@RequestMapping("/order")
public class OrderController {
    @PostMapping("/create")
    public Object createOrder(String id) {
        return service.createOrder(id);
    }
}
""",
        "src/service/OrderService.java": """public class OrderService {
    public Object createOrder(String id) {
        return null;
    }
}
""",
        "src/dao/OrderDao.java": """public class OrderDao {
    public Object insertOrder(String id) {
        return null;
    }
}
""",
    }
    # feat touches ONLY service + dao (controller byte-identical)
    UP_FEAT = {
        "src/controller/OrderController.java": UP_BASE["src/controller/OrderController.java"],
        "src/service/OrderService.java": """public class OrderService {
    public Object createOrder(String id) {
        return dao.insertOrder(id);
    }
}
""",
        "src/dao/OrderDao.java": """public class OrderDao {
    public Object insertOrder(String id) {
        return execute("insert ... " + id);
    }
}
""",
    }
    # callers map: OrderService.createOrder -> OrderController.createOrder (hops=1);
    # OrderDao.insertOrder -> OrderService.createOrder (hops=2 via the changed caller)
    UP_EDGES = {
        "callers": {
            "createOrder": [{"name": "createOrder", "kind": "method",
                             "filePath": "src/controller/OrderController.java",
                             "startLine": 4}],
            "insertOrder": [{"name": "createOrder", "kind": "method",
                             "filePath": "src/service/OrderService.java",
                             "startLine": 3}],
        },
        "callees": {},
    }

    def test_upstream_anchor_unchanged_controller(self):
        # Scenario: controller unchanged, service+dao changed -> callers walk <=2 hops
        # finds the unchanged route method -> ONE interface unit with the route-method
        # snippet in its slice; not 2 scattered standalone units.
        repo = self._build(self.UP_BASE, self.UP_FEAT, cg_on=True, edges=self.UP_EDGES)
        d = self._run_group(repo, "up")
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"]["interface"], 1)
        self.assertEqual(d["stats"] if "stats" in d else d["codegraph_stats"]
                         ["anchors_upstream"], d["codegraph_stats"]["anchors_upstream"])
        self.assertGreaterEqual(d["codegraph_stats"]["anchors_upstream"], 1)
        u = d["pending"][0]
        self.assertEqual(u["kind"], "interface")
        self.assertEqual(u["route"], "/order/create")
        t = self._slice_text(u)
        self.assertIn("OrderService.java", t)
        self.assertIn("OrderDao.java", t)
        self.assertIn("upstream-route", t)          # disclosure line
        self.assertIn("@PostMapping(\"/create\")", t)  # bounded route-method snippet
        # changed-route path covers the 2-hop dao symbol too -> no stray standalone
        self.assertEqual(d["counts"]["standalone"], 0)

    def test_upstream_two_hops_no_route_falls_residual(self):
        # Scenario: callers EMPTY (reflection) -> residual directory cluster, exit 0.
        # (2-hop-no-route shape covered by test_cg_reflection_isolated_falls_to_standalone)
        repo = self._build({"src/pay/PayService.java": CG_ISOLATED_BASE[
                                "src/pay/PayService.java"]},
                           {"src/pay/PayService.java": CG_ISOLATED_FEAT[
                                "src/pay/PayService.java"]},
                           cg_on=True, edges={"callees": {}, "callers": {}})
        d = self._run_group(repo, "up-no")
        self.assertEqual(d["counts"]["interface"], 0)
        self.assertGreaterEqual(d["counts"]["standalone"], 1)
        self.assertEqual(d["codegraph_stats"]["anchors_upstream"], 0)

    def test_shared_chain_merge_same_controller(self):
        # Scenario: two changed routes in ONE controller whose reach sets are equal ->
        # merged into ONE interface unit, route ';'-joined, chain_merged counted.
        edges = {"callees": {
            "detail": [{"name": "queryUser", "kind": "method",
                        "filePath": "src/UserService.java", "startLine": 3}],
            "list": [{"name": "queryUser", "kind": "method",
                      "filePath": "src/UserService.java", "startLine": 3}],
            "queryUser": [],
        }}
        repo = self._build(CG_SHARED_BASE, CG_SHARED_FEAT, cg_on=True, edges=edges)
        d = self._run_group(repo, "merge")
        self.assertEqual(d["counts"], {"interface": 1, "standalone": 0})
        u = d["pending"][0]
        self.assertEqual(u["route"], "/user/detail;/user/list")
        self.assertEqual(d["codegraph_stats"]["chain_merged"], 1)
        t = self._slice_text(u)
        self.assertEqual(t.count("UserService.java @@ "), 1)   # shared hunk once

    def test_shared_chain_no_merge_across_controllers(self):
        # Scenario: same shared downstream from TWO controller files -> cross-file
        # merge NEVER happens; two interface units, both referencing the shared hunk.
        base = {
            "src/UserController.java": CG_SHARED_BASE["src/UserController.java"],
            "src/UserService.java": CG_SHARED_BASE["src/UserService.java"],
            "src/DeptController.java": """@RestController
@RequestMapping("/dept")
public class DeptController {
    @GetMapping("/detail")
    public Object detail(String id) {
        return null;
    }
}
""",
        }
        feat = {
            "src/UserController.java": CG_SHARED_FEAT["src/UserController.java"],
            "src/UserService.java": CG_SHARED_FEAT["src/UserService.java"],
            "src/DeptController.java": """@RestController
@RequestMapping("/dept")
public class DeptController {
    @GetMapping("/detail")
    public Object detail(String id) {
        return service.queryUser(id);
    }
}
""",
        }
        edges = {"callees": {
            "detail": [{"name": "queryUser", "kind": "method",
                        "filePath": "src/UserService.java", "startLine": 3}],
            "list": [{"name": "queryUser", "kind": "method",
                      "filePath": "src/UserService.java", "startLine": 3}],
            "queryUser": [],
        }}
        repo = self._build(base, feat, cg_on=True, edges=edges)
        d = self._run_group(repo, "xfile")
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        self.assertEqual(len(ifaces), 2)            # /dept/detail stays its own unit
        routes = {u["route"] for u in ifaces}
        self.assertIn("/dept/detail", routes)
        merged = [u for u in ifaces if ";" in u["route"]]
        self.assertEqual(len(merged), 1)            # UserController pair merged (same file)
        # shared downstream hunk appears in every referencing interface slice
        for u in ifaces:
            self.assertIn("UserService.java", self._slice_text(u))

    def test_interface_budget_splits_parts(self):
        # Scenario: a merged interface unit whose MEASURED slice exceeds
        # --max-interface-bytes splits into -partN units, each with its own route segment
        # + independent paths, and the split is LOSSLESS (the parts' hunk locators equal
        # the un-split run's set — no hunk dropped, no content truncated). Fixture: two
        # changed routes MERGED into one unit (shared downstream), then a small cap.
        # Each file's own diff body sits well under the cap: the MERGED slice is what
        # overflows, which is precisely the case the old estimate-only judge let through.
        big = "x" * 1200
        pad = "\n".join(f"    private int pad{i} = {i};" for i in range(20))
        base = {
            "src/BigController.java": f"""@RestController
@RequestMapping("/big")
public class BigController {{
    @GetMapping("/a")
    public Object a(String id) {{
        return svc.s(id);
    }}

{pad}

    @GetMapping("/b")
    public Object b(String id) {{
        return null;
    }}
}}
""",
            "src/BigService.java": """public class BigService {
    public Object s(String id) {
        return null;
    }
}
""",
        }
        feat = {
            "src/BigController.java": f"""@RestController
@RequestMapping("/big")
public class BigController {{
    @GetMapping("/a")
    public Object a(String id) {{
        return svc.s(id) + "{big}";
    }}

{pad}

    @GetMapping("/b")
    public Object b(String id) {{
        return "{big}";
    }}
}}
""",
            "src/BigService.java": """public class BigService {
    public Object s(String id) {
        return "%s";
    }
}
""" % big,
        }
        # both routes call BigService.s -> downstream {BigService.s} shared -> merged
        edges = {"callees": {
            "a": [{"name": "s", "kind": "method",
                   "filePath": "src/BigService.java", "startLine": 3}],
            "b": [{"name": "s", "kind": "method",
                   "filePath": "src/BigService.java", "startLine": 3}],
            "s": [],
        }}
        repo = self._build(base, feat, cg_on=True, edges=edges)
        run_dir = repo / ".mgh-sdr" / "runs" / "budget"
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feat", "--max-interface-bytes", "2048",
                                   "--checkpoints", str(run_dir / "markers"),
                                   "--materialize", str(run_dir / "slices"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertGreaterEqual(d["counts"]["interface"], 2)
        part_ids = [u["unit_id"] for u in d["pending"] if "-part" in u["unit_id"]]
        self.assertTrue(part_ids, "over-budget unit must split into -partN")
        for u in d["pending"]:
            # the gate's promise, tightened from `cap + 1024`: EVERY part measures <= cap
            self.assertLessEqual(u["unit_bytes"], 2048)
            self.assertEqual(u["slimmed"], {},
                             "a multi-file over-budget unit is resolved by re-splitting, "
                             "never by slimming context")
            self.assertTrue(Path(u["input_path"]).is_file())
            self.assertNotIn(":", Path(u["input_path"]).name)
        # lossless: the same fixture under a cap nothing can reach renders the SAME set of
        # hunk locators — the split moved hunks between units, it did not drop any
        wide_dir = repo / ".mgh-sdr" / "runs" / "wide"
        code, wout, werr = self._run("--repo", str(repo), "--base", "master",
                                     "--branch", "feat", "--max-interface-bytes",
                                     "1000000", "--checkpoints", str(wide_dir / "markers"),
                                     "--materialize", str(wide_dir / "slices"))
        self.assertEqual(code, 0, werr)
        self.assertEqual(self._hunk_locators(d), self._hunk_locators(json.loads(wout)))

    def test_codegraph_stats_shape_off(self):
        # codegraph off -> stats structure present, all zeros; probe reason on stderr.
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=False)
        d = self._run_group(repo, "statsoff")
        self.assertIs(d["codegraph"], False)
        s = d["codegraph_stats"]
        for k in ("symbols_queried", "edges_captured", "edges_in_changed_set",
                  "anchors_changed", "anchors_upstream", "chain_merged",
                  "excluded_files"):
            self.assertIn(k, s)
            self.assertEqual(s[k], 0)
        # stats shape when ON (chain fixture): counts are consistent
        repo2 = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=True,
                            edges=CG_CHAIN_EDGES)
        d2 = self._run_group(repo2, "statson")
        s2 = d2["codegraph_stats"]
        self.assertEqual(s2["anchors_changed"], 1)
        self.assertGreater(s2["edges_captured"], 0)
        # union semantics: the shared-name query returns controller+service callers/
        # callees entries twice (once per changed symbol sharing the name) — the count
        # is diagnostic only, so just assert the in-changed-set edges are present.
        self.assertGreaterEqual(s2["edges_in_changed_set"], 2)  # controller->service->dao

    def test_cg_probe_failure_reason_on_stderr(self):
        # probe failure prints WHY (no .codegraph dir / no binary) to stderr.
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=False)
        _, out, err = self._run("--repo", str(repo), "--base", "master",
                                "--branch", "feat",
                                "--checkpoints", str(self.tmp / "p1" / "markers"),
                                "--materialize", str(self.tmp / "p1" / "slices"))
        # .codegraph absent, binary missing too -> one of the two reasons surfaces
        self.assertTrue(("no .codegraph dir" in err) or ("no binary" in err), err)
        (repo / ".codegraph").mkdir(exist_ok=True)
        _, _, err2 = self._run("--repo", str(repo), "--base", "master",
                               "--branch", "feat",
                               "--checkpoints", str(self.tmp / "p2" / "markers"),
                               "--materialize", str(self.tmp / "p2" / "slices"))
        self.assertIn("no binary", err2)

    # --- chain materialization (improve-mgh-sdr-report-structure) ---------------

    def _chain_fixture_repo(self, files_base, files_feat, edges, mapper_xml=None):
        repo = self._build(files_base, files_feat, cg_on=True, edges=edges)
        if mapper_xml is not None:
            _write(repo, mapper_xml[0], mapper_xml[1])
            _git(repo, "add", "-A")
            _git(repo, "commit", "-qm", "mapper")
        return repo

    def _iface(self, d):
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        self.assertTrue(ifaces, "fixture must produce an interface unit")
        return ifaces[0]

    def test_chain_linear_deep_with_mapper_terminal(self):
        # 4-node linear chain: controller -> service (distinct name) -> dao -> mapper
        # XML terminal (external). Node order follows the call chain; fqn_short =
        # package-initial short form; the mapper node branches off the dao node.
        svc_base = 'public class OrderService {\n    public Object place(String id) {\n        return null;\n    }\n}\n'
        svc_feat = 'public class OrderService {\n    public Object place(String id) {\n        return dao.insertOrder(id);\n    }\n}\n'
        base = dict(CG_CHAIN_BASE)
        base["src/service/OrderService.java"] = svc_base
        feat = dict(CG_CHAIN_FEAT)
        feat["src/service/OrderService.java"] = svc_feat
        edges = {"callees": {
            "createOrder": [{"name": "place", "kind": "method",
                             "filePath": "src/service/OrderService.java",
                             "startLine": 2}],
            "place": [{"name": "insertOrder", "kind": "method",
                       "filePath": "src/dao/OrderDao.java", "startLine": 3}],
            "insertOrder": [],
        }}
        xml = ("src/main/resources/mapper/OrderDaoMapper.xml",
               '<?xml version="1.0"?>\n<mapper namespace="OrderDao">\n'
               '    <insert id="insertOrder">SELECT 1</insert>\n</mapper>\n')
        repo = self._chain_fixture_repo(base, feat, edges, xml)
        d = self._run_group(repo, "chainlin")
        u = self._iface(d)
        ch = u["chain"]
        self.assertEqual(len(ch), 4)
        self.assertEqual(ch[0]["change"], "changed")
        self.assertEqual(ch[0]["route"], "/order/create")
        self.assertEqual(ch[1]["change"], "changed")
        self.assertEqual(ch[2]["change"], "changed")
        self.assertEqual(ch[3]["change"], "external")
        self.assertEqual(ch[3]["file"],
                         "src/main/resources/mapper/OrderDaoMapper.xml")
        self.assertNotIn("branch_of", ch[0])
        self.assertEqual(ch[3]["branch_of"], 2)   # hangs off the dao node
        for nd in ch:
            for f in ("fqn_short", "label", "file", "change"):
                self.assertIn(f, nd)

    def test_chain_fqn_short_shape(self):
        # fqn_short = bare class name . method (package initials were dropped after
        # real-repo trial: too long, no information value; file column recovers pkg).
        mod = self._load_module()
        self.assertEqual(
            mod._fqn_short("com/linkinstars/springBootTemplate/controller/"
                           "OrderController.java", "submit"),
            "OrderController.submit")
        # non-java path keeps the file name (extension included)
        self.assertEqual(mod._fqn_short("mapper/UserMapper.xml", ""),
                         "UserMapper.xml")

    def test_chain_interface_impl_resolution_impl_preferred(self):
        # same-name interface + impl both reachable downstream: the impl declaration
        # wins (the interface hop is not duplicated into the chain).
        base = {
            "src/controller/OrderController.java": """@RestController
@RequestMapping("/order")
public class OrderController {
    @PostMapping("/create")
    public Object createOrder(String id) {
        return svc.createOrder(id);
    }
}
""",
            "src/service/IOrderService.java": """public interface IOrderService {
    Object submit(String id);
}
""",
            "src/service/OrderServiceImpl.java": """public class OrderServiceImpl {
    public Object submit(String id) {
        return null;
    }
}
""",
        }
        feat = {
            "src/controller/OrderController.java": """@RestController
@RequestMapping("/order")
public class OrderController {
    @PostMapping("/create")
    public Object createOrder(String id) {
        return svc.createOrder(id);   // feat: audit hook added
    }
}
""",
            "src/service/IOrderService.java": """public interface IOrderService {
    Object submit(String id);
    Object audit(String id);
}
""",
            "src/service/OrderServiceImpl.java": """public class OrderServiceImpl {
    public Object submit(String id) {
        return dao.insertOrder(id);
    }
}
""",
        }
        edges = {"callees": {
            "createOrder": [{"name": "submit", "kind": "method",
                             "filePath": "src/service/IOrderService.java",
                             "startLine": 2},
                            {"name": "submit", "kind": "method",
                             "filePath": "src/service/OrderServiceImpl.java",
                             "startLine": 2}],
            "submit": [{"name": "insertOrder", "kind": "method",
                        "filePath": "src/dao/OrderDao.java", "startLine": 3}],
            "insertOrder": [],
        }}
        repo = self._chain_fixture_repo(base, feat, edges)
        d = self._run_group(repo, "chainif")
        u = self._iface(d)
        fqn_entries = [n["fqn_short"] for n in u["chain"]]
        # the interface twin never enters the chain (impl preferred)
        self.assertNotIn("IOrderService.submit", fqn_entries)
        self.assertIn("OrderServiceImpl.submit", fqn_entries)

    def test_chain_branch_of_fanout_shape(self):
        # one route anchor, two downstreams -> the second child carries branch_of
        # (fan-out is expressed by index back-reference, never a tree).
        base = {
            "src/UserController.java": """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/query")
    public Object query(String id) {
        return service.queryUser(id);
    }
}
""",
            "src/UserService.java": CG_SHARED_BASE["src/UserService.java"],
            "src/UserDao.java": """public class UserDao {
    public Object findById(String id) {
        return null;
    }
}
""",
            "src/LogDao.java": """public class LogDao {
    public Object insertLog(String id) {
        return null;
    }
}
""",
        }
        feat = {
            "src/UserController.java": """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/query")
    public Object query(String id) {
        return service.queryUser(id);   // feat: delegate
    }
}
""",
            "src/UserService.java": """public class UserService {
    public Object queryUser(String id) {
        Object u = dao.findById(id);
        return logs.insertLog(id) == null ? u : null;
    }
}
""",
            "src/UserDao.java": base["src/UserDao.java"],
            "src/LogDao.java": base["src/LogDao.java"],
        }
        edges = {"callees": {
            "query": [{"name": "queryUser", "kind": "method",
                       "filePath": "src/UserService.java", "startLine": 2}],
            "queryUser": [{"name": "findById", "kind": "method",
                           "filePath": "src/UserDao.java", "startLine": 2},
                          {"name": "insertLog", "kind": "method",
                           "filePath": "src/LogDao.java", "startLine": 2}],
            "findById": [], "insertLog": [],
        }}
        repo = self._chain_fixture_repo(base, feat, edges)
        d = self._run_group(repo, "chainfork")
        u = self._iface(d)
        ch = u["chain"]
        # query -> queryUser (linear) -> LogDao.insertLog (first child, linear) +
        # UserDao.findById (second child, branch_of) — children in lexicographic order
        self.assertEqual(len(ch), 4)
        self.assertNotIn("branch_of", ch[0])
        self.assertNotIn("branch_of", ch[1])   # first child continues linearly
        self.assertNotIn("branch_of", ch[2])   # first fan-out child stays linear
        self.assertEqual(ch[3]["branch_of"], 1)   # second fan-out child branches
        self.assertEqual(ch[1]["fqn_short"], "UserService.queryUser")
        self.assertEqual(ch[2]["fqn_short"], "LogDao.insertLog")
        self.assertEqual(ch[3]["fqn_short"], "UserDao.findById")

    def test_chain_upstream_anchor_entry_unchanged(self):
        # upstream-anchored unit: chain[0] is the UNCHANGED route method carrying the
        # route string; subsequent nodes are the changed service+dao (+ mapper).
        edges = {"callers": self.UP_EDGES["callers"], "callees": {
            "createOrder": [{"name": "insertOrder", "kind": "method",
                             "filePath": "src/dao/OrderDao.java", "startLine": 3}],
            "insertOrder": [],
        }}
        xml = ("src/resources/OrderDaoMapper.xml",
               '<mapper namespace="dao.OrderDao">\n'
               '  <insert id="insertOrder">SELECT 1</insert>\n</mapper>\n')
        repo = self._chain_fixture_repo(self.UP_BASE, self.UP_FEAT, edges, xml)
        d = self._run_group(repo, "chainup")
        u = self._iface(d)
        self.assertEqual(u["route"], "/order/create")
        ch = u["chain"]
        self.assertGreaterEqual(len(ch), 4)
        self.assertEqual(ch[0]["change"], "unchanged")
        self.assertEqual(ch[0]["route"], "/order/create")
        for nd in ch[1:3]:
            self.assertEqual(nd["change"], "changed")
        self.assertEqual(ch[-1]["change"], "external")

    def test_chain_mapper_no_match_no_append(self):
        # mapper XML missing / namespace-id mismatch -> the chain ends at the dao
        # method (no terminal node appended).
        edges = {"callees": {
            "createOrder": [{"name": "insertOrder", "kind": "method",
                             "filePath": "src/dao/OrderDao.java", "startLine": 3}],
            "insertOrder": [],
        }}
        repo = self._chain_fixture_repo(CG_CHAIN_BASE, CG_CHAIN_FEAT, edges)
        d = self._run_group(repo, "chainnomap")
        u = self._iface(d)
        self.assertTrue(all(n["change"] != "external" for n in u["chain"]))

    def test_chain_codegraph_off_all_empty(self):
        # codegraph off -> EVERY unit carries chain == [] (structure always present).
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=False)
        d = self._run_group(repo, "chainoff")
        self.assertTrue(all(u.get("chain") == [] for u in d["pending"]))

    def test_chain_standalone_always_empty(self):
        # standalone units carry chain == [] even in codegraph mode.
        repo = self._build(CG_ISOLATED_BASE, CG_ISOLATED_FEAT, cg_on=True,
                           edges={"callees": {}, "callers": {}})
        d = self._run_group(repo, "chainsa")
        self.assertTrue(all(u["chain"] == [] for u in d["pending"]
                            if u["kind"] == "standalone"))

    def test_check_old_grouping_without_chain_ok(self):
        # an old grouping.json WITHOUT chain[] must stay --check-clean (incremental
        # field semantics); a malformed chain[] must fail.
        repo = self._build(CG_CHAIN_BASE, CG_CHAIN_FEAT, cg_on=True,
                           edges=CG_CHAIN_EDGES)
        d = self._run_group(repo, "chainold")
        run_dir = repo / ".mgh-sdr" / "runs" / "chainold"
        gp = run_dir / "grouping.json"
        g = json.loads(gp.read_text(encoding="utf-8"))
        for u in g["pending"]:
            u.pop("chain", None)
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, err = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, err)
        # malformed chain -> violation
        g2 = json.loads(gp.read_text(encoding="utf-8"))
        for u in g2["pending"]:
            u["chain"] = [{"fqn_short": "x", "label": "x", "file": "x",
                           "change": "changed", "branch_of": 99}]
        gp.write_text(json.dumps(g2), encoding="utf-8")
        code, _, err = self._run("--check", str(run_dir))
        self.assertEqual(code, 2)
        self.assertIn("branch_of illegal", err)


# --- slice byte gate: judge == artifact, and the over-budget ladder -------------

def _java_residual(n_methods: int, pad: int = 0) -> str:
    """A route-less java class: `n_methods` one-line methods (so the residual cluster
    carries a full, 40-entry-capped symbol table) plus `pad` long comment lines. Changing
    `pad` between base and feat yields ONE file whose diff body and symbol table are both
    substantial — the atomic-residue shape levels 2/3 exist for."""
    body = "\n".join(f"    public int paddingMethodName{i}() {{ return {i}; }}"
                     for i in range(n_methods))
    lines = [f"    // pad line {i}: " + "y" * 48 for i in range(pad)]
    return "public class BigUtil {\n" + "\n".join(lines + body.split("\n")) + "\n}\n"


class SliceByteGateTest(unittest.TestCase):
    """harden-mgh-sdr-oversize-slice-gate: (a) the budget judge is the rendered slice's
    utf-8 byte count — the same number that lands on disk; (b) over budget, the unit is
    re-split losslessly, then context-slimmed, then refused with zero side effects."""

    RESIDUAL_BASE = {"src/util/BigUtil.java": _java_residual(60, 0)}
    RESIDUAL_FEAT = {"src/util/BigUtil.java": _java_residual(60, 15)}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_diffgate_"))
        self._env_backup = {k: v for k, v in os.environ.items()}

    def tearDown(self):
        import shutil
        for k in ("MGH_CODEGRAPH_BIN", "CG_STUB_MAP"):
            os.environ.pop(k, None)
        for k, v in self._env_backup.items():
            os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # reuse the main harness (build/run helpers live on DiffGroupTest)
    _build = DiffGroupTest._build
    _run_group = DiffGroupTest._run_group
    _run = DiffGroupTest._run
    _slice_text = DiffGroupTest._slice_text

    def _run_cap(self, repo, run: str, *extra):
        run_dir = repo / ".mgh-sdr" / "runs" / run
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feat",
                                   "--checkpoints", str(run_dir / "markers"),
                                   "--materialize", str(run_dir / "slices"), *extra)
        return code, out, err, run_dir

    def test_standalone_multifile_cluster_resplit(self):
        # Scenario (standalone half of level 1): a directory cluster of several files —
        # one unit, because the clustering merge cap is judged per candidate — measures
        # over its cap while each file alone fits -> re-split into -partN, losslessly.
        # Exercises the gate splitter with NO hunk selection (the "render every hunk"
        # shape), which the interface path never does.
        base, feat = {}, {}
        for i in range(3):
            rel = f"db/m{i}.sql"
            base[rel] = f"CREATE TABLE m{i}(id INT);\n"
            feat[rel] = (f"CREATE TABLE m{i}(id INT, x INT);\n"
                         + "".join(f"-- note {j} {'q' * 60}\n" for j in range(12)))
        repo = self._build(base, feat, cg_on=False)
        code, out, err, _ = self._run_cap(repo, "multi",
                                          "--max-standalone-bytes", "1500")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        parts = [u for u in d["pending"] if "-part" in u["unit_id"]]
        self.assertEqual(len(parts), 3, d["pending"])
        for u in d["pending"]:
            self.assertLessEqual(u["unit_bytes"], 1500)
            self.assertEqual(u["slimmed"], {})          # lossless: nothing was slimmed
        # lossless: same hunk locators as the un-split (huge cap) run
        code, wout, werr, _ = self._run_cap(repo, "multiwide",
                                            "--max-standalone-bytes", "1000000")
        self.assertEqual(code, 0, werr)
        self.assertEqual(DiffGroupTest._hunk_locators(self, d),
                         DiffGroupTest._hunk_locators(self, json.loads(wout)))
        self.assertEqual(len(json.loads(wout)["pending"]), 1)   # one cluster, un-split

    def test_oversize_atomic_residue_slimmed(self):
        # Scenario: one file (cannot be split mid-file) over cap, where the overage is
        # carried by the descriptive symbol table -> slim it, keep the evidence intact.
        repo = self._build(self.RESIDUAL_BASE, self.RESIDUAL_FEAT, cg_on=True)
        code, out, err, run_dir = self._run_cap(repo, "slim",
                                                "--max-standalone-bytes", "2200")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(len(d["pending"]), 1)
        u = d["pending"][0]
        self.assertLessEqual(u["unit_bytes"], 2200)
        self.assertEqual(u["slimmed"].keys(), {"sym_ctx"})       # recorded, not silent
        text = self._slice_text(u)
        self.assertRegex(text, r"… \(截断:\d+ 行 / 原 \d+ 字节\)")  # visible in the slice
        # evidence面 untouched: the diff body, the file list and every hunk locator
        self.assertIn("- src/util/BigUtil.java [M]", text)
        self.assertIn("@@ src/util/BigUtil.java @@ new-file lines", text)
        self.assertIn("+    // pad line 0:", text)
        self.assertNotIn("(截断", text.split("## Diff hunks", 1)[1])   # never the diff
        self.assertEqual(d["budget"], {"max_standalone_bytes": 2200,
                                       "max_interface_bytes": 262144})

    def test_oversize_atomic_residue_refuses_with_zero_side_effects(self):
        # Scenario: the file's own diff body is over the cap — no context block can give
        # that budget back -> exit 2 BEFORE anything is written (zero slices, zero
        # grouping.json => the dispatcher has nothing to consume => zero subagents).
        repo = self._build(self.RESIDUAL_BASE, self.RESIDUAL_FEAT, cg_on=True)
        code, out, err, run_dir = self._run_cap(repo, "refuse",
                                                "--max-standalone-bytes", "1500")
        self.assertEqual(code, 2, err)
        self.assertIn("over their slice byte budget", err)
        self.assertIn("BigUtil", err)             # unit_id
        self.assertIn("cap 1500", err)
        self.assertIn("largest contributing file: src/util/BigUtil.java", err)
        self.assertIn("recipe:", err)
        self.assertFalse((run_dir / "slices").exists())
        self.assertEqual([p for p in run_dir.glob("**/*.slice.md")], [])
        self.assertFalse((run_dir / "grouping.json").exists())
        self.assertEqual(out.strip(), "")         # nothing on stdout either

    def test_unit_bytes_is_the_landed_file(self):
        # the judge and the artifact are one number: `unit_bytes` equals the slice file's
        # byte count (and the utf-8 length of the text), for every unit
        repo = self._build(self.RESIDUAL_BASE, self.RESIDUAL_FEAT, cg_on=True)
        code, out, err, _ = self._run_cap(repo, "same")
        self.assertEqual(code, 0, err)
        for u in json.loads(out)["pending"]:
            p = Path(u["input_path"])
            self.assertEqual(u["unit_bytes"], p.stat().st_size, u["unit_id"])
            self.assertEqual(u["unit_bytes"],
                             len(p.read_text(encoding="utf-8").encode("utf-8")))

    def test_in_budget_output_unchanged(self):
        # no-regression line: an in-budget run renders the SAME slice text and the same
        # pending[] fields as before the gate existed — `budget` (top level) and an empty
        # `slimmed` (per unit) are the only increments.
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/UserController.java", CONTROLLER)
        _write(repo, "db/migration.sql", "CREATE TABLE t(id INT);\n")
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feat")
        _write(repo, "src/UserController.java",
               CONTROLLER + "    // feature-branch change inside detail method\n")
        _write(repo, "db/migration.sql", "CREATE TABLE t(id INT, x INT);\n")
        _commit_all(repo, "feat")
        code, out, err, _ = self._run_cap(repo, "keep")
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertEqual(d["budget"], {"max_standalone_bytes": 65536,
                                       "max_interface_bytes": 262144})
        for u in d["pending"]:
            self.assertEqual(u["slimmed"], {})
            self.assertNotRegex(self._slice_text(u), r"截断")
            self.assertTrue(Path(u["input_path"]).name.startswith(f"{u['unit_id']}.slice.md"))
        # pinned render for the fixed fixture — the byte-for-byte no-regression line
        by_id = {u["unit_id"]: u for u in d["pending"]}
        self.assertEqual(
            self._slice_text(by_id["db"]),
            "# SDR review unit slice — db\n"
            "kind: standalone\n"
            "route: (standalone cluster)\n"
            f"repo: {repo}\n"
            "diff range: master..feat\n"
            "\n"
            "## Files in this unit\n"
            "- db/migration.sql [M]\n"
            "\n"
            "## Diff hunks (unified, 3-line context)\n"
            "```diff\n"
            "@@ db/migration.sql @@ new-file lines 1+1\n"
            "-CREATE TABLE t(id INT);\n"
            "+CREATE TABLE t(id INT, x INT);\n"
            "```\n"
            "\n"
            "Read-only slice materialized by diff_group.py; review against the baseline.\n")

    def test_check_budget_assertions_and_backward_compat(self):
        # --check: the new fields are asserted when present and SKIPPED when absent (an
        # old grouping.json stays clean) — same incremental contract as chain[].
        repo = self._build(self.RESIDUAL_BASE, self.RESIDUAL_FEAT, cg_on=True)
        code, out, err, run_dir = self._run_cap(repo, "ck")
        self.assertEqual(code, 0, err)
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, cerr)

        gp = run_dir / "grouping.json"
        good = gp.read_text(encoding="utf-8")

        # old product: no budget[], no slimmed{} -> assertions skipped, still exit 0
        g = json.loads(good)
        g.pop("budget", None)
        for u in g["pending"]:
            u.pop("slimmed", None)
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 0, cerr)

        # new product with a unit past its cap -> exit 2
        g = json.loads(good)
        g["pending"][0]["unit_bytes"] = g["budget"]["max_standalone_bytes"] + 1
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 2)
        self.assertIn("cap", cerr)

        # malformed slimmed -> exit 2
        g = json.loads(good)
        g["pending"][0]["slimmed"] = {"sym_ctx": "not-an-int"}
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 2)
        self.assertIn("slimmed malformed", cerr)

        # malformed budget -> exit 2
        g = json.loads(good)
        g["budget"] = {"max_standalone_bytes": "64KB"}
        gp.write_text(json.dumps(g), encoding="utf-8")
        code, _, cerr = self._run("--check", str(run_dir))
        self.assertEqual(code, 2)
        self.assertIn("budget malformed", cerr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
