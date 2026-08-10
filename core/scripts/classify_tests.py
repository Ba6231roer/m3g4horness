#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
classify_tests — deterministic test-layer classifier for /mgh-ut-init.

Scans `<target>` test source trees and buckets every test file by 被测层 / SUT 类型
(controller / service / repository / config / integration / util / other) — the fan-out
unit for ut-init's per-group sample extraction. Classification is by ACTUAL annotation +
import + package path + filename (never name alone). Within a bucket, mixed sub-styles
(e.g. `@WebMvcTest` slice vs `@SpringBootTest`+`TestRestTemplate` full-stack) are split
into sub-groups. Each group reports a uniformity hint (dominant annotation ratio) + a
cheap assertion-density quality hint (both drive downstream sampling).

Pinned strategy (design Open Questions):
- Bucket set: controller / service / repository / config / integration / util / other.
- Uniformity threshold: a group is `uniform` iff its dominant style token covers
  >= `--subsplit-threshold` (default 0.8) of the group; else `hetero`.
- Util hetero sub-split: util files get a style sub-family by signal priority
  spring-context > mock-static > mock-time > parameterized > pure; mixed util buckets
  split per sub-family when no single sub-family dominates (same threshold).

Zero runtime deps (Python >=3.10 stdlib: argparse/json/os/pathlib/re/sys).

CLI contract (`--help` is the contract surface, R5.1):
  py classify_tests.py --repo <target> [--out <dir>] [--scope <path|package|file>]
       [--max-files N] [--subsplit-threshold F] [--check <out-dir>]

  --repo               target project root (default .; recorded ABSOLUTE).
  --out                run dir for test_groups.json (default <target>/.mgh-ut-init).
  --scope              path:<dir>|package:<pkg>|file:<glob> (default: whole repo).
  --max-files          warn-and-continue source-file cap (default 200000).
  --subsplit-threshold dominant-style ratio >= this counts a group uniform (default 0.8).
  --check <out-dir>    validate an existing run-dir's test_groups.json (R5.9); exit 0/2.

stdout (structured JSON; stderr = progress only, R5.3b):
  {"repo":"<abs>","groups":N,"scanned":N,"unclassified":M,"truncated":false}
Exit codes (R5.3b): 0 ok · 1 general (out dir unusable) · 2 misuse (argparse / --check
violation). stdout=JSON / stderr=progress strictly split. Idempotent, no TTY.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

# Self-locate this script's dir (self-contained family, R5.3a).
sys.path.insert(0, str(Path(__file__).resolve().parent))

DEFAULT_MAX_FILES = 200_000
DEFAULT_SUBSPLIT_THRESHOLD = 0.8
EXCLUDE_DIR = {".git", ".hg", ".svn", "node_modules", "vendor", "dist", "build",
               "target", ".venv", "venv", "__pycache__", ".idea", ".vscode", "bin",
               "obj", "out", ".gradle"}
# Test source-tree directory segments (a file under one of these is a candidate test file).
TEST_SEGMENTS = {"test", "tests", "__tests__", "__mocks__", "spec", "specs",
                 "integration-test", "integrationTest", "it", "e2e"}
TEST_SUFFIXES = (".java", ".kt", ".scala", ".groovy")
TEST_NAME_RX = re.compile(r"(Test|Tests|IT|ITest|TestCase)$")

# --- signal tables (detected from file text; NEVER name-guessing alone) ---
# annotation / import substrings per layer
_SLICE_ANNOTATIONS = ("WebMvcTest", "WebFluxTest")
_REPO_ANNOTATIONS = ("DataJpaTest", "JdbcTest", "MybatisTest", "DataMongoTest", "RestClientTest")
_TESTCONTAINERS = ("Testcontainers", "org.testcontainers")
_SPRING_BOOT_TEST = ("SpringBootTest", "org.springframework.boot.test.context.SpringBootTest")
_FULLSTACK = ("TestRestTemplate", "LocalServerPort")
_CONFIG = ("TestConfiguration", "@Configuration")
_SERVICE_MOCK = ("InjectMocks", "MockitoExtension", "org.mockito.Mock")
_STATIC_MOCK = ("MockedStatic", "mockStatic")
_TIME_MOCK = ("Clock", "mockTime", "InstantSource")
_PARAMETRIZED = ("ParameterizedTest", "TestFactory", "RepeatedTest")

