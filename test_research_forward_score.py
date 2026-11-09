"""Offline forward scoring tests: synthetic prices and outcomes only."""
import unittest
from research_forward_score import compute,primary_archives,outcome_cache

class ForwardScoreTests(unittest.TestCase):
    def make_archive(self,run_id="2",captured="2026-11-08T21:00:00Z"):
        forecast={"game_id":123,"home_team":"NYR","away_team":"BOS",
                  "contract_selection_team":"NYR","p_home_win":.6}
        contract={"market_type":"moneyline","nhl_game_id":123,
                  "home_team":"NYR","away_team":"BOS"}
        base={"ticker":"WIN","status":"research_candidate","contract":contract,
              "forecast":forecast,"model_probability":.6,
              "market_probability":.57,
              "ask_cents":55,"fee_cents_per_contract":2,"paper_selected":False}
        yes=dict(base,contract_side="yes",paper_selected=True)
        no=dict(base,contract_side="no",model_probability=.4,
                paper_selected=False,market_probability=.43)
        return {"target_date":"2026-11-10","source_run_id":run_id,
                "captured_at_utc":captured,"capture":{"rows":[yes,no]}}
    def test_no_settlement_is_not_zero_profit(self):
        result=compute([self.make_archive()],{"WIN":{"status":"active","result":None}})
        self.assertEqual(result["status"],"no_settled_paper_positions")
        self.assertIsNone(result["paper_profit_usd"])
        self.assertEqual(result["calibration"]["moneyline"]["n"],0)
    def test_yes_settles_correctly_and_no_double_calibration(self):
        result=compute([self.make_archive()],
                       {"WIN":{"status":"finalized","result":"yes"}})
        self.assertEqual(result["paper_positions_settled"],1)
        self.assertAlmostEqual(result["paper_profit_usd"],.43)
        self.assertEqual(result["calibration"]["moneyline"]["n"],1)
        self.assertAlmostEqual(result["calibration"]["moneyline"]["model_brier"],.16)
    def test_no_side_settlement(self):
        archive=self.make_archive()
        archive["capture"]["rows"][0]["paper_selected"]=False
        archive["capture"]["rows"][1]["paper_selected"]=True
        archive["capture"]["rows"][1]["ask_cents"]=39
        result=compute([archive],{"WIN":{"status":"finalized","result":"no"}})
        self.assertEqual(result["paper_positions_settled"],1)
        self.assertAlmostEqual(result["paper_profit_usd"],.59)
        self.assertEqual(result["calibration"]["moneyline"]["n"],1)
    def test_one_primary_snapshot_per_target_date(self):
        a=self.make_archive("1","2026-11-08T20:00:00Z")
        b=self.make_archive("2","2026-11-08T21:00:00Z")
        selected=primary_archives([b,a])
        self.assertEqual(len(selected),1)
        self.assertEqual(selected[0]["source_run_id"],"1")
        outcome=compute([b,a],{"WIN":{"status":"finalized","result":"yes"}})
        self.assertEqual(outcome["paper_positions_settled"],1)
    def test_nonbinary_settlement_not_counted(self):
        r=compute([self.make_archive()],{"WIN":{"status":"finalized","result":"void"}})
        self.assertEqual(r["paper_positions_settled"],0)
        self.assertEqual(r["calibration"]["moneyline"]["n"],0)
    def test_fetches_one_ticker_even_with_two_sides(self):
        events=[]
        def fake_get(session,path):
            events.append(path)
            return {"market":{"status":"finalized","result":"yes"}}
        markets,_=outcome_cache([self.make_archive()],object(),provider=fake_get)
        self.assertEqual(events,["/markets/WIN"])
        self.assertEqual(markets["WIN"]["result"],"yes")

if __name__=="__main__":
    unittest.main()
