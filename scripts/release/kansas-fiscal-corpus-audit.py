#!/usr/bin/env python3
"""Read real KanView account evidence without loading or publishing anything.

This is an operator design/acceptance audit, not a canonical identity resolver
or graph publisher. No database, network, provider, or payroll/vendor access.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "statecivics.kanview-account-audit.v1"
SOURCE_URL = "https://kanview.ks.gov/DataDownload.aspx"
REQUIRED_COLUMNS = (
    "Fiscal_Year", "Fiscal_Quarter", "Business_Unit", "Business_Unit_Descr",
    "Fund_Code", "Fund_Code_Descr", "Budget_Ref", "Budget_Ref_Descr",
    "Program_Code", "State_Function", "Primary_Account_Code",
    "Intermediate_Account_Code", "Detail_Account_Code", "Total",
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_sha256(value: Any) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8"))


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("source path escapes the supplied root")
    return path


def parse_legal_account(value: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9]{3}-[0-9]{2}-[0-9]{4}-[0-9]{4}", value):
        raise ValueError("legal account must have agency-subunit-fund-budget reference form")
    return dict(zip(("agency", "subunit", "fund", "budget_unit"), value.split("-")))


def inspect_year(corpus_root: Path, custody_root: Path | None,
                 legal_account: str, fiscal_year: int) -> dict[str, Any]:
    """Check one agency expenditure extract and return exact matching records.

    Budget-reference candidate matching uses the existing upstream kanview-1
    strip_budget_ref_leading_zeroes rule. Other codes retain their zeroes.
    The absent subunit is deliberately not filled from the legal reference.
    """
    legal = parse_legal_account(legal_account)
    if type(fiscal_year) is not int or not 2011 <= fiscal_year <= 2026:
        raise ValueError("this harvested corpus covers fiscal years 2011 through 2026")
    agency = legal["agency"]
    filename = f"ExpData_{agency}_{fiscal_year}.csv"
    manifests = sorted((corpus_root / "data/kanview").glob(f"manifest_FY{fiscal_year}_*.json"))
    if len(manifests) != 1:
        raise ValueError(f"FY{fiscal_year} requires exactly one harvest manifest; found {len(manifests)}")
    manifest_path = _inside(corpus_root, str(manifests[0].relative_to(corpus_root)))
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest.get("operation") != "kanview_harvest"
            or str(manifest.get("fiscal_year")) != str(fiscal_year)
            or manifest.get("source") != SOURCE_URL
            or manifest.get("output_dir") != f"data/kanview/FY{fiscal_year}"):
        raise ValueError("manifest is not the requested KanView agency/year harvest")
    entries = [entry for entry in manifest["entries"] if entry.get("filename") == filename]
    if len(entries) != 1:
        raise ValueError(f"{filename} requires exactly one manifest entry")
    entry = entries[0]
    request = entry.get("request", {})
    if (request.get("agency") != agency or request.get("type") != "Exp"
            or str(request.get("fiscal_year")) != str(fiscal_year)):
        raise ValueError("manifest request does not match the agency, year, and expenditure source")
    relative = f"data/kanview/FY{fiscal_year}/{filename}"
    content = _inside(corpus_root, relative).read_bytes()
    content_hash = sha256(content)
    if (content_hash != entry.get("checksum_sha256")
            or len(content) != entry.get("size_bytes")):
        raise ValueError(f"{filename} does not match its manifest hash/size")
    custody_verified = False
    if custody_root is not None:
        custody_path = _inside(custody_root, f"kanview/{content_hash[:2]}/{content_hash}")
        if sha256(custody_path.read_bytes()) != content_hash:
            raise ValueError(f"{filename} custody bytes do not match the source hash")
        custody_verified = True

    reader = csv.reader(io.StringIO(content.decode("utf-8-sig"), newline=""), strict=True)
    headers = next(reader)
    if (len(headers) != len(set(headers))
            or any(column not in headers for column in REQUIRED_COLUMNS)):
        raise ValueError("agency extract has missing or duplicate required headers")
    matches: list[dict[str, Any]] = []
    records_read = 0
    budget_ref = legal["budget_unit"].lstrip("0") or "0"
    for record_number, values in enumerate(reader, 1):
        line_end = reader.line_num
        if len(values) != len(headers):
            raise ValueError(f"CSV record {record_number} has an unexpected column count")
        raw = dict(zip(headers, values))
        row = {key: value.strip() for key, value in raw.items() if key}
        if row["Fiscal_Year"] != str(fiscal_year) or row["Business_Unit"] != agency:
            raise ValueError(f"CSV record {record_number} has the wrong agency or fiscal year")
        if row["Fiscal_Quarter"] not in {"1", "2", "3", "4"}:
            raise ValueError(f"CSV record {record_number} has an invalid fiscal quarter")
        records_read += 1
        if (row["Fund_Code"] != legal["fund"] or not row["Budget_Ref"]
                or (row["Budget_Ref"].lstrip("0") or "0") != budget_ref):
            continue
        matches.append({
            "locator": {"kind": "csv_record", "data_record_1based": record_number,
                        "header_records": 1, "physical_line_end_1based": line_end},
            "raw_record_sha256": json_sha256({"headers": headers, "values": values}),
            "raw_record": {"headers": headers, "values": values},
            "fields": row,
        })
    if records_read != entry.get("row_count"):
        raise ValueError(f"{filename} parsed record count differs from the manifest")
    return {
        "fiscal_year": fiscal_year,
        "source": {
            "relative_path": relative, "source_url": SOURCE_URL,
            "request": request, "retrieved_at": entry.get("retrieval_date"),
            "content_hash_sha256": content_hash, "byte_size": len(content),
            "manifest_relative_path": str(manifest_path.relative_to(corpus_root.resolve())),
            "manifest_sha256": sha256(manifest_bytes), "manifest_verified": True,
            "custody_bytes_verified": custody_verified,
        },
        "candidate_components": {"agency": agency, "subunit": None,
                                 "fund": legal["fund"], "budget_unit": budget_ref},
        "normalization": {"upstream_version": "kanview-1",
                          "budget_unit": "strip_budget_ref_leading_zeroes",
                          "other_codes": "preserve_trimmed_code"},
        "legal_account_match": "candidate_missing_subunit" if matches else "no_source_match",
        "publication_allowed": False,
        "source_records_read": records_read,
        "matched_records": len(matches),
        "observed_quarters": sorted({int(row["fields"]["Fiscal_Quarter"]) for row in matches}),
        "raw_budget_references": sorted({row["fields"]["Budget_Ref"] for row in matches}),
        "agency_descriptions": sorted({row["fields"]["Business_Unit_Descr"] for row in matches}),
        "fund_descriptions": sorted({row["fields"]["Fund_Code_Descr"] for row in matches}),
        "budget_descriptions": sorted({row["fields"]["Budget_Ref_Descr"] for row in matches}),
        "records": matches,
    }


def audit(corpus_root: Path, custody_root: Path | None, legal_account: str,
          fiscal_years: list[int]) -> dict[str, Any]:
    parse_legal_account(legal_account)
    if not fiscal_years or len(set(fiscal_years)) != len(fiscal_years):
        raise ValueError("provide distinct fiscal years")
    years = [inspect_year(corpus_root.resolve(), custody_root, legal_account, year)
             for year in sorted(fiscal_years)]
    return {
        "schema_version": SCHEMA_VERSION,
        "purpose": "real-source design and acceptance evidence; not a publishable graph",
        "legal_account": legal_account,
        "years": years,
        "evidence_sha256": json_sha256(years),
        "limitations": [
            "A matching agency/fund/budget reference is a candidate, not a reviewed legal crosswalk.",
            "KanView has no subunit column; no canonical IDs, SourceSpans or reviews are invented.",
            "CSV Total is a source expenditure observation, not enacted appropriation authority.",
            "Observed quarters do not certify complete fiscal-year coverage; no totals or growth rates are computed.",
            "Manifest and optional custody byte checks do not attest a current published ledger revision.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--custody-root", type=Path)
    parser.add_argument("--legal-account", required=True)
    parser.add_argument("--fiscal-years", nargs="+", type=int, required=True)
    args = parser.parse_args()
    try:
        result = audit(args.corpus_root, args.custody_root, args.legal_account, args.fiscal_years)
    except (ValueError, KeyError, OSError, csv.Error, StopIteration) as exc:
        parser.exit(2, f"Fiscal corpus audit failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
