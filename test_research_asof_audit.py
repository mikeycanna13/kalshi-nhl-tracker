import copy
import unittest
from research_asof_audit import audit_forecast,audit_quote,audit_capture

class PointInTimeAuditTests(unittest.TestCase):
    def setUp(self):
        self.f={"game_id":123,"date":"2026-11-10",
                "last_training_game_date":"2026-11-08",
                "scheduled_start_utc":"2026-11-10T00:00:00Z",
                "generated_at_utc":"2026-11-08T21:00:00Z",
                "model_trained_through_utc":"2026-11-08T21:00:00Z",
                "training_source_loaded_at_utc":"2026-11-08T20:55:00Z",
                "training_source_sha256":"a"*64,
                "training_source_type":"nhl_completed_game_scores",
                "model_code_commit":"example","pregame_verified":True}
        self.row={"status":"research_candidate","forecast":self.f,
                  "fee_schedule":{"fee_type":"quadratic","fee_multiplier":1},
                  "quote":{"snapshot_kind":"live_orderbook",
                           "observed_at_utc":"2026-11-08T21:05:00Z"}}
    def test_operational_not_historical(self):
        result=audit_forecast(self.f)
        self.assertEqual(result["status"],"operational_pregame_only")
        self.assertFalse(result["historical_replay_verified"])
    def test_same_day_training_invalid(self):
        self.f["last_training_game_date"]="2026-11-10"
        self.assertEqual(audit_forecast(self.f)["status"],"invalid")
    def test_no_source_hash_invalid(self):
        self.f.pop("training_source_sha256")
        self.assertEqual(audit_forecast(self.f)["status"],"invalid")
    def test_source_loaded_after_forecast_invalid(self):
        self.f["training_source_loaded_at_utc"]="2026-11-08T21:01:00Z"
        self.assertEqual(audit_forecast(self.f)["status"],"invalid")
    def test_forged_pregame_flag_invalid(self):
        self.f["pregame_verified"]=False
        self.assertEqual(audit_forecast(self.f)["status"],"invalid")
    def test_postgame_quote_invalid(self):
        self.row["quote"]["observed_at_utc"]="2026-11-10T00:00:00Z"
        self.assertEqual(audit_quote(self.row)["status"],"invalid")
    def test_live_quote_conditional_not_fill(self):
        result=audit_quote(self.row)
        self.assertEqual(result["status"],"conditional")
        self.assertIn("unverified",result["reason"])
    def test_non_candidate_not_counted_as_invalid(self):
        self.row["status"]="skipped"
        self.assertEqual(audit_quote(self.row)["status"],"not_scored")
    def test_audit_full_capture(self):
        result=audit_capture({"forecasts":{"forecasts":[self.f]},
                              "rows":[self.row,{"status":"skipped"}]})
        self.assertEqual(result["overall_status"],"conditional")
        self.assertFalse(result["historical_backtest_point_in_time_verified"])
        self.assertEqual(result["forecast_status_counts"]["operational_pregame_only"],1)
    def test_invalid_capture_is_fail_closed(self):
        bad=copy.deepcopy(self.row)
        bad["quote"]["observed_at_utc"]="2026-11-11T01:00:00Z"
        result=audit_capture({"forecasts":{"forecasts":[self.f]},"rows":[bad]})
        self.assertEqual(result["overall_status"],"invalid")

if __name__=="__main__":
    unittest.main()
