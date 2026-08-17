#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""install_hook.py idempotent settings.json merge (R5.7 deliverable, §9.6).

Asserts: add creates exactly one matcher; double-add does not duplicate; the user's
existing hooks are preserved; --remove takes ours back out.
"""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / "tools"


def _load():
    spec = importlib.util.spec_from_file_location("install_hook", TOOLS / "install_hook.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInstallHook(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.d = Path(tempfile.mkdtemp(prefix="mgh_ih_"))

    def _run(self, settings, remove=False):
        argv = ["install_hook.py", "--settings", str(settings),
                "--hook-command", "py .claude/hooks/block_adhoc_scripts.py"]
        if remove:
            argv.append("--remove")
        old, sys.argv = sys.argv, argv
        try:
            return self.m.main()
        finally:
            sys.argv = old

    def _count(self, settings):
        if not settings.is_file():
            return None
        return len(json.loads(settings.read_text(encoding="utf-8"))
                   .get("hooks", {}).get("PreToolUse", []))

    def test_add_creates_settings_with_one_matcher(self):
        s = self.d / "settings.json"
        self.assertEqual(self._run(s), 0)
        self.assertEqual(self._count(s), 1)

    def test_double_add_is_idempotent(self):
        s = self.d / "settings.json"
        self._run(s)
        self._run(s)
        self.assertEqual(self._count(s), 1)  # NOT 2

    def test_preserves_user_existing_hook(self):
        s = self.d / "settings.json"
        s.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Write", "hooks": [{"type": "command", "command": "my-hook"}]}]}}),
            encoding="utf-8")
        self._run(s)
        self.assertEqual(self._count(s), 2)  # user's + ours
        data = json.loads(s.read_text(encoding="utf-8"))
        cmds = [h["command"] for e in data["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertIn("my-hook", cmds)
        self.assertTrue(any("block_adhoc_scripts" in c for c in cmds))

    def test_remove_takes_ours_out(self):
        s = self.d / "settings.json"
        self._run(s)
        self.assertEqual(self._run(s, remove=True), 0)
        data = json.loads(s.read_text(encoding="utf-8"))
        self.assertNotIn("hooks", data)  # empty hooks{} removed

    # ---- matcher default surface + idempotent legacy evolution (wiring layer) ----

    def _matcher_of_ours(self, settings):
        data = json.loads(settings.read_text(encoding="utf-8"))
        for e in data["hooks"]["PreToolUse"]:
            for h in e.get("hooks", []):
                if "block_adhoc_scripts" in (h.get("command") or ""):
                    return e.get("matcher")
        return None

    def test_fresh_install_gets_full_tool_surface(self):
        # the default matcher carries the guard's FULL dispatch surface (read-side +
        # tool-face branches are consulted only when the matcher carries them).
        s = self.d / "settings.json"
        self.assertEqual(self._run(s), 0)
        m = self._matcher_of_ours(s)
        self.assertEqual(set(m.split("|")),
                         {"Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "ApplyPatch",
                          "Read", "Glob", "Grep"})

    def _legacy_settings(self, command="py .claude/hooks/block_adhoc_scripts.py", s=None):
        """settings.json carrying OUR entry with the legacy `Bash|Write|Edit` matcher."""
        s = s or (self.d / "settings.json")
        s.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "Bash|Write|Edit",
             "hooks": [{"type": "command", "command": command}]}]}}), encoding="utf-8")
        return s

    def test_legacy_matcher_evolved_in_place(self):
        # an earlier shipped default (Bash|Write|Edit) evolves to the full default on
        # reinstall — only the matcher field; the command stays byte-identical.
        s = self._legacy_settings()
        self.assertEqual(self._run(s), 0)
        self.assertEqual(self._run(s), 0)
        data = json.loads(s.read_text(encoding="utf-8"))
        entry = data["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"],
                         "Bash|Write|Edit|MultiEdit|NotebookEdit|ApplyPatch|Read|Glob|Grep")
        self.assertEqual(entry["hooks"][0]["command"],
                         "py .claude/hooks/block_adhoc_scripts.py")
        self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)  # in place, no duplicate

    def test_user_custom_non_subset_matcher_untouched(self):
        # a user-customized matcher that is NOT a legacy subset keeps its extra tools —
        # the evolution never second-guesses a deliberate customization.
        s = self.d / "settings.json"
        custom = "Bash|Write|Edit|WebFetch"
        s.write_text(json.dumps({"hooks": {"PreToolUse": [
            {"matcher": custom,
             "hooks": [{"type": "command",
                        "command": "py .claude/hooks/block_adhoc_scripts.py"}]}]}}),
            encoding="utf-8")
        self.assertEqual(self._run(s), 0)
        self.assertEqual(self._matcher_of_ours(s), custom)

    def test_evolution_idempotent_on_second_rerun(self):
        # after evolving, a third run is a no-op (matcher already == default -> subset
        # check fails -> untouched).
        s = self._legacy_settings()
        self._run(s)
        self._run(s)
        data = json.loads(s.read_text(encoding="utf-8"))
        self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)
        self.assertEqual(self._matcher_of_ours(s),
                         "Bash|Write|Edit|MultiEdit|NotebookEdit|ApplyPatch|Read|Glob|Grep")

    def test_user_custom_command_field_preserved(self):
        # the entry is anchored by OUR marker inside command; a user who edited the
        # matcher but kept our command keeps their whole entry except the legacy subset.
        user_cmd = "py .claude/hooks/block_adhoc_scripts.py --extra-flag"
        s = self._legacy_settings(command=user_cmd)
        self.assertEqual(self._run(s), 0)
        data = json.loads(s.read_text(encoding="utf-8"))
        entry = data["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["hooks"][0]["command"], user_cmd)  # command preserved
        self.assertEqual(entry["matcher"],
                         "Bash|Write|Edit|MultiEdit|NotebookEdit|ApplyPatch|Read|Glob|Grep")

    def test_explicit_matcher_skips_evolution(self):
        # an explicit --matcher pins the intent; a legacy-subset entry is left as-is.
        s = self._legacy_settings()
        argv = ["install_hook.py", "--settings", str(s),
                "--hook-command", "py .claude/hooks/block_adhoc_scripts.py",
                "--matcher", "Bash|Write|Edit"]
        old, sys.argv = sys.argv, argv
        try:
            self.assertEqual(self.m.main(), 0)
        finally:
            sys.argv = old
        self.assertEqual(self._matcher_of_ours(s), "Bash|Write|Edit")


if __name__ == "__main__":
    unittest.main()
