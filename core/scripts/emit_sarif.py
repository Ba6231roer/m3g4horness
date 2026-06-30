#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
emit_sarif — s9 deterministic SARIF 2.1.0 emission with CVSS 3.1 + CWE.

Stdlib only. Computes the CVSS 3.1 base score from each finding's vector,
derives severity from the official qualitative band (label can never disagree
with the score), maps CWE ids, and writes SARIF 2.1.0.

Usage:
  py emit_sarif.py --in findings.json --out report.sarif
       [--application-id 12345] [--repo-name myapp] [--tool mgh-sast]
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

# CVSS 3.1 metric values
AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
AC = {"L": 0.77, "H": 0.44}
PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}   # scope unchanged
PR_C = {"N": 0.85, "L": 0.68, "H": 0.50}   # scope changed
UI = {"N": 0.85, "R": 0.62}
CIA = {"H": 0.56, "L": 0.22, "N": 0.00}


def parse_vector(vec):
    """Parse 'CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H' -> dict."""
    if not vec:
        return {}
    out = {}
    for part in vec.split("/"):
        if ":" in part and not part.startswith("CVSS"):
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def roundup(x):
    """Official CVSS 3.1 Roundup."""
    int_input = round(x * 100000)
    if int_input % 10000 == 0:
        return int_input / 100000.0
    return (math.floor(int_input / 10000) + 1) / 10.0


def cvss_base(vec_dict):
    """Return base score (float) or None if vector incomplete."""
    need = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
    if not all(k in vec_dict for k in need):
        return None
    scope_changed = vec_dict["S"] == "C"
    pr = (PR_C if scope_changed else PR_U)[vec_dict["PR"]]
    exploitab = 8.22 * AV[vec_dict["AV"]] * AC[vec_dict["AC"]] * pr * UI[vec_dict["UI"]]
    isc = 1 - ((1 - CIA[vec_dict["C"]]) * (1 - CIA[vec_dict["I"]]) *
               (1 - CIA[vec_dict["A"]]))
    if scope_changed:
        impact = 7.52 * (isc - 0.029) - 3.25 * (isc - 0.02) ** 15
    else:
        impact = 6.42 * isc
    if impact <= 0:
        return 0.0
    if scope_changed:
        return roundup(min(1.08 * (impact + exploitab), 10))
    return roundup(min(impact + exploitab, 10))


def severity_band(score):
    if score is None:
        return "Info"
    if score == 0.0:
        return "Info"
    if score < 4.0:
        return "Low"
    if score < 7.0:
        return "Medium"
    if score < 9.0:
        return "High"
    return "Critical"


# A small CWE name map for common ids; unknown ids get a generic label.
CWE_NAMES = {
    "CWE-79": "Improper Neutralization of Input During Web Page Generation (XSS)",
    "CWE-89": "SQL Injection",
    "CWE-22": "Path Traversal",
    "CWE-78": "OS Command Injection",
    "CWE-20": "Improper Input Validation",
    "CWE-79": "Cross-site Scripting",
    "CWE-352": "Cross-Site Request Forgery",
    "CWE-287": "Improper Authentication",
    "CWE-862": "Missing Authorization",
    "CWE-863": "Incorrect Authorization",
    "CWE-502": "Deserialization of Untrusted Data",
    "CWE-295": "Improper Certificate Validation",
    "CWE-319": "Cleartext Transmission of Sensitive Information",
    "CWE-798": "Use of Hard-coded Credentials",
    "CWE-327": "Use of a Broken or Risky Cryptographic Algorithm",
    "CWE-400": "Uncontrolled Resource Consumption",
    "CWE-918": "Server-Side Request Forgery",
    "CWE-94": "Code Injection",
    "CWE-269": "Improper Privilege Management",
    "CWE-611": "XML External Entity (XXE)",
}


def enrich(findings):
    """Set cvss_score + severity on each finding (severity always from band)."""
    for f in findings:
        vec = parse_vector(f.get("cvss_vector"))
        score = cvss_base(vec)
        f["cvss_score"] = score if score is not None else f.get("cvss_score")
        f["severity"] = severity_band(f.get("cvss_score"))
    return findings


def loc(f):
    ref = f.get("source_ref") or f.get("file") or ""
    uri, line = ref, 1
    if ":" in ref:
        uri, _, ln = ref.rpartition(":")
        try:
            line = int(ln)
        except ValueError:
            uri = ref
    if not uri or "/" not in uri and "\\" not in uri:
        uri = f.get("file") or uri
    return uri, line


def emit(findings, tool, repo_name, app_id):
    rules = {}
    results = []
    for f in findings:
        cwe = (f.get("cwe") or "CWE-Other").strip()
        rid = cwe.replace("CWE-", "cwe-")
        if rid not in rules:
            rules[rid] = {
                "id": rid, "name": cwe,
                "shortDescription": {"text": CWE_NAMES.get(cwe, cwe)},
                "properties": {"tags": ["security", cwe.lower()],
                               "precision": "medium"},
            }
        uri, line = loc(f)
        results.append({
            "ruleId": rid,
            "level": {"Critical": "error", "High": "error", "Medium": "warning",
                      "Low": "note", "Info": "none"}.get(f["severity"], "note"),
            "message": {"text": f"{f.get('title','')}\n\n{f.get('impact','')}"},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": uri},
                "region": {"startLine": max(1, line)}}}],
            "partialFingerprints": {"primaryLocationLineHash": (
                f"{uri}:{line}:{f.get('vuln_class','')}")},
            "properties": {
                "severity": f["severity"],
                "cvss": {"score": f.get("cvss_score"),
                         "vector": f.get("cvss_vector")},
                "cwe": cwe,
                "confidence": f.get("confidence"),
                "source_ref": f.get("source_ref"),
                "sink_ref": f.get("sink_ref"),
            },
        })
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": tool, "informationUri": "https://example.invalid/mgh-sast",
                "rules": list(rules.values())}},
            "results": results,
            "properties": {"applicationId": app_id, "repositoryName": repo_name},
        }],
    }
    return sarif


def main():
    ap = argparse.ArgumentParser(description="s9 SARIF 2.1.0 emission")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--application-id", default="")
    ap.add_argument("--repo-name", default="")
    ap.add_argument("--tool", default="mgh-sast")
    args = ap.parse_args()
    data = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    findings = data.get("findings", data if isinstance(data, list) else [])
    enrich(findings)
    sarif = emit(findings, args.tool, args.repo_name, args.application_id)
    Path(args.out).write_text(json.dumps(sarif, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    # also write back enriched findings next to it
    Path(args.out + ".findings.json").write_text(
        json.dumps({"findings": findings}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    dist = {}
    for f in findings:
        dist[f["severity"]] = dist.get(f["severity"], 0) + 1
    print(json.dumps({"results": len(findings), "severity": dist}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