# annotation family token per file (the uniform/hetero + split signal)
_ANNOTATION_TOKENS = (
    ("WebMvcTest", "WebMvcTest"),
    ("WebFluxTest", "WebFluxTest"),
    ("SpringBootTest", "SpringBootTest"),
    ("DataJpaTest", "DataJpaTest"),
    ("JdbcTest", "JdbcTest"),
    ("MybatisTest", "MybatisTest"),
    ("DataMongoTest", "DataMongoTest"),
    ("Testcontainers", "Testcontainers"),
    ("ParameterizedTest", "ParameterizedTest"),
    ("MockitoExtension", "MockitoExtension"),
    ("TestConfiguration", "TestConfiguration"),
    ("Configuration", "Configuration"),
)

# assertion keywords for the cheap assertion-density hint
_ASSERTION_TOKENS = (
    "assertThat", "assertEquals", "assertNotEquals", "assertTrue", "assertFalse",
    "assertNull", "assertNotNull", "assertThrows", "assertAll", "assertArrayEquals",
    "assertSame", "assertInstanceOf", "verify(", "verifyNoMoreInteractions",
    "assertThatCode", "assertThatThrownBy", "isEqualTo(", "isTrue()", "isFalse()",
    "contains(", "isInstanceOf(", "isNotNull(", "isNull(", "matches(",
)
_TEST_METHOD_TOKENS = ("@Test", "@ParameterizedTest", "@TestFactory", "@RepeatedTest")

# package / filename hints (fallback AFTER annotation/import signals)
_PKG_HINTS = (
    ("controller", "controller"), ("service", "service"), ("repository", "repository"),
    ("repositories", "repository"), ("dao", "repository"), ("mapper", "repository"),
    ("config", "config"), ("configuration", "config"), ("util", "util"),
    ("utils", "util"), ("common", "util"), ("support", "util"), ("helper", "util"),
    ("integration", "integration"), ("it", "integration"), ("e2e", "integration"),
)
_NAME_HINTS = (
    ("ControllerTest", "controller"), ("ServiceTest", "service"),
    ("RepositoryTest", "repository"), ("DaoTest", "repository"), ("MapperTest", "repository"),
    ("ConfigTest", "config"), ("ConfigurationTest", "config"),
    ("UtilTest", "util"), ("UtilsTest", "util"), ("HelperTest", "util"),
    ("IntegrationTest", "integration"), ("ITest", "integration"),
)
# util sub-split signals, in priority order (first match wins)
_UTIL_STYLES = (
    ("spring-context", ("SpringBootTest", "WebMvcTest", "DataJpaTest", "TestConfiguration",
                        "@MockBean", "MockMvc", "TestRestTemplate")),
    ("mock-static", _STATIC_MOCK),
    ("mock-time", _TIME_MOCK),
    ("parameterized", _PARAMETRIZED),
    ("pure", ()),  # fallback: JUnit + assertions, no distinctive signals
)
_LAYERS = ("controller", "service", "repository", "config", "integration", "util", "other")


def _has(text: str, tokens) -> bool:
    return any(t in text for t in tokens)


def _anno_token(text: str) -> str:
    """Dominant test-annotation token (uniformity hint key); first match in priority."""
    for needle, token in _ANNOTATION_TOKENS:
        if needle in text:
            return token
    return "none"


def _pkg_of(rel: str) -> str:
    return rel.replace("\\", "/").rsplit("/", 1)[0] if "/" in rel.replace("\\", "/") else ""


def _layer_bucket(text: str, rel: str) -> str:
    """Primary layer bucket, by annotation/import signal first, then hint fallback."""
    if _has(text, _SLICE_ANNOTATIONS):
        return "controller"
    if _has(text, _REPO_ANNOTATIONS):
        return "repository"
    if _has(text, _TESTCONTAINERS):
        return "integration"
    if _has(text, _SPRING_BOOT_TEST):
        if _has(text, _FULLSTACK):
            return "integration"
        if _has(text, "MockMvc"):
            return "controller"
        return "service"
    if _has(text, _CONFIG):
        return "config"
    if _has(text, _SERVICE_MOCK):
        return "service"
    # package / filename hints (fallback only — signals win over names)
    pkg = _pkg_of(rel)
    for needle, layer in _PKG_HINTS:
        if needle in pkg:
            return layer
    for needle, layer in _NAME_HINTS:
        if rel.endswith(needle):
            return layer
    if _has(text, _STATIC_MOCK):
        return "util"
    if _has(text, _PARAMETRIZED) or _has(text, "assertThat") or _has(text, "Assertions"):
        return "util"
    return "other"


