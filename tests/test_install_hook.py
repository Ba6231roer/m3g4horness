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


if __name__ == "__main__":
    unittest.main()
