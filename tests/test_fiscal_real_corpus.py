"""Opt-in regressions over retained real KanView sources, never invented rows.

Set SVS_FISCAL_CORPUS_ROOT and SVS_FISCAL_CUSTODY_ROOT to read-only mounts.
The default suite cannot claim this real-data proof when those are absent.
"""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/release/kansas-fiscal-corpus-audit.py"
spec = importlib.util.spec_from_file_location("fiscal_corpus_audit", MODULE_PATH)
assert spec and spec.loader
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)
CORPUS = os.environ.get("SVS_FISCAL_CORPUS_ROOT")
CUSTODY = os.environ.get("SVS_FISCAL_CUSTODY_ROOT")
ACCOUNT = "652-00-1000-0840"


@unittest.skipUnless(CORPUS and CUSTODY, "requires the retained real KanView corpus and custody bytes")
class RealKanViewEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(CORPUS)
        cls.custody = Path(CUSTODY)
        cls.result = audit_module.audit(cls.root, cls.custody, ACCOUNT, list(range(2011, 2027)))
        cls.years = {entry["fiscal_year"]: entry for entry in cls.result["years"]}

    def test_all_sixteen_real_sources_match_manifests_and_custody(self):
        self.assertEqual(len(self.years), 16)
        for year in self.years.values():
            self.assertTrue(year["source"]["manifest_verified"])
            self.assertTrue(year["source"]["custody_bytes_verified"])
            self.assertGreater(year["source_records_read"], 0)

    def test_pinned_real_2025_2026_sources_preserve_padding_and_quarters(self):
        self.assertEqual(self.years[2025]["source"]["content_hash_sha256"],
                         "6a96fc93c1721fe66479aadc988b53575648df7b24065d5b3674e86fe1234949")
        self.assertEqual(self.years[2026]["source"]["content_hash_sha256"],
                         "ea386136d6135334aa71f84331ec8ab68b2d5c83d9b992efe72b41e1a569eaed")
        self.assertEqual(self.years[2025]["raw_budget_references"], ["0840"])
        self.assertEqual(self.years[2026]["raw_budget_references"], ["840"])
        self.assertEqual(self.years[2026]["observed_quarters"], [1, 4])
        self.assertEqual(self.years[2026]["agency_descriptions"], ["Department of Education"])
        self.assertEqual(self.years[2026]["fund_descriptions"], ["STATE GENERAL FUND"])
        self.assertEqual(self.years[2026]["budget_descriptions"], ["SUPPLEMENTAL GENERAL STATE AID"])

    def test_real_2016_gap_is_not_zero_or_a_published_join(self):
        year = self.years[2016]
        self.assertEqual(year["matched_records"], 0)
        self.assertEqual(year["legal_account_match"], "no_source_match")
        self.assertFalse(year["publication_allowed"])
        self.assertEqual(year["records"], [])
        self.assertNotIn("total", year)

    def test_a_different_legal_subunit_does_not_become_a_verified_match(self):
        for account in (ACCOUNT, "652-01-1000-0840"):
            year = audit_module.inspect_year(self.root, self.custody, account, 2026)
            self.assertIsNone(year["candidate_components"]["subunit"])
            self.assertEqual(year["legal_account_match"], "candidate_missing_subunit")
            self.assertFalse(year["publication_allowed"])

    def test_each_real_record_locator_and_hash_round_trips_to_source(self):
        year = self.years[2026]
        with (self.root / year["source"]["relative_path"]).open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle)
            headers = next(reader)
            rows = {number: values for number, values in enumerate(reader, 1)}
        self.assertEqual([record["locator"]["data_record_1based"] for record in year["records"]], [384, 2671])
        for record in year["records"]:
            original = {"headers": headers, "values": rows[record["locator"]["data_record_1based"]]}
            self.assertEqual(record["raw_record"], original)
            self.assertEqual(record["raw_record_sha256"], audit_module.json_sha256(original))

    def test_real_source_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.years[2026]["source"]
            for relative in (source["relative_path"], source["manifest_relative_path"]):
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root / relative, target)
            with (root / source["relative_path"]).open("ab") as handle:
                handle.write(b" ")
            with self.assertRaisesRegex(ValueError, "manifest hash/size"):
                audit_module.inspect_year(root, None, ACCOUNT, 2026)

    def test_real_manifest_with_wrong_agency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            relative = self.years[2026]["source"]["manifest_relative_path"]
            target = root / relative
            target.parent.mkdir(parents=True)
            manifest = json.loads((self.root / relative).read_text())
            next(entry for entry in manifest["entries"] if entry["filename"] == "ExpData_652_2026.csv")["request"]["agency"] = "016"
            target.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "manifest request"):
                audit_module.inspect_year(root, None, ACCOUNT, 2026)

    def test_replay_is_deterministic(self):
        replay = audit_module.audit(self.root, self.custody, ACCOUNT, list(reversed(range(2011, 2027))))
        self.assertEqual(replay, self.result)


if __name__ == "__main__":
    unittest.main()
