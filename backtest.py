"""Out-of-sample 2025-26 NHL game winner and totals baseline evaluation."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss,log_loss
from nhl_mvp import pregame_features
def backtest(games,test_season="20252026"):
    games=games.copy();games["season"]=games["season"].astype(str)
    if games.game_id.duplicated().any():raise ValueError("Duplicate game IDs")
    train=games[games.season!=test_season];holdout=games[games.season==test_season]
    if train.empty or holdout.empty:raise ValueError("Missing training or holdout season")
    if train.date.max()>=holdout.date.min():raise ValueError("Training overlaps holdout")
    pred=pregame_features(games);test=pred[pred.season==test_season].copy()
    result={"test_season":test_season,"n_games":len(test),"historical_games":len(train),"markets":{},"limitations":["No sportsbook or Kalshi market prices","No goalie, injuries, xG, or OT/SO-specific model","2025-26 results are a historical holdout, not a live trading forecast"]}
    for name,y,p,base in [
      ("moneyline",test.home_win,test.p_home,train.home_win.mean()),
      ("over_5_5",((test.home_goals+test.away_goals)>=6).astype(int),test.p_over_5_5,((train.home_goals+train.away_goals)>=6).mean()),
      ("over_6_5",((test.home_goals+test.away_goals)>=7).astype(int),test.p_over_6_5,((train.home_goals+train.away_goals)>=7).mean())]:
        def metrics(probs):
            probs=np.clip(np.asarray(probs,dtype=float),1e-8,1-1e-8)
            return {"brier":float(brier_score_loss(y,probs)),"log_loss":float(log_loss(y,probs,labels=[0,1]))}
        bins=[]
        for lo in np.arange(0,1,.1):
            mask=(p>=lo)&(p<(lo+.1 if lo<.9 else 1.00001))
            if mask.any():bins.append({"range":f"{lo:.1f}-{lo+.1:.1f}","n":int(mask.sum()),"predicted":float(p[mask].mean()),"actual":float(y[mask].mean())})
        result["markets"][name]={"model":metrics(p),"train_only_constant_baseline":metrics(np.full(len(y),base)),"calibration_bins":bins}
    return result,test
if __name__=="__main__":
    games=pd.read_csv("data/games.csv",dtype={"season":str});report,pred=backtest(games)
    Path("results").mkdir(exist_ok=True);Path("results/holdout_metrics.json").write_text(json.dumps(report,indent=2))
    pred.to_csv("results/holdout_predictions.csv",index=False)
    print(json.dumps(report,indent=2),flush=True)
