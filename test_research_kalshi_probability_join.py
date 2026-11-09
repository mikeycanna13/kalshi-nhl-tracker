import unittest
from research_kalshi_probability_join import join_quote
class JoinTests(unittest.TestCase):
    def setUp(self):
        self.c={"status":"game_matched","nhl_game_id":123,"ticker":"TICKER",
                "market_type":"total","threshold":5.5,
                "rules_primary":"If the teams collectively score more than 5.5 goals, Yes."}
        self.q={"ticker":"TICKER","snapshot_kind":"live_orderbook",
                "observed_at_utc":"2026-11-09T20:00:00Z","yes_ask_implied_cents":40,
                "no_bid_qty":10}
        self.f={"game_id":123,"generated_at_utc":"2026-11-09T19:00:00Z",
                "pregame_verified":True,"p_over_5_5":0.6}
    def test_positive_ev(self):
        x=join_quote(self.c,self.q,self.f,fee_cents=2)
        self.assertEqual(x["status"],"research_candidate")
        self.assertAlmostEqual(x["expected_profit_usd"],0.18)
    def test_future_forecast_rejected(self):
        self.f["generated_at_utc"]="2026-11-09T21:00:00Z"
        self.assertEqual(join_quote(self.c,self.q,self.f,2)["status"],"skipped")
    def test_fee_required(self):
        self.assertEqual(join_quote(self.c,self.q,self.f)["status"],"skipped")
    def test_no_player_model(self):
        self.c["market_type"]="player_points"
        self.assertEqual(join_quote(self.c,self.q,self.f,2)["status"],"skipped")
    def test_no_unmatched_game(self):
        self.c["status"]="parsed_unverified"
        self.assertEqual(join_quote(self.c,self.q,self.f,2)["status"],"skipped")
    def test_no_liquidity(self):
        self.q["no_bid_qty"]=0
        self.assertEqual(join_quote(self.c,self.q,self.f,2)["status"],"skipped")
if __name__=="__main__":unittest.main()
