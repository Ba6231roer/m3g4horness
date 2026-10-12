#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
create_dsh_profile — ensure the `mgh` dsh profile skeleton exists (install-time leaf).

The mgh profile is the run carrier for dsh-side dispatch (fan-out units spawn as
`dsh --profile mgh --patch <tier>.yml`; interactive stages ride its named
delegation instances). Its skeleton is two files:

- `package.json` — declares the bundle composition (base + headless, resolved
  through the dsh install anchor, no `dsh plugin add` needed; spike-verified on
  0.1.5-rc.2 with empty dependencies) and `patchReload: startup`.
- `cordis.yml` — empty root entry list; all mgh content lands in the
  `cordis.patch.yml` managed block written by install_dsh_wiring.py.

Additive-only discipline: the installer CREATES what is missing and NEVER
rewrites an existing file (idempotent reruns report `present`). A foreign
package.json under profiles/mgh that lacks the required bundles is a name
collision with a user-owned profile — fail-loud with a merge recipe instead of
clobbering it (user-owned profiles are never touched; this file is the guard
for the one directory named `mgh`).

CLI (`--help` is the contract surface):
  py create_dsh_profile.py --dsh-home <abs dsh home dir>

stdout (R5.3b): {"profile_dir":"...","package_json":"created|present",
                 "cordis_yml":"created|present"}
stderr = diagnostics. Exit codes: 0 ok · 1 collision/IO (fail-loud + recipe) ·
2 misuse (relative path, missing home).

Build/install-time tool; NOT an /mgh-* orchestrator.
Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/sys/pathlib).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REQUIRED_BUNDLES = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless")

PACKAGE_JSON = {
    "name": "dsh-profile-mgh",
    "private": True,
    "dependencies": {},
    "dsh": {
        "profile": {
            "bundles": list(REQUIRED_BUNDLES),
            "patchReload": "startup",
        }
    },
}

CORDIS_YML = (
    "# mgh profile root — an empty entry list. All mgh content rides the\n"
    "# cordis.patch.yml managed block (install_dsh_wiring.py). Edit that,\n"
    "# not this file.\n"
    "[]\n"
)


def _bundles_ok(path: Path) -> bool:
    """True iff an EXISTING package.json already declares both bundles."""
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
        bundles = body["dsh"]["profile"]["bundles"]
        return isinstance(bundles, list) and all(b in bundles
                                                 for b in REQUIRED_BUNDLES)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    ap = argparse.ArgumentParser(
        description="ensure the mgh dsh profile skeleton (package.json + cordis.yml)")
    ap.add_argument("--dsh-home", required=True,
                    help="ABSOLUTE dsh home dir ($DSH_HOME, default ~/.dsh); the "
                         "profile is created under <home>/profiles/mgh")
    args = ap.parse_args()

    home = Path(args.dsh_home)
    if not home.is_absolute():
        print(f"error: --dsh-home must be ABSOLUTE: {home}", file=sys.stderr)
        return 2
    if not home.is_dir():
        print(f"error: dsh home not found: {home}\n"
              f"  recipe: install/boot dsh first, or point --dsh-home at the real "
              f"$DSH_HOME (the installer never creates the dsh home itself).",
              file=sys.stderr)
        return 2

    prof = home / "profiles" / "mgh"
    pkg = prof / "package.json"
    cordis = prof / "cordis.yml"
    result = {"profile_dir": str(prof)}

    if pkg.exists():
        if not _bundles_ok(pkg):
            print(f"error: {pkg} exists but does not declare the required bundles "
                  f"{list(REQUIRED_BUNDLES)} — this looks like a user-owned profile "
                  f"named 'mgh'.\n  recipe: rename your profile, or merge the two "
                  f"bundle entries into its dsh.profile.bundles by hand, then rerun "
                  f"the installer. The installer NEVER rewrites a foreign "
                  f"package.json.", file=sys.stderr)
            return 1
        result["package_json"] = "present"
    else:
        prof.mkdir(parents=True, exist_ok=True)
        pkg.write_text(json.dumps(PACKAGE_JSON, indent=2) + "\n",
                       encoding="utf-8")
        result["package_json"] = "created"

    if cordis.exists():
        result["cordis_yml"] = "present"
    else:
        prof.mkdir(parents=True, exist_ok=True)
        cordis.write_text(CORDIS_YML, encoding="utf-8")
        result["cordis_yml"] = "created"

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
