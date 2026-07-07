#!/usr/bin/env python3
"""
gate_check.py — deterministic gate between ticket-tranche waves.

Checks the machine-verifiable invariants only: structure, ticket continuity,
verification of external claims, traceability, and index coverage. Anything
requiring judgment (scope drift, semantic contradiction) is the critic agent's
job, not this script's.

Exit code 0 = pass. Nonzero = fail. Findings always printed to stdout as JSON.

Usage:
  python gate_check.py --stage 1 --artifact tickets.base.json
  python gate_check.py --stage 2 --artifact tickets.enriched.json --prev tickets.base.json [--repo-root .]
  python gate_check.py --stage 3 --artifact build-contract.json --index stack.index.json [--repo-root .]
"""
import argparse
import json
import os
import sys


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fail(findings, msg):
    findings.append(msg)


def check_stage1(art, findings, **_):
    if not isinstance(art.get("canonical_goal"), str) or not art["canonical_goal"].strip():
        fail(findings, "canonical_goal missing or empty (the tranche has no north star)")
    tickets = art.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        fail(findings, "tickets missing or empty")
        return
    seen = set()
    for i, t in enumerate(tickets):
        tid = t.get("id")
        loc = f"ticket[{i}]" + (f" id={tid}" if tid else "")
        if not tid:
            fail(findings, f"{loc}: missing id")
        elif tid in seen:
            fail(findings, f"{loc}: duplicate id")
        else:
            seen.add(tid)
        for field in ("title", "goal", "acceptance"):
            if not t.get(field):
                fail(findings, f"{loc}: missing/empty '{field}'")
        if not isinstance(t.get("suspected_files"), list):
            fail(findings, f"{loc}: 'suspected_files' must be a list")


def check_stage2(art, findings, prev=None, repo_root=None, **_):
    tickets = art.get("tickets")
    if not isinstance(tickets, list) or not tickets:
        fail(findings, "tickets missing or empty")
        return
    # continuity: no base ticket id dropped
    if prev:
        base_ids = {t.get("id") for t in prev.get("tickets", [])}
        now_ids = {t.get("id") for t in tickets}
        dropped = base_ids - now_ids
        if dropped:
            fail(findings, f"tickets dropped since wave 1: {sorted(dropped)}")
    for i, t in enumerate(tickets):
        loc = f"ticket[{i}] id={t.get('id')}"
        refs = t.get("code_refs")
        if not isinstance(refs, list) or not refs:
            fail(findings, f"{loc}: missing code_refs (ticket was not grounded against real code)")
        else:
            for r in refs:
                if not r.get("file") or not r.get("symbol"):
                    fail(findings, f"{loc}: code_ref needs both 'file' and 'symbol': {r}")
                elif repo_root and not os.path.exists(os.path.join(repo_root, r["file"])):
                    fail(findings, f"{loc}: code_ref file does not exist: {r['file']}")
        # every external claim must be verified
        for c in t.get("external_claims", []):
            if not c.get("verification"):
                fail(findings, f"{loc}: UNVERIFIED external_claim admitted: {c.get('claim', c)!r}")


def check_stage3(art, findings, index=None, repo_root=None, **_):
    if not art.get("end_goal"):
        fail(findings, "end_goal missing")
    if not isinstance(art.get("anti_duplication_rules"), list) or not art["anti_duplication_rules"]:
        fail(findings, "anti_duplication_rules missing or empty")

    fmm = art.get("file_modification_map")
    if not isinstance(fmm, list) or not fmm:
        fail(findings, "file_modification_map missing or empty")
        fmm = []
    for entry in fmm:
        if not entry.get("file"):
            fail(findings, f"file_modification_map entry missing 'file': {entry}")
        if not entry.get("ticket_ids"):
            fail(findings, f"file '{entry.get('file')}' traces to no ticket (orphan change)")
        if repo_root and entry.get("file") and entry.get("is_new") is not True:
            if not os.path.exists(os.path.join(repo_root, entry["file"])):
                fail(findings, f"file_modification_map: '{entry['file']}' not found and not marked is_new")

    # mesh check: a shared function name must have exactly one owner + one signature
    by_name = {}
    for sf in art.get("shared_functions", []):
        name = sf.get("name")
        if not name:
            fail(findings, f"shared_function missing 'name': {sf}")
            continue
        by_name.setdefault(name, []).append(sf)
    for name, defs in by_name.items():
        owners = {d.get("owner_file") for d in defs}
        sigs = {d.get("signature") for d in defs}
        if len(owners) > 1:
            fail(findings, f"shared_function '{name}' has multiple owners {owners} (mesh failed)")
        if len(sigs) > 1:
            fail(findings, f"shared_function '{name}' has conflicting signatures (mesh failed)")

    # per-ticket expected_output
    for i, t in enumerate(art.get("tickets", [])):
        if not t.get("expected_output"):
            fail(findings, f"ticket[{i}] id={t.get('id')}: missing expected_output")

    # index coverage: every modified file appears in the file->ticket index
    if index is not None:
        file_idx = index.get("file_to_tickets", {})
        for entry in fmm:
            f = entry.get("file")
            if f and f not in file_idx:
                fail(findings, f"index gap: modified file '{f}' absent from stack.index file_to_tickets")
        if not index.get("symbol_to_tickets"):
            fail(findings, "stack.index has no symbol_to_tickets map (worker cannot do symbol lookup)")


CHECKS = {1: check_stage1, 2: check_stage2, 3: check_stage3}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=int, required=True, choices=[1, 2, 3])
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--prev")
    ap.add_argument("--index")
    ap.add_argument("--repo-root")
    args = ap.parse_args()

    findings = []
    try:
        art = load(args.artifact)
    except Exception as e:
        print(json.dumps({"stage": args.stage, "passed": False, "findings": [f"cannot read artifact: {e}"]}, indent=2))
        sys.exit(2)

    prev = load(args.prev) if args.prev else None
    index = load(args.index) if args.index else None

    CHECKS[args.stage](art, findings, prev=prev, index=index, repo_root=args.repo_root)

    passed = not findings
    print(json.dumps({"stage": args.stage, "passed": passed, "findings": findings}, indent=2))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
