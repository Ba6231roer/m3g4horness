#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""dsh command-surface shape lint (add-mgh-dsh-command-surface task 3.3).

Asserts for the five shipped dsh skill shells (releases/dsh/skills/mgh-*/SKILL.md)
+ the dsh-face lazy flow fragments:
  1. frontmatter: exactly the kebab-case keys name/description/user-invocable/
     disable-model-invocation present, name == directory name, booleans 'true',
     description within the 1536-char cap;
  2. asset-reference rooting: no `.opencode/mgh-core` / `.claude/mgh-core` /
     absolute-drive / `~/` install-root references — every `mgh-core/` asset path
     is rooted at the target project root (dsh install layout);
  3. every `REQUIRED SUB-SKILL` pointer path in a dsh shell resolves to a real
     file in this repo's core/prompts/ (mirror of <target>/mgh-core/prompts/).

Run: py tests/test_dsh_command_surface.py
"""
import re, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DSH_SKILLS = ROOT / "releases" / "dsh" / "skills"
COMMANDS = ["mgh-sdr", "mgh-sast", "mgh-init", "mgh-sra", "mgh-srr"]

FM_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)


def frontmatter(text: str) -> dict:
    m = FM_RE.match(text)
    if not m:
        raise AssertionError("missing leading --- frontmatter block")
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    return fm


class TestFrontmatter(unittest.TestCase):
    def test_five_shells_exist(self):
        for cmd in COMMANDS:
            self.assertTrue((DSH_SKILLS / cmd / "SKILL.md").is_file(),
                            f"missing dsh shell: {cmd}/SKILL.md")

    def test_frontmatter_shape(self):
        for cmd in COMMANDS:
            with self.subTest(cmd=cmd):
                fm = frontmatter((DSH_SKILLS / cmd / "SKILL.md").read_text(encoding="utf-8"))
                for key in ("name", "description", "user-invocable", "disable-model-invocation"):
                    self.assertIn(key, fm, f"{cmd}: frontmatter lacks '{key}'")
                self.assertEqual(fm["name"], cmd)
                self.assertEqual(fm["user-invocable"], "true")
                self.assertEqual(fm["disable-model-invocation"], "true")
                self.assertLessEqual(len(fm["description"]), 1536,
                                     f"{cmd}: description exceeds 1536 chars")
                # legacy camelCase spellings must not appear (dsh parser rejects them)
                raw = (DSH_SKILLS / cmd / "SKILL.md").read_text(encoding="utf-8")[:2500]
                for bad in ("userInvocable", "disableModelInvocation"):
                    self.assertNotIn(bad, raw, f"{cmd}: camelCase key '{bad}' is rejected by dsh")


class TestAssetReferenceRooting(unittest.TestCase):
    def _texts(self):
        for cmd in COMMANDS:
            yield DSH_SKILLS / cmd / "SKILL.md"
        for frag in sorted((ROOT / "core" / "prompts" / "fragments").glob("*-flow-dsh.md")):
            yield frag

    def test_no_host_prefixed_mgh_core(self):
        for path in self._texts():
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                for bad in (".opencode/mgh-core", ".claude/mgh-core", "~/.dsh"):
                    self.assertNotIn(bad, text, f"{path}: references '{bad}'")

    def test_no_absolute_install_root_refs(self):
        # asset paths must be target-root relative (mgh-core/...), never hard-coded
        # absolute install locations.
        abs_re = re.compile(r"(?<![\w<>-])[A-Za-z]:[\\/]{1,2}mgh-core|[\"']mgh-core")
        for path in self._texts():
            with self.subTest(file=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIsNone(abs_re.search(text),
                                  f"{path}: absolute/pseudo-quoted install root reference")


class TestLazyFragmentPointers(unittest.TestCase):
    PTR_RE = re.compile(r"mgh-core/(prompts/[\w/.\-]+\.md)")

    def test_pointer_targets_exist(self):
        for cmd in COMMANDS:
            text = (DSH_SKILLS / cmd / "SKILL.md").read_text(encoding="utf-8")
            for rel in set(self.PTR_RE.findall(text)):
                with self.subTest(cmd=cmd, frag=rel):
                    self.assertTrue((ROOT / "core" / rel).is_file(),
                                    f"{cmd}: REQUIRED SUB-SKILL pointer to missing {rel}")

    def test_sra_srr_flow_pointers_present(self):
        for cmd in ("mgh-sra", "mgh-srr"):
            text = (DSH_SKILLS / cmd / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("REQUIRED SUB-SKILL", text, f"{cmd}: pointer marker missing")
            self.assertRegex(text, rf"{cmd.replace('mgh-', '')}-flow-dsh\.md",
                             f"{cmd}: dsh-face flow fragment pointer missing")


class TestInitDispatchDisclosure(unittest.TestCase):
    """fix-mgh-init-distribution-links 1.7 / dsh-command-surface delta: the mgh-init
    SKILL.md dispatch disclosure must state the REAL wiring (dsh-command-surface
    requirement "dsh dispatch disclosure states the real wiring and stop surface").
    Four closed-set facts, all text-asserted:
      ① wired tier list == fanout_runner TIERS closed set (incl. scout-merge);
      ② stop list enumerates EVERY non-dispatched stage (missing one invites
         improvised inline execution — the exact shape the disclosure forbids);
      ③ --skip-consistency is declared run-start-only (mid-run uninjectable);
      ④ stop-at-t3-with-T4-pending is disclosed as having NO terminal manifest.
    """

    DISCLOSURE_START = "dsh 派发面"

    def _disclosure(self) -> str:
        text = (DSH_SKILLS / "mgh-init" / "SKILL.md").read_text(encoding="utf-8")
        start = text.find(self.DISCLOSURE_START)
        self.assertGreaterEqual(start, 0, "dispatch disclosure section missing")
        return text[start:start + 3000]

    def test_wired_tier_list_matches_dispatcher_closed_set(self):
        # scout-merge is wired (fanout_runner TIERS + the script inventory row say so);
        # the disclosure listing scout/t1/t2/t3 only contradicts the same document.
        self.assertIn("scout/scout-merge/t1/t2/t3", self._disclosure(),
                      "wired tier list must be the TIERS closed set "
                      "scout/scout-merge/t1/t2/t3")

    def test_stop_list_enumerates_every_undispatched_stage(self):
        d = self._disclosure()
        for stage in ("init-survey", "init-resolve",
                      "init-synthesis", "init-synthesis-rollup",
                      "init-scout-merge", "init-scout-merge-rollup",
                      "init-rules-consistency"):
            self.assertIn(f"`{stage}`", d,
                          f"stop list missing `{stage}` — an unlisted non-dispatched "
                          f"stage invites improvised inline execution")

    def test_skip_consistency_declared_run_start_only(self):
        d = self._disclosure()
        self.assertIn("--skip-consistency", d)
        self.assertIn("mid-run 不可注入", d,
                      "disclosure must state the flag is run-start-only — an "
                      "orchestrator reading it mid-run cannot inject it")

    def test_stop_before_t4_discloses_no_terminal_manifest(self):
        d = self._disclosure()
        self.assertIn("init_manifest.json", d,
                      "disclosure must name the terminal manifest")
        self.assertIn("--resume", d,
                      "disclosure must give the --resume path to finish a run that "
                      "stopped after t3")


if __name__ == "__main__":
    unittest.main(verbosity=1)
