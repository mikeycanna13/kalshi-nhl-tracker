"""Offline tests for append-only NHL forward evidence storage."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase

from research_forward_ledger import make_archive,write_archive,load_archives,report

class LedgerTests(TestCase):
    def setUp(self):
        self.forecast={"game_id":123,"date":"2026-11-10",
                       "generated_at_utc":"2026-11-08T20:00:00Z",
                       "scheduled_start_utc":"2026-11-10T20:00:00Z"}
        self.selection={"ticker":"TEST","contract_side":"yes","paper_selected":True,
                        "status":"research_candidate","expected_profit_usd":.05}
        self.capture={
            "captured_at_utc":"2026-11-08T21:00:00Z",
            "forecasts":{"target_date":"2026-11-10","forecasts":[self.forecast]},
            "rows":[self.selection,{"status":"skipped"}]}
        self.audit={"overall_status":"conditional",
                    "forecast_status_counts":{"operational_pregame_only":1},
                    "quote_status_counts":{"conditional":1,"not_scored":1},
                    "forecasts":[{"game_id":123,"status":"operational_pregame_only"}]}
        self.benchmark={"status":"no_paired_benchmark","paired_games":0,
                        "comparison_count":1}
    def save_inputs(self,root):
        for name,data in [("capture",self.capture),("audit",self.audit),("bench",self.benchmark)]:
            (root/(name+".json")).write_text(json.dumps(data))
        return [root/(x+".json") for x in ("capture","audit","bench")]
    def test_archive_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs=self.save_inputs(root)
            path=write_archive(*inputs,"4242",root/"archive")
            self.assertEqual(path.name,"4242.json")
            self.assertEqual(len(load_archives(root/"archive")),1)
            summary=report(root/"archive")
            self.assertEqual(summary["primary_target_dates"],1)
            self.assertEqual(summary["primary_selected_positions"],1)
            self.assertEqual(summary["primary_sportsbook_paired_games"],0)
            self.assertIsNone(summary["realized_paper_pnl"])
    def test_rearchive_fails_instead_of_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs=self.save_inputs(root)
            write_archive(*inputs,"4242",root/"archive")
            with self.assertRaises(FileExistsError):
                write_archive(*inputs,"4242",root/"archive")
    def test_checksum_detects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs=self.save_inputs(root)
            path=write_archive(*inputs,"4242",root/"archive")
            data=json.loads(path.read_text())
            data["capture"]["rows"][0]["expected_profit_usd"]=999
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                load_archives(root/"archive")
    def test_one_primary_capture_per_target_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inputs=self.save_inputs(root)
            write_archive(*inputs,"4242",root/"archive")
            self.capture["captured_at_utc"]="2026-11-08T22:00:00Z"
            self.save_inputs(root)
            write_archive(*inputs,"4243",root/"archive")
            summary=report(root/"archive")
            self.assertEqual(summary["archived_snapshots"],2)
            self.assertEqual(summary["primary_target_dates"],1)
            self.assertEqual(summary["primary_run_ids"],["4242"])
    def test_reject_bad_audit(self):
        self.audit["overall_status"]="invalid"
        with self.assertRaises(ValueError):
            make_archive(self.capture,self.audit,self.benchmark,"1")
    def test_reject_no_early_prediction(self):
        self.forecast["generated_at_utc"]="2026-11-08T22:00:00Z"
        with self.assertRaises(ValueError):
            make_archive(self.capture,self.audit,self.benchmark,"1")
    def test_reject_non_numeric_run_id(self):
        with self.assertRaises(ValueError):
            make_archive(self.capture,self.audit,self.benchmark,"../../../branch")
    def test_reject_missing_benchmark(self):
        with self.assertRaises(ValueError):
            make_archive(self.capture,self.audit,{},"1")
    def test_reject_audit_faking_status(self):
        self.audit["forecasts"][0]["status"]="invalid"
        with self.assertRaises(ValueError):
            make_archive(self.capture,self.audit,self.benchmark,"1")

if __name__=="__main__":
    import unittest
    unittest.main()
