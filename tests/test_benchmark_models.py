"""Smoke tests for walk-forward NHL benchmarks; no network or historical downloads."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import benchmark_models

class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(123)
        rows=[]
        for season in ("20212022","20222023","20232024","20242025"):
            for i in range(40):
                row={name:float(rng.normal()) for name in set(sum(benchmark_models.MODELS.values(),[]))}
                row.update(season=season,game_id=int(season[:4])*1000+i,
                           date=f"{season[:4]}-11-{i%28+1:02d}",
                           home_win=i%2,over_5_5=(i//2)%2,over_6_5=(i//3)%2,
                           poisson_home=.53,poisson_over55=.48,poisson_over65=.36)
                rows.append(row)
        self.df=pd.DataFrame(rows)

    def test_walk_forward_season_boundaries_and_metrics(self):
        with patch.object(benchmark_models,"build_features",return_value=self.df):
            report=benchmark_models.benchmark(pd.DataFrame())
        self.assertEqual(len(report["folds"]),2)
        self.assertEqual([x["season"] for x in report["folds"]],["20232024","20242025"])
        self.assertEqual([x["training_games"] for x in report["folds"]],[80,120])
        for fold in report["folds"]:
            for market in benchmark_models.MARKETS:
                for name, metrics in fold["markets"][market].items():
                    self.assertGreaterEqual(metrics["brier"],0,name)
                    self.assertLessEqual(metrics["brier"],1,name)
                    self.assertTrue(np.isfinite(metrics["log_loss"]),name)
                    self.assertGreaterEqual(metrics["winner_accuracy"],0,name)
                    self.assertLessEqual(metrics["winner_accuracy"],1,name)

    def test_requires_three_seasons(self):
        with patch.object(benchmark_models,"build_features",return_value=self.df[self.df.season<"20232024"]):
            with self.assertRaises(ValueError):
                benchmark_models.benchmark(pd.DataFrame())

if __name__=="__main__":
    unittest.main()
