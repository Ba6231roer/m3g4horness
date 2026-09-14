#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile-purity regression: every core/scripts leaf compiles with ZERO warnings.

Leaf scripts are loaded via import chains (e.g. resume_state.py -> list_clusters), so a
single SyntaxWarning (an invalid escape sequence in a docstring) pollutes stderr on every
call — stderr must carry only expected diagnostics. `py_compile.compile` under
`warnings.simplefilter("always")` catches any Warning category at compile time;
ANY warning => fail-loud listing the script name + message.
"""
import py_compile
import unittest
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "core" / "scripts"


class TestNoCompileWarnings(unittest.TestCase):
    def test_all_core_scripts_compile_warning_free(self):
        offenders = []
        for script in sorted(SCRIPTS.glob("*.py")):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    py_compile.compile(str(script), doraise=True)
                except py_compile.PyCompileError as exc:
                    offenders.append(f"{script.name}: COMPILE ERROR: {exc}")
                    continue
            msgs = [f"{w.category.__name__}: {w.message}" for w in caught
                    if issubclass(w.category, Warning)]
            if msgs:
                offenders.append(f"{script.name}: " + " | ".join(msgs))
        self.assertEqual(
            offenders, [],
            "scripts compiling with warnings (stderr pollution on every import):\n"
            + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main(verbosity=2)
