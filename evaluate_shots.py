"""Evaluate the same market-independent goal model with and without pregame shot data."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import PoissonRegressor
from scipy.stats import poisson,skellam
from independent_model import FEATURES,SEASONS,metrics
from improved_model import build_features
from enrich_nhl import rolling_shots_features

EXTRA=["home_shots_for","home_shots_against","home_save_pct",
       "away_shots_for","away_shots_against","away_save_pct"]

def fit_predict(train,test,cols):
    out={}
    for side in ("home","away"):
        m=make_pipeline(StandardScaler(),PoissonRegressor(alpha=5.0,max_iter=500))
        m.fit(train[cols].to_numpy(float),train[side+"_goals"].to_numpy(float))
        out[side]=np.clip(m.predict(test[cols].to_numpy(float)),0.3,7)
    h,a=out["home"],out["away"]
    return {"moneyline":skellam.sf(0,h,a)+0.5*skellam.pmf(0,h,a),
            "over_5_5":poisson.sf(5,h+a),"over_6_5":poisson.sf(6,h+a)}

def run(games,boxscores):
    if boxscores.empty:raise ValueError("No boxscore data")
    valid=games.game_id.isin(boxscores.game_id)
    coverage=float(valid.mean())
    if coverage<.98:raise ValueError(f"Boxscore coverage {coverage:.1%} below 98% requirement")
    df=build_features(games)
    df=df.merge(games[["game_id","home_goals","away_goals"]],on="game_id",validate="one_to_one")
    df=df.merge(rolling_shots_features(games,boxscores),on="game_id",validate="one_to_one")
    folds=[]
    for season in SEASONS:
        train=df[df.season<season];test=df[df.season==season]
        if train.empty or test.empty:continue
        original=fit_predict(train,test,FEATURES)
        enriched=fit_predict(train,test,FEATURES+EXTRA)
        markets={}
        for market,target in [("moneyline","home_win"),("over_5_5","over_5_5"),("over_6_5","over_6_5")]:
            y=test[target].to_numpy(int)
            markets[market]={"without_shots":metrics(y,original[market]),
                             "with_shots":metrics(y,enriched[market])}
        folds.append({"season":season,"games":len(test),"markets":markets})
    return {"coverage":coverage,"boxscores":len(boxscores),"folds":folds,
            "note":"Historical shots only, no xG or identified starting goalie; no market prices used."}

if __name__=="__main__":
    games=pd.read_csv("data/games.csv",dtype={"season":str})
    box=pd.read_csv("data/boxscores.csv")
    report=run(games,box)
    Path("results").mkdir(exist_ok=True)
    Path("results/shot_ablation_metrics.json").write_text(json.dumps(report,indent=2))
    print("SHOT_ABLATION_REPORT_BEGIN",flush=True)
    print(json.dumps(report,indent=2),flush=True)
    print("SHOT_ABLATION_REPORT_END",flush=True)
