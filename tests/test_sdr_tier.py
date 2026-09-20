#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""sdr_tier.py unit tests (add-mgh-sdr-resume-surface task 1.3).

The shared marker predicate must reproduce BYTE-FOR-BYTE the marker/draft paths
`diff_group.py` actually emits into `pending[]` — that identity is the whole point
of the module (writer and resume reader share one rule). So the core test builds a
throwaway git repo, runs diff_group, and compares every emitted path against
`forward_marker_paths`. Also covers the special-character unit_id case, the
forward done/failed set computation, orphan-marker non-counting, and the
empty/missing-dir shape.

Run: py tests/test_sdr_tier.py
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"
SCRIPT = SCRIPTS / "diff_group.py"
sys.path.insert(0, str(SCRIPTS))

from sdr_tier import (  # noqa: E402
    codegraph_available, codegraph_bin, codegraph_probe_reason,
    forward_done_ids, forward_failed_ids, forward_marker_paths, orphan_markers,
)


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


# Route carries `:{brch_no}` — the NTFS-ADS separator in a path variable. diff_group
# sanitizes it at unit construction (route `/user/detail:{brch_no}` becomes the
# filesystem-safe unit_id `UserController___user_detail_{brch_no}`), so the shared
# predicate must reproduce the SANITIZED id verbatim; it does no sanitizing itself.
CONTROLLER_BASE = """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/list")
    public java.util.List list() { return null; }
}
"""

CONTROLLER_FEAT = """@RestController
@RequestMapping("/user")
public class UserController {
    @GetMapping("/list")
    public java.util.List list() { return null; }

    @PostMapping("/detail:{brch_no}")
    public Object detail(String brch_no) {
        return null;
    }
}
"""


class SdrTierTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *args):
        p = subprocess.run([sys.executable, str(SCRIPT), *args],
                           capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout, p.stderr

    def _repo_with_feature(self) -> Path:
        repo = self.tmp / "repo"
        _init_repo(repo)
        _write(repo, "src/UserController.java", CONTROLLER_BASE)
        _commit_all(repo, "init")
        _git(repo, "checkout", "-qb", "feature-pay")
        _write(repo, "src/UserController.java", CONTROLLER_FEAT)
        _commit_all(repo, "feat")
        return repo

    # --- pure shape -------------------------------------------------------

    def test_paths_are_absolute_and_follow_the_run_dir_layout(self):
        run = self.tmp / "run"
        cp = run / "markers"
        draft, done, failed = forward_marker_paths(cp, "unit-alpha")
        self.assertEqual(draft, str((run / "drafts" / "unit-alpha.json").resolve()))
        self.assertEqual(done, str((cp / "unit-alpha.done").resolve()))
        self.assertEqual(failed, str((cp / "unit-alpha.failed").resolve()))
        for p in (draft, done, failed):
            self.assertTrue(Path(p).is_absolute(), p)

    def test_special_char_ids_are_concatenated_verbatim(self):
        # The module does NO sanitizing/truncating (unlike init_tier's
        # safe_unit_filename): the writer sanitizes before the id exists, and a
        # second pass here would be a second rule to keep in sync. Pin that.
        cp = self.tmp / "markers"
        for uid in ("unit:name", "x" * 400):
            draft, done, failed = forward_marker_paths(cp, uid)
            self.assertEqual(Path(done).name, f"{uid}.done")
            self.assertEqual(Path(failed).name, f"{uid}.failed")
            self.assertEqual(Path(draft).name, f"{uid}.json")
        # a 400-char id is NOT truncated here (contrast: init_tier caps stems at 200);
        # adopting init's encoding would rename every existing sdr marker on disk.
        self.assertEqual(len(Path(forward_marker_paths(cp, "x" * 400)[1]).name), 405)

    def test_missing_checkpoints_dir_yields_empty_sets(self):
        absent = self.tmp / "nope"
        self.assertEqual(forward_done_ids(absent, ["a", "b"]), set())
        self.assertEqual(forward_failed_ids(absent, ["a", "b"]), set())
        self.assertEqual(orphan_markers(absent, ["a"]), [])

    # --- writer/reader identity (the module's reason to exist) ------------

    def test_marker_paths_match_diff_group_pending_byte_for_byte(self):
        repo = self._repo_with_feature()
        run = self.tmp / "run"
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feature-pay",
                                   "--checkpoints", str(run / "markers"),
                                   "--materialize", str(run / "slices"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        self.assertGreater(len(d["pending"]), 0, "fixture produced no units")
        # the ADS hazard really is present in the fixture route ...
        self.assertTrue(any(":" in u["route"] for u in d["pending"]),
                        "fixture no longer exercises a `:`-bearing route")
        for u in d["pending"]:
            # ... and by the time it reaches a filename it is already sanitized, so
            # the shared predicate must reproduce that sanitized id byte-for-byte.
            self.assertNotIn(":", u["unit_id"])
            self.assertEqual(
                forward_marker_paths(run / "markers", u["unit_id"]),
                (u["draft_path"], u["done_marker"], u["failed_marker"]),
                f"path drift for unit {u['unit_id']!r}")

    def test_forward_sets_agree_with_the_marker_files_diff_group_reported(self):
        repo = self._repo_with_feature()
        run = self.tmp / "run"
        code, out, err = self._run("--repo", str(repo), "--base", "master",
                                   "--branch", "feature-pay",
                                   "--checkpoints", str(run / "markers"),
                                   "--materialize", str(run / "slices"))
        self.assertEqual(code, 0, err)
        d = json.loads(out)
        cp = run / "markers"
        ids = [u["unit_id"] for u in d["pending"]]

        self.assertEqual(forward_done_ids(cp, ids), set())
        self.assertEqual(forward_failed_ids(cp, ids), set())

        Path(d["pending"][0]["done_marker"]).write_text("{}", encoding="utf-8")
        Path(d["pending"][1]["failed_marker"]).write_text("{}", encoding="utf-8")
        self.assertEqual(forward_done_ids(cp, ids), {ids[0]})
        self.assertEqual(forward_failed_ids(cp, ids), {ids[1]})

    def test_orphan_markers_never_count_as_terminal(self):
        cp = self.tmp / "markers"
        cp.mkdir(parents=True)
        (cp / "legacy-unit.done").write_text("{}", encoding="utf-8")
        self.assertEqual(forward_done_ids(cp, ["another-unit"]), set())
        self.assertEqual(orphan_markers(cp, ["another-unit"]), ["legacy-unit.done"])

    def test_non_marker_files_are_not_orphans(self):
        cp = self.tmp / "markers"
        cp.mkdir(parents=True)
        (cp / "note.txt").write_text("x", encoding="utf-8")
        (cp / "unit-a.json").write_text("{}", encoding="utf-8")
        self.assertEqual(orphan_markers(cp, ["unit-a"]), [])


class _env:
    """Context manager: set (or remove) an env var for the block."""

    def __init__(self, key, value):
        self.key, self.value, self.old = key, value, None
        self.had = False

    def __enter__(self):
        self.had = self.key in os.environ
        self.old = os.environ.get(self.key)
        if self.value is None:
            os.environ.pop(self.key, None)
        else:
            os.environ[self.key] = self.value
        return self

    def __exit__(self, *exc):
        if self.had:
            os.environ[self.key] = self.old
        else:
            os.environ.pop(self.key, None)
        return False


class CodegraphProbeTest(unittest.TestCase):
    """The shared availability predicate. One rule, two consumers that MUST agree:
    `diff_group.py` decides whether to merge units along the call chain with it, and
    `sdr_context.py` writes the signal every unit's task message is filled from. If
    they disagreed, a slice would be reported as carrying a chain that was never
    materialized — a false instruction to the reviewer, not a cosmetic mismatch."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_cgprobe_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fake_bin(self) -> Path:
        p = self.tmp / "codegraph.cmd"
        p.write_text("@echo off\n", encoding="utf-8")
        return p

    def _missing_bin(self) -> str:
        # The host may genuinely have `codegraph` on PATH (this repo's own tooling),
        # so "no binary" is forced through the env override rather than by emptying PATH.
        return str(self.tmp / "no-such-dir" / "codegraph.exe")

    def test_needs_both_an_index_and_a_binary(self):
        with _env("MGH_CODEGRAPH_BIN", str(self._fake_bin())):
            self.assertFalse(codegraph_available(self.repo), "unindexed -> off")
            (self.repo / ".codegraph").mkdir()
            self.assertTrue(codegraph_available(self.repo), "indexed + binary -> on")
        with _env("MGH_CODEGRAPH_BIN", self._missing_bin()):
            self.assertFalse(codegraph_available(self.repo),
                             "indexed but no binary -> off")

    def test_bin_env_override_must_be_an_existing_file(self):
        with _env("MGH_CODEGRAPH_BIN", self._missing_bin()):
            self.assertIsNone(codegraph_bin(), "a stale override resolves to nothing")

    def test_probe_reason_names_the_missing_half(self):
        with _env("MGH_CODEGRAPH_BIN", str(self._fake_bin())):
            self.assertEqual(codegraph_probe_reason(self.repo), "no .codegraph dir")
            (self.repo / ".codegraph").mkdir()
            self.assertIsNone(codegraph_probe_reason(self.repo))
        with _env("MGH_CODEGRAPH_BIN", self._missing_bin()):
            self.assertEqual(codegraph_probe_reason(self.repo), "no binary")

    def test_diff_group_and_sdr_context_agree_on_the_same_repo(self):
        """The structural claim, not a coincidence: both sides import THIS predicate.
        Asserted at the source level so a future re-inlined copy fails loudly."""
        for name in ("diff_group.py", "sdr_context.py"):
            src = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertIn("codegraph_available", src,
                          f"{name} must use the shared predicate")
            self.assertNotIn('shutil.which("codegraph")', src,
                             f"{name} re-inlines the probe instead of sharing it")


if __name__ == "__main__":
    unittest.main(verbosity=2)