def _family(bucket: str, text: str) -> str:
    """Style family within a bucket (the mix-substyle split key)."""
    if bucket == "util":
        for name, tokens in _UTIL_STYLES:
            if name == "pure":
                return "pure"
            if _has(text, tokens):
                return name
        return "pure"
    if bucket == "controller":
        if _has(text, "WebMvcTest"):
            return "WebMvcTest"
        if _has(text, "WebFluxTest"):
            return "WebFluxTest"
        return "SpringBootTest" if _has(text, _SPRING_BOOT_TEST) else "none"
    if bucket == "service":
        if _has(text, "MockitoExtension"):
            return "MockitoExtension"
        if _has(text, _SPRING_BOOT_TEST):
            return "SpringBootTest"
        return "none"
    if bucket == "repository":
        for needle, token in (("DataJpaTest", "DataJpaTest"), ("JdbcTest", "JdbcTest"),
                              ("MybatisTest", "MybatisTest"), ("DataMongoTest", "DataMongoTest")):
            if needle in text:
                return token
        return "none"
    if bucket == "integration":
        if _has(text, _TESTCONTAINERS):
            return "Testcontainers"
        return "SpringBootTest" if _has(text, _SPRING_BOOT_TEST) else "none"
    if bucket == "config":
        if "TestConfiguration" in text:
            return "TestConfiguration"
        if "@Configuration" in text:
            return "Configuration"
        return "none"
    return "other"


def _assert_density(text: str) -> float:
    """Cheap quality hint: assertion hits per test method (0 if no test methods)."""
    methods = sum(text.count(t) for t in _TEST_METHOD_TOKENS)
    if methods <= 0:
        return 0.0
    hits = sum(text.count(t) for t in _ASSERTION_TOKENS)
    return round(hits / methods, 2)


def _is_test_file(rel: str) -> bool:
    """A file is a test candidate iff in a test source tree (dir segment) OR a test-like
    name; the content check (`contains JUnit/TestNG marker`) is applied by the caller."""
    if not rel.endswith(TEST_SUFFIXES):
        return False
    parts = rel.replace("\\", "/").split("/")
    if any(seg in TEST_SEGMENTS for seg in parts[:-1]):
        return True
    return bool(TEST_NAME_RX.search(parts[-1]))


def _is_test_framework(text: str) -> bool:
    return _has(text, ("org.junit", "org.testng", "@Test", "@ParameterizedTest"))


def _walk_test_files(repo: Path, seed: set | None):
    """Yield (path, rel) test files under repo, excluding build/tooling dirs. When `seed`
    (from --scope) is given, only files whose rel is in the seed are considered."""
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in EXCLUDE_DIR for part in p.parts):
            continue
        rel = p.relative_to(repo).as_posix()
        if seed is not None and rel not in seed:
            continue
        if not _is_test_file(rel):
            continue
        yield p, rel


def _resolve_scope(repo: Path, scope: str | None):
    """Return (seed_files:set[rel] | None, scope_note). None = whole repo."""
    if not scope:
        return None, "full-repo"
    if scope.startswith("path:"):
        d = repo / scope[5:]
        if not d.is_dir():
            return set(), scope
        seed = set()
        for p in d.rglob("*"):
            if p.is_file():
                rel = p.relative_to(repo).as_posix()
                if _is_test_file(rel):
                    seed.add(rel)
        return seed, scope
    if scope.startswith("package:"):
        pkg = scope[8:].replace(".", "/")
        seed = set()
        for d in (repo / "src" / "test" / "java" / pkg, repo / pkg):
            if d.is_dir():
                for p in d.rglob("*"):
                    if p.is_file():
                        rel = p.relative_to(repo).as_posix()
                        if _is_test_file(rel):
                            seed.add(rel)
        return seed, scope
    if scope.startswith("file:"):
        import fnmatch
        pat = scope[5:]
        seed = set()
        for p, rel in _walk_test_files(repo, None):
            if fnmatch.fnmatch(rel, pat):
                seed.add(rel)
        return seed, scope
    return None, "full-repo"


