"""Compare the NHL baseline with historical MoneyPuck xG or goalie features."""
import argparse
import json
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from nhl_mvp import download
from advanced_stats import load_shots, pregame_advanced_features
from goalie_features import prior_goalie_features
from improved_model import build_features, FEATURES, MARKETS, score

SEASONS=["2021","2022","2023","2024","2025"]
def main(goalies=False, history=None, shots_dir=None):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        if history is None:
            download([s+str(int(s)+1) for s in SEASONS],root)
        games=pd.read_csv(history or root/"games.csv",dtype={"season":str})
        schedule=games[["game_id","date"]]
        ids=set(games.game_id.astype(int))
        shots=[]
        counts={}
        for s in SEASONS:
            archive = (shots_dir or root) / f"shots_{s}.zip"
            if shots_dir is None:
                response = requests.get(f"https://peter-tanner.com/moneypuck/downloads/shots_{s}.zip", timeout=180)
                response.raise_for_status()
                archive.write_bytes(response.content)
            frame=load_shots(archive)
            frame["game_id"]=int(s)*1000000+pd.to_numeric(frame.game_id,errors="raise").astype("int64")
            frame=frame[frame.game_id.isin(ids)].copy()
            counts[s]=len(set(frame.game_id))
            if counts[s]<1200: raise ValueError(f"Low MoneyPuck coverage {s}: {counts[s]}")
            shots.append(frame)
            print(f"Loaded {s}: {len(frame)} shots, {counts[s]} games",flush=True)
        all_shots=pd.concat(shots,ignore_index=True)
        if goalies:
            advanced = prior_goalie_features(all_shots, game_dates=schedule)
            feature_columns = ["home_goalie_gsax", "away_goalie_gsax"]
            model_name = "baseline_plus_goalie_proxy"
        else:
            advanced, _ = pregame_advanced_features(all_shots, game_dates=schedule)
            feature_columns = [c for c in advanced if c.endswith("_pg")]
            model_name = "baseline_plus_xg"
        base=build_features(games)
        missing_ids=sorted(set(base.game_id)-set(advanced.game_id))
        if missing_ids:
            print("MISSING_XG_GAME_IDS="+json.dumps(missing_ids),flush=True)
            if len(missing_ids)>1:
                raise ValueError(f"Too many missing MoneyPuck games: {missing_ids}")
            # Exclude the single shotless game symmetrically from both models.
            base=base[~base.game_id.isin(missing_ids)].copy()
        df=base.merge(advanced.drop(columns=["date"], errors="ignore"),on="game_id",how="inner",validate="one_to_one")
        if len(df)!=len(base):raise ValueError(f"Unmatched feature rows {len(df)}/{len(base)}")
        if df.isna().any().any():raise ValueError("Null values in merged feature table")
        rng=np.random.default_rng(20261108)
        report={"protocol":"Expanding-window; 2023-24, 2024-25, 2025-26 held-out folds; historical pregame xG",
                "shot_counts":counts,("goalie_features" if goalies else "xg_features"):feature_columns,"excluded_game_ids":missing_ids,"folds":[],"pooled":{}}
        if goalies:
            report["protocol"] = report["protocol"].replace("historical pregame xG", "strictly prior-date goalie pool proxy")
        pooled={market:{"y":[],"baseline":[],model_name:[]} for market in MARKETS}
        for season in ["20232024","20242025","20252026"]:
            train=df[df.season<season]
            test=df[df.season==season]
            if len(train)<2400 or len(test)<1000:
                raise ValueError(f"Insufficient fold data {season}: {len(train)} train, {len(test)} test")
            fold={"test_season":season,"train_games":len(train),"test_games":len(test),"markets":{}}
            for market,target in MARKETS.items():
                ytrain=train[target].to_numpy(int)
                ytest=test[target].to_numpy(int)
                predictions={}
                for name,columns in [("baseline",FEATURES),(model_name,FEATURES+feature_columns)]:
                    model=make_pipeline(StandardScaler(),LogisticRegression(C=.08,max_iter=1500))
                    model.fit(train[columns].to_numpy(float),ytrain)
                    predictions[name]=model.predict_proba(test[columns].to_numpy(float))[:,1]
                result={name:score(ytest,p) for name,p in predictions.items()}
                result["brier_improvement"]=float(result["baseline"]["brier"]-result[model_name]["brier"])
                result["logloss_improvement"]=float(result["baseline"]["log_loss"]-result[model_name]["log_loss"])
                fold["markets"][market]=result
                pooled[market]["y"].extend(ytest.tolist())
                for name,p in predictions.items():pooled[market][name].extend(p.tolist())
            report["folds"].append(fold)
        for market,values in pooled.items():
            y=np.asarray(values["y"],dtype=float)
            p0=np.clip(np.asarray(values["baseline"]),1e-6,1-1e-6)
            p1=np.clip(np.asarray(values[model_name]),1e-6,1-1e-6)
            brier_delta=(y-p0)**2-(y-p1)**2
            log_delta=-(y*np.log(p0)+(1-y)*np.log(1-p0))+(y*np.log(p1)+(1-y)*np.log(1-p1))
            fold_sizes=[f["test_games"] for f in report["folds"]]
            bounds=np.cumsum([0]+fold_sizes)
            groups=[np.arange(bounds[i],bounds[i+1]) for i in range(len(fold_sizes))]
            draws=np.empty((2000,2))
            for i in range(2000):
                sampled=np.concatenate([rng.choice(g,size=len(g),replace=True) for g in groups])
                draws[i]=[brier_delta[sampled].mean(),log_delta[sampled].mean()]
            report["pooled"][market]={
                "test_games":len(y),"baseline":score(y,p0),model_name:score(y,p1),
                "brier_improvement":float(brier_delta.mean()),
                "brier_95pct_ci":np.quantile(draws[:,0],[.025,.975]).tolist(),
                "logloss_improvement":float(log_delta.mean()),
                "logloss_95pct_ci":np.quantile(draws[:,1],[.025,.975]).tolist(),
                "positive_brier_folds":sum(f["markets"][market]["brier_improvement"]>0 for f in report["folds"])}
        print(("REAL_GOALIE_ABLATION=" if goalies else "REAL_XG_ABLATION=")+json.dumps(report,sort_keys=True),flush=True)
        if not all(np.isfinite(m["brier_improvement"]) for m in report["pooled"].values()):
            raise ValueError("Nonfinite model metrics")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--goalie-proxy", action="store_true")
    parser.add_argument("--history", type=Path)
    parser.add_argument("--shots-dir", type=Path)
    args = parser.parse_args()
    main(args.goalie_proxy, args.history, args.shots_dir)
