#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""classify_tests — deterministic test-layer classification (subprocess runtime).

Covers: bucketing by ACTUAL annotation/import (never name alone), mix-substyle splitting,
uniformity hint, util hetero sub-split, and the --check boundary (fail-loud exit 2)."""

import json, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
CLASSIFY = SCRIPTS / "classify_tests.py"
PY = sys.executable

CONTROLLER_SLICE = """\
package com.acme.controller;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.junit.jupiter.api.Test;
@WebMvcTest
class FooControllerTest {
  @MockBean com.acme.service.FooService svc;
  @Test void t() {}
}
"""
CONTROLLER_FULL = """\
package com.acme.controller;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.junit.jupiter.api.Test;
@SpringBootTest
class BarControllerTest {
  TestRestTemplate rest;
  @Test void t() {}
}
"""
SERVICE_UNIT = """\
package com.acme.service;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.InjectMocks;
import org.mockito.Mock;
@ExtendWith(MockitoExtension.class)
class UserServiceTest {
  @InjectMocks UserService s;
  @Mock UserRepo r;
  @Test void t() {}
}
"""
UTIL_PURE = """\
package com.acme.util;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import static org.assertj.core.api.Assertions.assertThat;
class StringUtilTest {
  @ParameterizedTest @CsvSource({"a,1"})
  void len(String s, int n) { assertThat(s.length()).isEqualTo(n); }
  @Test void blank() { assertThat("").isEmpty(); }
}
"""
UTIL_TIME = """\
package com.acme.util;
import org.junit.jupiter.api.Test;
import java.time.Clock;
import static org.assertj.core.api.Assertions.assertThat;
class TimeUtilTest {
  @Test void now() { assertThat(TimeUtil.now(Clock.systemDefaultZone())).isNotNull(); }
}
"""


def _write(root: Path, rel: str, text: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _run(args, cwd):
    return subprocess.run([PY, str(CLASSIFY), *args], cwd=str(cwd),
                          capture_output=True, text=True, encoding="utf-8")


class TestClassifyTests(unittest.TestCase):
    def _fixture(self):
        repo = Path(tempfile.mkdtemp(prefix="mgh_ct_"))
        out = Path(tempfile.mkdtemp(prefix="mgh_ct_out_"))
        return repo, out

    def _groups(self, repo, out):
        data = json.loads((out / "test_groups.json").read_text(encoding="utf-8"))
        return {g["id"]: g for g in data["groups"]}

    def test_bucket_by_annotation_not_name_alone(self):
        # FooControllerTest(@WebMvcTest) and BarControllerTest(@SpringBootTest+TestRestTemplate)
        # are both named *ControllerTest but MUST land in different groups (detected annotation).
        repo, out = self._fixture()
        _write(repo, "src/test/java/com/acme/controller/FooControllerTest.java", CONTROLLER_SLICE)
        _write(repo, "src/test/java/com/acme/controller/BarControllerTest.java", CONTROLLER_FULL)
        r = _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 0, f"classify failed:\n{r.stderr}")
        groups = self._groups(repo, out)
        self.assertIn("controller::WebMvcTest", groups)
        # full-stack (SpringBootTest+TestRestTemplate) separated into its own group
        self.assertTrue(any(g["layer"] == "integration" for g in groups.values()),
                        f"expected a full-stack/integration group, got {sorted(groups)}")

    def test_uniform_group_by_single_annotation(self):
        repo, out = self._fixture()
        for i in range(5):
            _write(repo, f"src/test/java/com/acme/service/UserService{i}Test.java", SERVICE_UNIT)
        r = _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 0)
        groups = self._groups(repo, out)
        svc = [g for g in groups.values() if g["layer"] == "service"]
        self.assertEqual(len(svc), 1)                # all MockitoExtension -> one group
        self.assertEqual(svc[0]["uniformity"], "uniform")
        self.assertEqual(svc[0]["member_count"], 5)

    def test_util_hetero_subsplit(self):
        # util bucket sub-splits by signal (parameterized vs mock-time) even with 1 file each.
        repo, out = self._fixture()
        _write(repo, "src/test/java/com/acme/util/StringUtilTest.java", UTIL_PURE)
        _write(repo, "src/test/java/com/acme/util/TimeUtilTest.java", UTIL_TIME)
        r = _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 0)
        groups = self._groups(repo, out)
        util = [g for g in groups.values() if g["layer"] == "util"]
        self.assertGreaterEqual(len(util), 2)        # parameterized vs mock-time sub-split
        fams = sorted(g["family"] for g in util)
        self.assertIn("parameterized", fams)
        self.assertIn("mock-time", fams)

    def test_check_consistent_exit0(self):
        repo, out = self._fixture()
        _write(repo, "src/test/java/com/acme/service/UserServiceTest.java", SERVICE_UNIT)
        _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        r = _run(["--check", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["ok"])

    def test_check_inconsistent_member_missing_exit2(self):
        repo, out = self._fixture()
        member = _write(repo, "src/test/java/com/acme/service/UserServiceTest.java", SERVICE_UNIT)
        _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        member.unlink()  # group member no longer on disk -> --check must fail loud
        r = _run(["--check", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["ok"])

    def test_non_test_source_is_ignored(self):
        # production source (no test framework markers) must NOT be classified.
        repo, out = self._fixture()
        _write(repo, "src/main/java/com/acme/UserService.java",
               "package com.acme; public class UserService { public String x() { return \"x\"; } }")
        r = _run(["--repo", str(repo), "--out", str(out)], cwd=repo)
        self.assertEqual(r.returncode, 0)
        groups = self._groups(repo, out)
        self.assertEqual(groups, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