def _build_groups(entries: list, threshold: float) -> list:
    """entries: [(rel, text)]. Bucket → split by family → uniformity/assert_density per group.
    Returns groups[] (deterministic: layers/families/members all sorted)."""
    buckets: dict[str, list] = {}
    for rel, text in entries:
        bucket = _layer_bucket(text, rel)
        buckets.setdefault(bucket, []).append((rel, text))

    groups = []
    for layer in sorted(buckets):
        files = buckets[layer]
        # count families for the mix-substyle split
        fam_counts: dict[str, int] = {}
        fam_of = {}
        for rel, text in files:
            f = _family(layer, text)
            fam_of[rel] = f
            fam_counts[f] = fam_counts.get(f, 0) + 1
        n = len(files)
        max_ratio = max(fam_counts.values()) / n if n else 0.0
        if len(fam_counts) <= 1 or max_ratio >= threshold:
            # single family (or dominant): one group for this layer
            groups.append(_make_group(layer, fam_of.get(files[0][0], "none"), files,
                                      threshold))
        else:
            # mixed sub-styles: split per family
            by_fam: dict[str, list] = {}
            for rel, text in files:
                by_fam.setdefault(fam_of[rel], []).append((rel, text))
            for f in sorted(by_fam):
                groups.append(_make_group(layer, f, by_fam[f], threshold))
    groups.sort(key=lambda g: g["id"])
    return groups


def _make_group(layer: str, family: str, files: list, threshold: float) -> dict:
    """files: [(rel, text)] sorted by rel for determinism. Computes uniformity from the
    group's annotation-token distribution + assertion density."""
    files = sorted(files, key=lambda t: t[0])
    tokens = {}
    densities = []
    for _rel, text in files:
        t = _anno_token(text)
        tokens[t] = tokens.get(t, 0) + 1
        densities.append(_assert_density(text))
    n = len(files)
    dom_ratio = max(tokens.values()) / n if n else 0.0
    uniformity = "uniform" if dom_ratio >= threshold else "hetero"
    gid = layer if family in ("none", "other") else f"{layer}::{family}"
    return {
        "id": gid,
        "layer": layer,
        "family": family,
        "uniformity": uniformity,
        "member_count": n,
        "assert_density": round(sum(densities) / n, 2) if n else 0.0,
        "annotation_counts": {k: tokens[k] for k in sorted(tokens)},
        "members": [r for r, _ in files],
    }


