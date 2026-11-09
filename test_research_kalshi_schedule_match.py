import unittest
from research_kalshi_schedule_match import pair_candidates,reconcile
class ScheduleMatcherTests(unittest.TestCase):
    def test_aliases(self):
        self.assertIn(frozenset(("NYI","ANA")),pair_candidates("NYIANA"))
        self.assertIn(frozenset(("NJD","TOR")),pair_candidates("NJTOR"))
        self.assertIn(frozenset(("NSH","LAK")),pair_candidates("NSHLA"))
        self.assertIn(frozenset(("TBL","WPG")),pair_candidates("TBWPG"))
    def test_unique_match(self):
        m={"ticker":"KXNHLGAME-26NOV14NYIANA-NYI","event_ticker":"KXNHLGAME-26NOV14NYIANA"}
        schedule={"games":[{"id":2026020234,"gameDate":"2026-11-14","gameType":2,
                            "homeTeam":{"abbrev":"ANA"},"awayTeam":{"abbrev":"NYI"}}]}
        result=reconcile(m,schedule)
        self.assertEqual(result["status"],"game_matched")
        self.assertEqual(result["nhl_game_id"],2026020234)
    def test_no_match_never_guessed(self):
        m={"ticker":"KXNHLGAME-26NOV14NYIANA-NYI","event_ticker":"KXNHLGAME-26NOV14NYIANA"}
        result=reconcile(m,{"games":[]})
        self.assertEqual(result["status"],"unmatched")
        self.assertIsNone(result["nhl_game_id"])
    def test_wrong_date_rejected(self):
        m={"ticker":"KXNHLGAME-26NOV14NYIANA-NYI","event_ticker":"KXNHLGAME-26NOV14NYIANA"}
        schedule={"games":[{"id":123,"gameDate":"2026-11-15","gameType":2,
                            "homeTeam":{"abbrev":"ANA"},"awayTeam":{"abbrev":"NYI"}}]}
        self.assertEqual(reconcile(m,schedule)["status"],"unmatched")
    def test_duplicate_match_rejected(self):
        m={"ticker":"KXNHLGAME-26NOV14NYIANA-NYI","event_ticker":"KXNHLGAME-26NOV14NYIANA"}
        g={"id":123,"gameDate":"2026-11-14","gameType":2,
           "homeTeam":{"abbrev":"ANA"},"awayTeam":{"abbrev":"NYI"}}
        self.assertEqual(reconcile(m,{"games":[g,dict(g,id=124)]})["status"],"unmatched")
if __name__=="__main__":unittest.main()
