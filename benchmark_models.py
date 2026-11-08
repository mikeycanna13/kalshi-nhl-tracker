"""Independent NHL model benchmark. Run: python benchmark_models.py --games data/games.csv
Only historical pregame features. No betting odds are training inputs.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from improved_model import build_features, FEATURES, score

MODELS = {
    "elo_only": ["elo_diff"],
    "elo_rest_form": ["elo_diff", "home_form", "away_form", "rest_diff", "home_rest", "away_rest"],
    "puckcast_style_logistic": FEATURES,
}
MARKETS = {
    "moneyline": ("home_win", "poisson_home"),
    "over_5_5": ("over_5_5", "poisson_over55"),
    "over_6_5": ("over_6_5", "poisson_over65"),
}

def benchmark(games):
    df = build_features(games)
    seasons = sorted(df.season.unique())
    if len(seasons) < 3:
        raise ValueError("At least three seasons are required for walk-forward validation")
    folds = []
    for season in seasons[2:]:
        train, test = df[df.season < season], df[df.season == season]
        if train.empty or test.empty:
            continue
        markets = {}
        for market, (target, poisson_col) in MARKETS.items():
            ytrain, ytest = train[target].to_numpy(int), test[target].to_numpy(int)
            predictions = {
                "training_prevalence": np.full(len(test), ytrain.mean()),
                "poisson_baseline": test[poisson_col].to_numpy(float),
            }
            if market == "moneyline":
                predictions["home_team_constant_pick"] = np.full(len(test), .54)
            for name, columns in MODELS.items():
                model = make_pipeline(
                    StandardScaler(),
                    LogisticRegression(C=.02, max_iter=1500)
                )
                model.fit(train[columns].to_numpy(float), ytrain)
                predictions[name] = model.predict_proba(test[columns].to_numpy(float))[:, 1]
            markets[market] = {
                name: {**score(ytest, p),
                       "winner_accuracy": float(np.mean((np.asarray(p) >= .5) == ytest)),
                       "mean_predicted": float(np.mean(p)),
                       "actual_rate": float(np.mean(ytest))}
                for name, p in predictions.items()
            }
        folds.append({"season": season, "training_games": len(train),
                      "test_games": len(test), "markets": markets})
    return {
        "protocol": "expanding-window by season; all features from prior games only",
        "caveat": "PuckCast-style is an independently implemented logistic analogue, not PuckCast's proprietary feature set or trained model. MoneyPuck is a methodological reference, not replicated here.",
        "models": {**MODELS, "training_prevalence": [], "poisson_baseline": [],
                   "home_team_constant_pick": []},
        "folds": folds
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", default="data/games.csv")
    parser.add_argument("--output", default="results/model_benchmarks.json")
    args = parser.parse_args()
    games = pd.read_csv(args.games, dtype={"season": str})
    report = benchmark(games)
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2))
    print("MODEL_BENCHMARK_REPORT_BEGIN")
    print(json.dumps(report, indent=2))
    print("MODEL_BENCHMARK_REPORT_END")
