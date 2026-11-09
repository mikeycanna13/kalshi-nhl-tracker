"""Synthetic offline fixtures: no live or historical sportsbook prices are claimed."""
import copy
import unittest
from research_market_benchmark import (
    implied_probability, benchmark_game, compare_capture, score_settled, aware
)

class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.forecast={
            "game_id":2026020001,"home_team":"New York Rangers" if False else "NYR",
            "away_team":"BOS","p_home_win":0.60,
            "generated_at_utc":"2026-11-08T19:30:00Z",
            "scheduled_start_utc":"2026-11-10T00:00:00Z"}
        self.quote="2026-11-08T20:05:00Z"
        self.snapshot={
            "source":"the_odds_api_historical","timestamp":"2026-11-08T20:00:00Z",
            "data":[{
                "id":"synthetic_test_event","home_team":"New York Rangers",
                "away_team":"Boston Bruins","commence_time":"2026-11-10T00:00:00Z",
                "bookmakers":[self.book("book_a",1.90,1.95),
                              self.book("book_b",1.91,1.94),
                              self.book("book_c",1.89,1.96)]}]}
    def book(self,key,h,a,updated="2026-11-08T19:59:00Z"):
        return {"key":key,"last_update":updated,
                "markets":[{"key":"h2h","last_update":updated,
                            "outcomes":[{"name":"New York Rangers","price":h},
                                        {"name":"Boston Bruins","price":a}]}]}
    def test_happy_path_and_devig(self):
        result=benchmark_game(self.forecast,self.quote,self.snapshot)
        self.assertEqual(result["status"],"paired")
        self.assertEqual(result["bookmaker_count"],3)
        self.assertLess(result["sportsbook_fair_home_probability"],0.52)
        self.assertGreater(result["model_minus_consensus"],0.08)
    def test_prohibits_future_snapshot(self):
        self.snapshot["timestamp"]="2026-11-08T20:06:00Z"
        result=benchmark_game(self.forecast,self.quote,self.snapshot)
        self.assertEqual(result["status"],"unavailable")
        self.assertIn("future",result["reason"])
    def test_prohibits_model_generated_after_market(self):
        self.forecast["generated_at_utc"]="2026-11-08T20:01:00Z"
        self.assertEqual(benchmark_game(self.forecast,self.quote,self.snapshot)["status"],"unavailable")
    def test_prohibits_postgame(self):
        self.quote="2026-11-10T00:00:00Z"
        self.assertEqual(benchmark_game(self.forecast,self.quote,self.snapshot)["status"],"unavailable")
    def test_stale_snapshot(self):
        self.quote="2026-11-08T20:25:00Z"
        self.assertIn("stale",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_stale_bookmakers(self):
        for b in self.snapshot["data"][0]["bookmakers"]:
            b["last_update"]="2026-11-08T19:00:00Z"
            b["markets"][0]["last_update"]="2026-11-08T19:00:00Z"
        self.assertIn("insufficient",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_future_book_update_cannot_be_used(self):
        for b in self.snapshot["data"][0]["bookmakers"]:
            b["markets"][0]["last_update"]="2026-11-08T20:01:00Z"
        self.assertEqual(benchmark_game(self.forecast,self.quote,self.snapshot)["status"],"unavailable")
    def test_unverified_event_is_not_matched(self):
        self.snapshot["data"][0]["away_team"]="Montreal Canadiens"
        self.assertIn("unique NHL event",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_ambiguous_event_ids_are_not_matched(self):
        self.snapshot["data"].append(copy.deepcopy(self.snapshot["data"][0]))
        self.assertIn("unique NHL event",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_3way_draw_is_rejected(self):
        for b in self.snapshot["data"][0]["bookmakers"]:
            b["markets"][0]["outcomes"].append({"name":"Draw","price":3.1})
        self.assertIn("insufficient",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_unknown_source_is_not_accepted(self):
        self.snapshot["source"]="random_web_page"
        self.assertIn("provenance",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_insufficient_independent_books(self):
        self.snapshot["data"][0]["bookmakers"][1]["key"]="book_a"
        self.snapshot["data"][0]["bookmakers"][2]["key"]="book_a"
        self.assertIn("insufficient",benchmark_game(self.forecast,self.quote,self.snapshot)["reason"])
    def test_invalid_price_and_timezone(self):
        self.assertAlmostEqual(implied_probability(2.0),0.5)
        with self.assertRaises(ValueError):implied_probability(0)
        with self.assertRaises(ValueError):aware("2026-11-08T20:00:00")
    def test_compare_capture_deduplicates_market_sides(self):
        capture={"rows":[
            {"contract":{"market_type":"moneyline"},
             "forecast":self.forecast,"quote":{"observed_at_utc":self.quote}},
            {"contract":{"market_type":"moneyline"},
             "forecast":self.forecast,"quote":{"observed_at_utc":"2026-11-08T20:07:00Z"}}]}
        summary=compare_capture(capture,self.snapshot)
        self.assertEqual(summary["comparison_count"],1)
        self.assertEqual(summary["paired_games"],1)
    def test_score_requires_verified_final(self):
        report={"comparisons":[benchmark_game(self.forecast,self.quote,self.snapshot)]}
        self.assertEqual(score_settled(report,[])["status"],"not_evaluable")
        settled=score_settled(report,[{"game_id":2026020001,"status":"final","winner":"NYR"}])
        self.assertEqual(settled["status"],"scored")
        self.assertEqual(settled["settled_games"],1)
        self.assertAlmostEqual(settled["model_brier"],0.16)

if __name__=="__main__":
    unittest.main()
