#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Regression tests for mgh_credentials.py (credential center, R5.3).

Faces covered:
- validator (single source shared with fanout_runner): closed-set required
  keys, type checks, `v` pin;
- inherit mode: zero-login env read; missing var → exit 2 with recipe;
- env-file mode: KEY=VALUE parsing (export/quotes/comments); missing
  file / missing var → exit 2;
- login-process mode: probe plugin materialization + surgical global-config
  append; SUCCESS captures the probe-written token and RESTORES the config;
  FAILURE (probe never writes) also restores the config (re-read + remove
  only our entry) and exits 2 with a recipe. The real login child is faked by
  pointing the probe at a pre-written token file via a stub `opencode` exe on
  PATH that writes the token into the probe output path (exercising the REAL
  spawn/poll/finally machinery without a browser);
- cred payload write: restrictive permissions (POSIX 0600; Windows: best-
  effort — asserted as "file exists and parses");
- `--check`: schema-only validation, zero network, exit codes;
- stdout NEVER carries the token value (every mode's summary + failures).

Zero deps; every test self-contained under tempfile dirs (Windows-safe)."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "core" / "scripts" / "mgh_credentials.py"


def _load(name="mgh_credentials_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_main(mod, *argv, env_extra=None):
    """In-process main() with redirected streams; returns (code, out, err)."""
    old_argv = sys.argv
    saved_env = {k: os.environ.get(k) for k in (env_extra or {})}
    if env_extra:
        os.environ.update(env_extra)
    sys.argv = ["mgh_credentials.py", *argv]
    out, err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = mod.main()
    finally:
        sys.argv = old_argv
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return code, out.getvalue(), err.getvalue()


def _valid_cred(overrides: dict | None = None) -> dict:
    body = {"v": 1, "baseURL": "https://gw.example/api", "apikey": "T0KEN",
            "provider_id": "wizard", "global_config": "~/x/opencode.json",
            "keep_plugins": True, "expired_signatures": ["401"]}
    body.update(overrides or {})
    return body


def _source(tmp: Path, **overrides) -> Path:
    body = {"v": 1, "mode": "inherit", "token_env": "AIMAX_AUTH_TOKEN",
            "env_file": str(tmp / "wizard.env"),
            "global_config": str(tmp / "opencode.json"),
            "model": "wizard-local/glm-4",
            "provider_id": "wizard",
            "baseURL": "https://gw.example/api",
            "keep_plugins": True,
            "expired_signatures": ["401"]}
    body.update(overrides)
    p = tmp / "cred_source.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


class TestValidator(unittest.TestCase):
    """The closed-set validator — ONE source shared with the dispatcher."""

    def setUp(self):
        self.mod = _load("mgh_credentials_validator")

    def test_valid_body_has_no_problems(self):
        self.assertEqual(self.mod.validate_cred_payload(_valid_cred()), [])

    def test_each_required_key_missing_is_named(self):
        for k in self.mod.CRED_REQUIRED_KEYS:
            body = _valid_cred()
            del body[k]
            problems = self.mod.validate_cred_payload(body)
            self.assertTrue(any(k in p for p in problems), k)

    def test_type_checks(self):
        bad = _valid_cred({"v": 2, "apikey": "", "keep_plugins": 1,
                           "expired_signatures": "401"})
        problems = self.mod.validate_cred_payload(bad)
        self.assertTrue(any("v" in p for p in problems))
        self.assertTrue(any("apikey" in p for p in problems))
        self.assertTrue(any("keep_plugins" in p for p in problems))
        self.assertTrue(any("expired_signatures" in p for p in problems))

    def test_non_object_rejected(self):
        self.assertTrue(self.mod.validate_cred_payload([1, 2]))


class TestInheritMode(unittest.TestCase):
    def setUp(self):
        self.mod = _load("mgh_credentials_inherit")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_cred_inherit_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inherit_reads_env_zero_login(self):
        src = _source(self.tmp, mode="inherit")
        out = self.tmp / "cred.json"
        code, out_s, err = _run_main(self.mod, "--source", str(src),
                                     "--out", str(out),
                                     env_extra={"AIMAX_AUTH_TOKEN": "SESS-TOK"})
        self.assertEqual(code, 0, err)
        self.assertTrue(out.is_file())
        body = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(body["apikey"], "SESS-TOK")
        self.assertEqual(body["provider_id"], "wizard")
        self.assertEqual(body["expired_signatures"], ["401"])
        # stdout summary names mode/out but NEVER the token
        self.assertNotIn("SESS-TOK", out_s)
        self.assertIn('"mode": "inherit"', out_s)

    def test_inherit_missing_var_exit2_no_cred_file(self):
        src = _source(self.tmp, mode="inherit")
        out = self.tmp / "cred.json"
        code, out_s, err = _run_main(self.mod, "--source", str(src),
                                     "--out", str(out))
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())
        self.assertIn("AIMAX_AUTH_TOKEN", err)
        self.assertIn("recipe", err.lower())


class TestEnvFileMode(unittest.TestCase):
    def setUp(self):
        self.mod = _load("mgh_credentials_envfile")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_cred_envfile_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _envfile(self, text: str) -> Path:
        p = self.tmp / "wizard.env"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parses_export_quotes_comments(self):
        self._envfile('# comment\nOTHER=1\nexport AIMAX_AUTH_TOKEN="Q-TOK"\n')
        src = _source(self.tmp, mode="env-file")
        out = self.tmp / "cred.json"
        code, out_s, err = _run_main(self.mod, "--source", str(src),
                                     "--out", str(out))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["apikey"],
                         "Q-TOK")
        self.assertNotIn("Q-TOK", out_s)

    def test_missing_file_exit2(self):
        src = _source(self.tmp, mode="env-file")  # env_file not created
        code, _, err = _run_main(self.mod, "--source", str(src),
                                 "--out", str(self.tmp / "cred.json"))
        self.assertEqual(code, 2)
        self.assertIn("env file", err.lower())

    def test_missing_var_exit2(self):
        self._envfile("OTHER=1\n")
        src = _source(self.tmp, mode="env-file")
        code, _, err = _run_main(self.mod, "--source", str(src),
                                 "--out", str(self.tmp / "cred.json"))
        self.assertEqual(code, 2)
        self.assertIn("AIMAX_AUTH_TOKEN", err)


