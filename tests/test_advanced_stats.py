"""Offline synthetic tests: no live downloads or Railway restarts."""
import unittest
import pandas as pd
from advanced_stats import pregame_advanced_features, normalize

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

    def test_special_teams_from_team_perspective(self):
        # NYR has PP, NJD has PK; the next day's pregame features must
        # attribute the NYR PP chance to NJD PK xGA, not NJD PP xGA.
        first=game(1,"2025-10-01",.7,.1)
        first[0]["homeSkatersOnIce"]=5
        first[0]["awaySkatersOnIce"]=4
        first[1]["homeSkatersOnIce"]=5
        first[1]["awaySkatersOnIce"]=4
        later=game(2,"2025-10-02",.2,.3)
        features,_=pregame_advanced_features(pd.DataFrame(first+later))
        row=features.loc[features.game_id==2].iloc[0]
        # Shrinkage prior 3.0, historical one-game xG contribution .7.
        self.assertAlmostEqual(row.away_penalty_kill_xg_against_pg,(3.0+.7)/4)
        self.assertAlmostEqual(row.away_power_play_xg_against_pg,3.0/4)
        self.assertAlmostEqual(row.home_power_play_xg_for_pg,(3.0+.7)/4)

    def test_4v4_and_3v3_are_not_5v5(self):
        first=game(1,"2025-10-01",.7,.1)
        first[0]["homeSkatersOnIce"]=4
        first[0]["awaySkatersOnIce"]=4
        first[1]["homeSkatersOnIce"]=3
        first[1]["awaySkatersOnIce"]=3
        later=game(2,"2025-10-02",.2,.3)
        features,_=pregame_advanced_features(pd.DataFrame(first+later))
        row=features.loc[features.game_id==2].iloc[0]
        self.assertAlmostEqual(row.home_even_xg_for_pg,3.0/4)
        self.assertAlmostEqual(row.home_even_xg_against_pg,3.0/4)

    def test_official_moneypuck_home_away_schema_and_schedule(self):
        shots=pd.DataFrame([
            dict(game_id=2025020001,team="HOME",homeTeamCode="NYR",awayTeamCode="NJD",
                 xGoal=.2,goal=0,goalieIdForShot="away_goalie",
                 homeSkatersOnIce=5,awaySkatersOnIce=5),
            dict(game_id=2025020001,team="AWAY",homeTeamCode="NYR",awayTeamCode="NJD",
                 xGoal=.3,goal=1,goalieIdForShot="home_goalie",
                 homeSkatersOnIce=5,awaySkatersOnIce=5)])
        schedule=pd.DataFrame([dict(game_id=2025020001,date="2025-10-07")])
        normalized=normalize(shots,game_dates=schedule)
        self.assertEqual(normalized.team.tolist(),["NYR","NJD"])
        self.assertEqual(normalized.opponent.tolist(),["NJD","NYR"])
        self.assertEqual(str(normalized.date.iloc[0].date()),"2025-10-07")
        with self.assertRaises(ValueError):
            normalize(shots)

    def test_invalid_probabilities_rejected(self):
        data=pd.DataFrame(game(1,"2025-10-01",1.5,.2))
        with self.assertRaises(ValueError):
            pregame_advanced_features(data)

if __name__=="__main__":
    unittest.main()
