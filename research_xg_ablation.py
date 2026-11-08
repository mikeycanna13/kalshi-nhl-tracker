"""Real MoneyPuck xG ablation: train on 2022-23 and 2023-24, test on 2024-25."""
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
from improved_model import build_features, FEATURES, MARKETS, score

SEASONS=["2022","2023","2024"]
def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        download([s+str(int(s)+1) for s in SEASONS],root)
        games=pd.read_csv(root/"games.csv",dtype={"season":str})
        schedule=games[["game_id","date"]]
        ids=set(games.game_id.astype(int))
        shots=[]
        counts={}
        for s in SEASONS:
            response=requests.get(f"https://peter-tanner.com/moneypuck/downloads/shots_{s}.zip",timeout=180)
            response.raise_for_status()
            archive=root/f"shots_{s}.zip"
            archive.write_bytes(response.content)
            frame=load_shots(archive)
            frame["game_id"]=int(s)*1000000+pd.to_numeric(frame.game_id,errors="raise").astype("int64")
            frame=frame[frame.game_id.isin(ids)].copy()
            counts[s]=len(set(frame.game_id))
            if counts[s]<1200: raise ValueError(f"Low MoneyPuck coverage {s}: {counts[s]}")
            shots.append(frame)
            print(f"Loaded {s}: {len(frame)} shots, {counts[s]} games",flush=True)
        all_shots=pd.concat(shots,ignore_index=True)
        advanced,_=pregame_advanced_features(all_shots,game_dates=schedule)
        base=build_features(games)
        df=base.merge(advanced.drop(columns=["date"]),on="game_id",how="inner",validate="one_to_one")
        if len(df)!=len(base):raise ValueError(f"Unmatched feature rows {len(df)}/{len(base)}")
        if df.isna().any().any():raise ValueError("Null values in merged feature table")
        xg=[c for c in advanced if c.endswith("_pg")]
        train=df[df.season<"20242025"]
        test=df[df.season=="20242025"]
        if len(train)<2400 or len(test)<1200:raise ValueError("Insufficient train/test seasons")
        report={"protocol":"2022-23 and 2023-24 train; held-out 2024-25 test; no same-day or future features",
                "train_games":len(train),"test_games":len(test),"shot_counts":counts,
                "xg_features":xg,"markets":{}}
        for market,target in MARKETS.items():
            ytrain=train[target].to_numpy(int)
            ytest=test[target].to_numpy(int)
            results={}
            for name,columns in [("baseline",FEATURES),("baseline_plus_xg",FEATURES+xg)]:
                model=make_pipeline(StandardScaler(),LogisticRegression(C=.08,max_iter=1500))
                model.fit(train[columns].to_numpy(float),ytrain)
                p=model.predict_proba(test[columns].to_numpy(float))[:,1]
                results[name]=score(ytest,p)
            results["brier_improvement"]=round(results["baseline"]["brier"]-results["baseline_plus_xg"]["brier"],8)
            results["logloss_improvement"]=round(results["baseline"]["log_loss"]-results["baseline_plus_xg"]["log_loss"],8)
            report["markets"][market]=results
        print("REAL_XG_ABLATION="+json.dumps(report,sort_keys=True),flush=True)
        if not np.isfinite([v for market in report["markets"].values() for k,m in market.items() if isinstance(m,dict) for v in m.values()]).all():
            raise ValueError("Nonfinite model metrics")

if __name__=="__main__":main()