def _atomic_write_json(path: Path, obj):
    p = path
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def _run_check(outdir: Path) -> int:
    """R5.9 boundary check: validate an existing run-dir's test_groups.json."""
    violations = []
    gp = outdir / "test_groups.json"
    if not gp.is_file():
        violations.append({"file": "test_groups.json", "issue": "missing"})
        print(f"[classify --check] {outdir}: 1 violation(s)", file=sys.stderr)
        print(json.dumps({"check": "classify", "ok": False, "groups": 0,
                          "violations": violations}, ensure_ascii=False))
        return 2
    try:
        data = json.loads(gp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        violations.append({"file": "test_groups.json", "issue": f"malformed: {e}"})
        print(f"[classify --check] {outdir}: 1 violation(s)", file=sys.stderr)
        print(json.dumps({"check": "classify", "ok": False, "groups": 0,
                          "violations": violations}, ensure_ascii=False))
        return 2
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        violations.append({"file": "test_groups.json",
                           "issue": "wrapper must be {repo,groups[]}"})
    else:
        repo = Path(data.get("repo") or outdir.parent)
        seen_ids, seen_members = set(), set()
        for i, g in enumerate(data["groups"]):
            if not isinstance(g, dict):
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": "group not an object"})
                continue
            gid = g.get("id")
            if not gid:
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": "group missing `id`"})
            elif gid in seen_ids:
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": f"duplicate group id {gid}"})
            else:
                seen_ids.add(gid)
            if g.get("layer") not in _LAYERS:
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": f"layer {g.get('layer')!r} not in bucket set"})
            if g.get("uniformity") not in ("uniform", "hetero"):
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": "uniformity must be uniform|hetero"})
            members = g.get("members")
            if not isinstance(members, list) or not members:
                violations.append({"file": "test_groups.json", "index": i,
                                   "issue": "members must be a non-empty list"})
            else:
                for m in members:
                    if not isinstance(m, str) or not m:
                        violations.append({"file": "test_groups.json", "index": i,
                                           "issue": "member must be a non-empty string"})
                        continue
                    if m in seen_members:
                        violations.append({"file": "test_groups.json", "index": i,
                                           "issue": f"member {m} appears in >1 group"})
                    seen_members.add(m)
                    if not (repo / m).is_file():
                        violations.append({"file": "test_groups.json", "index": i,
                                           "issue": f"member missing on disk: {m}"})
    ok = not violations
    print(f"[classify --check] {outdir}: {'OK' if ok else f'{len(violations)} violation(s)'}",
          file=sys.stderr)
    print(json.dumps({"check": "classify", "ok": ok,
                      "groups": len(data.get("groups", [])) if isinstance(data, dict) else 0,
                      "violations": violations}, ensure_ascii=False))
    return 0 if ok else 2


def main():
    ap = argparse.ArgumentParser(
        description="classify test files into layer-groups for /mgh-ut-init (deterministic)")
    ap.add_argument("--repo", required=False, help="target project root (default .)")
    ap.add_argument("--out", required=False,
                    help="run dir for test_groups.json (default <target>/.mgh-ut-init)")
    ap.add_argument("--scope", help="path:<dir>|package:<pkg>|file:<glob>")
    ap.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES,
                    help="warn-and-continue source-file cap (default 200000)")
    ap.add_argument("--subsplit-threshold", type=float, default=DEFAULT_SUBSPLIT_THRESHOLD,
                    help="dominant-style ratio >= this counts a group uniform (default 0.8)")
    ap.add_argument("--check", metavar="<out-dir>",
                    help="validate an existing run-dir's test_groups.json (R5.9); exit 0/2")
    # Emit JSON / glyphs cleanly regardless of host console codepage (e.g. cp936/gbk).
    # Before parse_args so --help is utf-8 too. No-op on StringIO (in-process tests).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = ap.parse_args()

    if args.check:
        return _run_check(Path(args.check).resolve())
    if not args.repo or not args.out:
        print("error: --repo and --out are required (or use --check <out-dir>)", file=sys.stderr)
        return 2
    if not (0.0 <= args.subsplit_threshold <= 1.0):
        print(f"error: --subsplit-threshold must be in [0,1] (got {args.subsplit_threshold})",
              file=sys.stderr)
        return 2

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: --repo not a directory: {repo}", file=sys.stderr)
        return 1
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    if not outdir.is_dir():
        print(f"error: --out not usable: {outdir}", file=sys.stderr)
        return 1

    seed, scope_note = _resolve_scope(repo, args.scope)
    entries, scanned, truncated = [], 0, False
    unclassified: list[str] = []
    for p, rel in _walk_test_files(repo, seed):
        scanned += 1
        if scanned > args.max_files:
            truncated = True
            break
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"warn: unreadable {rel}: {e}", file=sys.stderr)
            continue
        if not _is_test_framework(text):
            continue
        if _layer_bucket(text, rel) == "other":
            unclassified.append(rel)
        entries.append((rel, text))
        if scanned % 1000 == 0:
            print(f"progress: scanned {scanned} test files", file=sys.stderr)

    groups = _build_groups(entries, args.subsplit_threshold)
    # keep unclassified files out of groups; they are disclosed separately
    payload = {
        "repo": str(repo),
        "scope": {"note": scope_note},
        "generated_by": "classify_tests.py",
        "groups": groups,
        "unclassified": sorted(unclassified),
        "scanned": scanned,
        "truncated": truncated,
        "subsplit_threshold": args.subsplit_threshold,
    }
    _atomic_write_json(outdir / "test_groups.json", payload)
    summary = {"repo": str(repo), "groups": len(groups), "scanned": scanned,
               "unclassified": len(unclassified), "truncated": truncated}
    print(f"[classify_tests] {len(groups)} group(s) from {len(entries)} test file(s) "
          f"(scanned {scanned}, {len(unclassified)} unclassified)", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
