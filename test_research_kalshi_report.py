import tempfile
import unittest
from pathlib import Path

from research_kalshi_report import export,make_rows


class ReportTests(unittest.TestCase):
    def test_export_preserves_quote_and_no_side(self):
        capture={"forecasts":{"target_date":"2026-11-10"},
                 "captured_at_utc":"2026-11-09T01:00:00Z",
                 "rows":[{"ticker":"ABC","contract_side":"no","status":"research_candidate",
                         "contract":{"market_type":"total","nhl_game_id":123},
                         "forecast":{"date":"2026-11-10","scheduled_start_utc":"2026-11-10T20:00:00Z",
                                     "home_team":"BOS","away_team":"NYR",
                                     "generated_at_utc":"2026-11-09T01:00:00Z"},
                         "quote":{"observed_at_utc":"2026-11-09T02:00:00Z"},
                         "model_probability":.65,"market_probability":.62,
                         "ask_cents":30,"fee_cents_per_contract":1.5,
                         "breakeven_probability":.315,"expected_profit_usd":.335,
                         "expected_roi":1.063,"quote_quantity":17,"paper_selected":True}]}
        with tempfile.TemporaryDirectory() as directory:
            csv_path=Path(directory)/"test.csv"
            md_path=Path(directory)/"test.md"
            counts=export(capture,csv_path,md_path)
            self.assertEqual(counts["positive_ev"],1)
            self.assertIn("ABC",csv_path.read_text())
            self.assertIn("NO",md_path.read_text())
            self.assertIn("0.3350",md_path.read_text())


if __name__=="__main__":
    unittest.main()