class TestLoginProcessMode(unittest.TestCase):
    """login-process with the REAL spawn/poll/finally machinery: a stub
    `opencode` exe on PATH plays the login child — it writes the token into
    the probe output path (the probe plugin's job in production is to copy
    process.env there; the stub reproduces the OBSERVABLE contract: token
    file appears, global config gets restored)."""

    def setUp(self):
        self.mod = _load("mgh_credentials_loginproc")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_cred_login_"))
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()
        self._write_stub()
        self.old_path = os.environ.get("PATH")
        os.environ["PATH"] = str(self.bin_dir) + os.pathsep + \
            (self.old_path or "")

    def tearDown(self):
        if self.old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self.old_path
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_stub(self):
        if os.name == "nt":
            exe = self.bin_dir / "opencode.bat"
            exe.write_text(
                "@echo off\r\n"
                "if not \"%MGH_CRED_STUB_TOKEN%\"==\"\" "
                "%MGH_CRED_STUB_PY% -c \"import pathlib,sys;"
                "p=pathlib.Path(sys.argv[1]);"
                "[p.write_text(sys.argv[2],encoding='utf-8') "
                "for _ in [0] if not p.exists()]\""
                " \"%MGH_CRED_STUB_OUT%\" \"%MGH_CRED_STUB_TOKEN%\"\r\n",
                encoding="utf-8")
        else:
            exe = self.bin_dir / "opencode"
            exe.write_text(
                "#!/bin/sh\n"
                "if [ -n \"$MGH_CRED_STUB_TOKEN\" ] && [ -n \"$MGH_CRED_STUB_OUT\" ]; then\n"
                "  [ -f \"$MGH_CRED_STUB_OUT\" ] || printf '%s' "
                "\"$MGH_CRED_STUB_TOKEN\" > \"$MGH_CRED_STUB_OUT\"\n"
                "fi\n", encoding="utf-8")
            os.chmod(str(exe), 0o755)

    def _global_config(self) -> Path:
        gp = self.tmp / "opencode.json"
        gp.write_text(json.dumps({"model": "wizard-local/glm-4",
                                  "plugin": ["wizard-opencode-plugin"],
                                  "provider": {"wizard": {"npm":
                                                          "@ai-sdk/openai-compatible"}}}),
                      encoding="utf-8")
        return gp

    def _run(self, gp: Path, out_name="cred.json"):
        src = _source(self.tmp, mode="login-process", global_config=str(gp))
        out = self.tmp / out_name
        code, out_s, err = _run_main(self.mod, "--source", str(src),
                                     "--out", str(out), "--login-timeout-s", "10")
        return code, out_s, err, out

    def test_success_captures_token_and_restores_config(self):
        gp = self._global_config()
        os.environ["MGH_CRED_STUB_TOKEN"] = "LOGIN-TOK"
        os.environ["MGH_CRED_STUB_OUT"] = str(self.tmp / "cred_probe_token.txt")
        os.environ["MGH_CRED_STUB_PY"] = sys.executable
        try:
            code, out_s, err, out = self._run(gp)
        finally:
            for k in ("MGH_CRED_STUB_TOKEN", "MGH_CRED_STUB_OUT",
                      "MGH_CRED_STUB_PY"):
                os.environ.pop(k, None)
        self.assertEqual(code, 0, err)
        body = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(body["apikey"], "LOGIN-TOK")
        self.assertNotIn("LOGIN-TOK", out_s)
        # global config restored: our probe entry gone, original content intact
        cfg = json.loads(gp.read_text(encoding="utf-8"))
        self.assertEqual(cfg["plugin"], ["wizard-opencode-plugin"])
        self.assertIn("wizard", cfg["provider"])
        # probe artifacts cleaned up
        self.assertFalse((self.tmp / "mgh_cred_probe.js").exists())
        self.assertFalse((self.tmp / "cred_probe_token.txt").exists())

    def test_failure_still_restores_config_exit2(self):
        gp = self._global_config()
        # no stub token → the probe output never appears → timeout path
        code, out_s, err, out = self._run(gp)
        self.assertEqual(code, 2)
        self.assertFalse(out.exists())
        self.assertIn("recipe", err.lower())
        cfg = json.loads(gp.read_text(encoding="utf-8"))
        self.assertEqual(cfg["plugin"], ["wizard-opencode-plugin"])
        self.assertFalse((self.tmp / "mgh_cred_probe.js").exists())

    def test_surgical_restore_survives_concurrent_edit(self):
        """An edit landing between append and restore must survive: the
        restore re-reads and removes ONLY our entry."""
        gp = self._global_config()
        os.environ["MGH_CRED_STUB_TOKEN"] = ""  # force the failure path
        # simulate the concurrent edit by a background rewrite of the config
        # WHILE the login child would be running: do it deterministically by
        # pre-writing the token output NEVER and patching time.sleep? —
        # simplest deterministic form: run the failure path and edit the file
        # immediately after append; here we assert the restore helper itself.
        self.mod  # noqa
        entry = str(self.tmp / "mgh_cred_probe.js")
        original = gp.read_bytes()
        import json as _json
        cfg = _json.loads(gp.read_text(encoding="utf-8"))
        cfg["plugin"].append(entry)
        gp.write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        # concurrent edit lands: user adds their own plugin meanwhile
        cfg = _json.loads(gp.read_text(encoding="utf-8"))
        cfg["plugin"].append("user-own-plugin")
        gp.write_text(_json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        self.mod._surgical_restore(gp, entry, original)
        cfg = _json.loads(gp.read_text(encoding="utf-8"))
        self.assertNotIn(entry, cfg["plugin"])
        self.assertIn("wizard-opencode-plugin", cfg["plugin"])
        self.assertIn("user-own-plugin", cfg["plugin"])

    def test_missing_global_config_exit2(self):
        src = _source(self.tmp, mode="login-process",
                      global_config=str(self.tmp / "absent.json"))
        code, _, err = _run_main(self.mod, "--source", str(src),
                                 "--out", str(self.tmp / "cred.json"))
        self.assertEqual(code, 2)
        self.assertIn("global config", err.lower())

    def test_missing_model_exit2(self):
        gp = self._global_config()
        src_body = _source(self.tmp, mode="login-process", global_config=str(gp))
        body = json.loads(src_body.read_text(encoding="utf-8"))
        del body["model"]
        src_body.write_text(json.dumps(body), encoding="utf-8")
        code, _, err = _run_main(self.mod, "--source", str(src_body),
                                 "--out", str(self.tmp / "cred.json"))
        self.assertEqual(code, 2)
        self.assertIn("model", err.lower())


class TestCheckAndWrite(unittest.TestCase):
    def setUp(self):
        self.mod = _load("mgh_credentials_check")
        self.tmp = Path(tempfile.mkdtemp(prefix="mgh_cred_check_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_check_valid_and_invalid(self):
        p = self.tmp / "cred.json"
        p.write_text(json.dumps(_valid_cred()), encoding="utf-8")
        code, out_s, _ = _run_main(self.mod, "--check", str(p))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out_s)["ok"])
        bad = self.tmp / "bad.json"
        bad.write_text(json.dumps({"v": 1}), encoding="utf-8")
        code, out_s, _ = _run_main(self.mod, "--check", str(bad))
        self.assertEqual(code, 1)
        summary = json.loads(out_s)
        self.assertFalse(summary["ok"])
        self.assertTrue(summary["problems"])

    def test_check_rejects_source_combo(self):
        code, _, err = _run_main(self.mod, "--check", "x.json",
                                 "--source", "y.json")
        self.assertEqual(code, 2)

    def test_written_file_permissions_restrictive_posix(self):
        out = self.tmp / "cred.json"
        self.mod._write_cred(out, _valid_cred())
        self.assertTrue(out.is_file())
        if os.name == "posix":
            mode = out.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_misuse_no_args_exit2(self):
        code, _, err = _run_main(self.mod)
        self.assertEqual(code, 2)
        self.assertIn("--source", err)


if __name__ == "__main__":
    unittest.main()
