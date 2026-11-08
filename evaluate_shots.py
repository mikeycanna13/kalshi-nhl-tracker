"""Evaluate the same market-independent goal model with and without pregame shot data."""
import json
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import PoissonRegressor
from scipy.stats import poisson,skellam
from sklearn.metrics import log_loss
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
    folds=[]; paired={k:[] for k in ('moneyline','over_5_5','over_6_5')}
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
            paired[market].append(pd.DataFrame({"game_id":test.game_id.to_numpy(),
                "season":season,"date":test.date.to_numpy(),"actual":y,
                "baseline":original[market],"enhanced":enriched[market]}))
        folds.append({"season":season,"games":len(test),"markets":markets})
    comparisons={}
    rng=np.random.default_rng(20261108)
    for market,frames in paired.items():
        z=pd.concat(frames,ignore_index=True)
        y=z.actual.to_numpy(int)
        p0=np.clip(z.baseline.to_numpy(float),1e-6,1-1e-6)
        p1=np.clip(z.enhanced.to_numpy(float),1e-6,1-1e-6)
        # Paired loss differences: negative means enriched model wins.
        db=(p1-y)**2-(p0-y)**2
        dl=-(y*np.log(p1)+(1-y)*np.log(1-p1))+(y*np.log(p0)+(1-y)*np.log(1-p0))
        # Block bootstrap by game date, retaining same-day dependence.
        groups=[g.index.to_numpy() for _,g in z.groupby("date",sort=False)]
        boot=np.empty((1500,2))
        for i in range(len(boot)):
            selected=rng.integers(0,len(groups),len(groups))
            ix=np.concatenate([groups[j] for j in selected])
            boot[i]=[db[ix].mean(),dl[ix].mean()]
        bins=[]
        for name,pred in (("baseline",p0),("enhanced",p1)):
            for lo,hi in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
                mask=(pred>=lo)&(pred<hi if hi<1 else pred<=hi)
                if mask.any():bins.append({"model":name,"lower":float(lo),
                    "upper":float(hi),"count":int(mask.sum()),
                    "predicted":float(pred[mask].mean()),"observed":float(y[mask].mean())})
        comparisons[market]={"games":len(z),
            "pooled_baseline":metrics(y,p0),"pooled_enhanced":metrics(y,p1),
            "delta_brier":float(db.mean()),"delta_log_loss":float(dl.mean()),
            "delta_brier_95pct_bootstrap_ci":np.quantile(boot[:,0],[.025,.975]).tolist(),
            "delta_log_loss_95pct_bootstrap_ci":np.quantile(boot[:,1],[.025,.975]).tolist(),
            "calibration_deciles":bins}
    return {"coverage":coverage,"boxscores":len(boxscores),"folds":folds,
            "pooled_paired_comparison":comparisons,
            "bootstrap":"1500 paired game-date block resamples; 95% percentile intervals",
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
