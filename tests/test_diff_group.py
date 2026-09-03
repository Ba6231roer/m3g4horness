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

    def test_zero_diff_empty(self):
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
        # Scenario: reflection/DI residue (no call edges) -> each changed method its
        # own standalone unit; flow exits 0 with a non-empty pending.
        repo = self._build(CG_ISOLATED_BASE, CG_ISOLATED_FEAT, cg_on=True,
                           edges={"callees": {}, "callers": {}})
        d = self._run_group(repo)
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"]["interface"], 0)
        self.assertEqual(d["counts"]["standalone"], 2)
        self.assertTrue(all(u["kind"] == "standalone" and u["route"] == ""
                            for u in d["pending"]))

    def test_cg_shared_downstream_split_per_interface(self):
        # Scenario: /user/detail + /user/list both call changed UserService.queryUser
        # -> TWO interface units, queryUser hunk repeated in each slice (dedup left to
        # the renderer), never one merged component.
        repo = self._build(CG_SHARED_BASE, CG_SHARED_FEAT, cg_on=True,
                           edges=CG_SHARED_EDGES)
        d = self._run_group(repo)
        self.assertIs(d["codegraph"], True)
        self.assertEqual(d["counts"], {"interface": 2, "standalone": 0})
        ifaces = [u for u in d["pending"] if u["kind"] == "interface"]
        self.assertEqual(sorted(u["route"] for u in ifaces),
                         ["/user/detail", "/user/list"])
        for u in ifaces:
            self.assertEqual(self._slice_text(u).count("UserService.java @@ "), 1)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
