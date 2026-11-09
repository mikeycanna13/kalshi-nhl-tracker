import unittest
from research_kalshi_contract_match import parse
class TestContracts(unittest.TestCase):
    def test_moneyline(self):
        x=parse({"ticker":"KXNHLGAME-26NOV14NYIANA-NYI","event_ticker":"KXNHLGAME-26NOV14NYIANA"})
        self.assertEqual(x["original_date"],"2026-11-14")
        self.assertEqual(x["market_type"],"moneyline")
        self.assertIsNone(x["nhl_game_id"])
    def test_total(self):
        x=parse({"ticker":"KXNHLTOTAL-26NOV10NSHLA-9","event_ticker":"KXNHLTOTAL-26NOV10NSHLA","strike_type":"greater","floor_strike":8.5})
        self.assertEqual(x["threshold"],8.5)
    def test_player_requires_id(self):
        x=parse({"ticker":"KXNHLPTS-26NOV08TBWPG-WPGNPIONK4-2","event_ticker":"KXNHLPTS-26NOV08TBWPG","strike_type":"greater","floor_strike":1.5})
        self.assertEqual(x["status"],"unmatched")
    def test_player_id(self):
        x=parse({"ticker":"KXNHLGOAL-26NOV08NJTOR-NJBDILLON5-1","event_ticker":"KXNHLGOAL-26NOV08NJTOR","strike_type":"greater","floor_strike":0.5,"custom_strike":{"hockey_player":"verified-uuid"}})
        self.assertEqual(x["market_type"],"player_goals")
    def test_reject_bad_date(self):
        x=parse({"ticker":"KXNHLGAME-26FEB30NYIANA-NYI","event_ticker":"KXNHLGAME-26FEB30NYIANA"})
        self.assertEqual(x["status"],"unmatched")
if __name__=="__main__":unittest.main()
