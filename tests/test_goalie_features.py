"""Goalie snapshot leakage and starter projection tests."""
import unittest
import pandas as pd
from goalie_features import goalie_snapshots, attach_projected_goalies
from test_advanced_stats import game

class GoalieTests(unittest.TestCase):
    def test_snapshot_excludes_same_day(self):
        raw=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-02",.9,.8))
        snapshots=goalie_snapshots(raw)
        self.assertFalse((snapshots.snapshot_date=="2025-10-01").any())
        next_day=snapshots[snapshots.snapshot_date=="2025-10-02"]
        self.assertEqual(len(next_day),2)
        self.assertTrue((next_day.prior_games==1).all())
        self.assertAlmostEqual(
            next_day.loc[next_day.goalie_id=="home_goalie","prior_xga"].iloc[0],.2)

    def test_probabilistic_starter_join(self):
        raw=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-02",.9,.8))
        snapshots=goalie_snapshots(raw)
        projections=pd.DataFrame([
            dict(game_id=2,prediction_date="2025-10-02",goalie_id="home_goalie",probability=.6),
            dict(game_id=2,prediction_date="2025-10-02",goalie_id="away_goalie",probability=.4)])
        games=pd.DataFrame([dict(game_id=2,date="2025-10-02")])
        result=attach_projected_goalies(games,projections,snapshots)
        self.assertEqual(len(result),1)
        self.assertTrue(pd.notna(result.weighted_gsax.iloc[0]))

    def test_unknown_goalie_uses_neutral_prior(self):
        raw=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-02",.9,.8))
        projections=pd.DataFrame([
            dict(game_id=2,prediction_date="2025-10-02",goalie_id="rookie",probability=.75),
            dict(game_id=2,prediction_date="2025-10-02",goalie_id="home_goalie",probability=.25)])
        result=attach_projected_goalies(
            pd.DataFrame([dict(game_id=2,date="2025-10-02")]),
            projections,goalie_snapshots(raw))
        self.assertAlmostEqual(result.unknown_starter_probability.iloc[0],.75)

    def test_rejects_projection_after_game(self):
        raw=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-02",.9,.8))
        projections=pd.DataFrame([dict(game_id=2,prediction_date="2025-10-03",
                                       goalie_id="home_goalie",probability=1.)])
        with self.assertRaises(ValueError):
            attach_projected_goalies(
                pd.DataFrame([dict(game_id=2,date="2025-10-02")]),
                projections,goalie_snapshots(raw))

    def test_rejects_probabilities_not_summing_to_one(self):
        raw=pd.DataFrame(game(1,"2025-10-01",.1,.2)+game(2,"2025-10-02",.9,.8))
        projections=pd.DataFrame([dict(game_id=2,prediction_date="2025-10-02",
                                       goalie_id="home_goalie",probability=.6)])
        with self.assertRaises(ValueError):
            attach_projected_goalies(pd.DataFrame([dict(game_id=2,date="2025-10-02")]),
                                     projections,goalie_snapshots(raw))

if __name__=="__main__":
    unittest.main()
