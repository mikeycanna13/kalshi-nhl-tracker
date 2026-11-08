"""Offline synthetic tests: no live downloads or Railway restarts."""
import unittest
import pandas as pd
from advanced_stats import pregame_advanced_features

def game(game_id,date,home_xg,away_xg):
    return [
        dict(gameId=game_id,gameDate=date,teamCode="NYR",opposingTeam="NJD",
             xGoal=home_xg,goalieIdForShot="away_goalie",isGoal=0,
             homeTeamCode="NYR",awayTeamCode="NJD",homeSkatersOnIce=5,awaySkatersOnIce=5),
        dict(gameId=game_id,gameDate=date,teamCode="NJD",opposingTeam="NYR",
             xGoal=away_xg,goalieIdForShot="home_goalie",isGoal=1,
             homeTeamCode="NYR",awayTeamCode="NJD",homeSkatersOnIce=5,awaySkatersOnIce=5)
    ]

class AdvancedStatsTests(unittest.TestCase):
    def test_future_games_do_not_change_past_features(self):
        first=pd.DataFrame(game(1,"2025-10-01",.1,.2))
        later=pd.DataFrame(game(2,"2025-10-02",.9,.8))
        a,_=pregame_advanced_features(first)
        b,goalies=pregame_advanced_features(pd.concat([first,later],ignore_index=True))
        pd.testing.assert_series_equal(a.iloc[0],b.iloc[0],check_names=False)
        self.assertEqual(int(b.iloc[1].home_advanced_games),1)
        self.assertEqual(len(goalies),2)

    def test_same_day_games_cannot_leak(self):
        data=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-01",.9,.8))
        features,_=pregame_advanced_features(data)
        self.assertTrue((features.home_advanced_games==0).all())

    def test_invalid_probabilities_rejected(self):
        data=pd.DataFrame(game(1,"2025-10-01",1.5,.2))
        with self.assertRaises(ValueError):
            pregame_advanced_features(data)

if __name__=="__main__":
    unittest.main()
