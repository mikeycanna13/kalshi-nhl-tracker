"""Produce genuine pregame NHL probabilities from completed games only.

One target schedule date per run. Synthetic future rows are feature placeholders,
never training labels. Forecast timestamps and data cutoff are recorded.
Research only; no betting orders or trading recommendations.
"""
import argparse,datetime as dt,json
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from improved_model import build_features,FEATURES,MARKETS

def forecast(date,history_file="data/games.csv",out="results/pregame_forecasts.json"):
    target=dt.date.fromisoformat(date)
    today=dt.datetime.now(dt.timezone.utc)
    if target < today.date():raise ValueError("Target date is in the past")
    games=pd.read_csv(history_file,dtype={"season":str})
    games["date"]=pd.to_datetime(games["date"]).dt.strftime("%Y-%m-%d")
    games=games[games.date<date].copy()
    if len(games)<1500:raise RuntimeError("Insufficient completed historical games")
    response=requests.get("https://api-web.nhle.com/v1/score/"+date,timeout=30)
    response.raise_for_status()
    scheduled=[]
    for g in response.json().get("games",[]):
        if g.get("gameDate")!=date or g.get("gameType")!=2:continue
        if g.get("gameState") in ("FINAL","OFF"):continue
        home=(g.get("homeTeam") or {}).get("abbrev")
        away=(g.get("awayTeam") or {}).get("abbrev")
        if not (home and away and g.get("id")):continue
        start=g.get("startTimeUTC")
        if not start:continue
        start_at=dt.datetime.fromisoformat(start.replace("Z","+00:00"))
        if start_at<=today:continue
        scheduled.append({"game_id":int(g["id"]),"date":date,"start_time_utc":start,
                          "season":str(g["season"]),"home":home,"away":away,
                          "home_goals":0,"away_goals":0})
    if not scheduled:raise RuntimeError("No uncompleted regular-season games on date")
    synthetic=pd.DataFrame(scheduled)
    if set(synthetic.game_id)&set(games.game_id):raise RuntimeError("Future games in training data")
    features=build_features(pd.concat([games,synthetic],ignore_index=True))
    train=features[features.game_id.isin(games.game_id)]
    test=features[features.game_id.isin(synthetic.game_id)]
    if len(test)!=len(synthetic):raise RuntimeError("Missing target game features")
    preds={}
    for name,label in MARKETS.items():
        model=make_pipeline(StandardScaler(),LogisticRegression(C=.08,max_iter=1000))
        model.fit(train[FEATURES].to_numpy(float),train[label].to_numpy(int))
        preds[name]=model.predict_proba(test[FEATURES].to_numpy(float))[:,1]
    generated = dt.datetime.now(dt.timezone.utc)
    records=[]
    for i,(_,row) in enumerate(test.iterrows()):
        original=next(x for x in scheduled if x["game_id"]==int(row.game_id))
        if dt.datetime.fromisoformat(original["start_time_utc"].replace("Z", "+00:00")) <= generated:
            continue
        records.append({"game_id":int(row.game_id),"home_team":original["home"],
          "away_team":original["away"],"date":date,
          "p_home_win":float(preds["moneyline"][i]),
          "p_over_5_5":float(preds["over_5_5"][i]),
          "p_over_6_5":float(preds["over_6_5"][i]),
          "generated_at_utc":generated.isoformat(),"model_trained_through_utc":generated.isoformat(),
          "last_training_game_date":str(games.date.max()),
          "scheduled_start_utc":original["start_time_utc"],
          "pregame_verified":True,
          "warning":"Pregame time verified against NHL schedule at generation; revalidate postponements and market settlement before analysis"})
    if not records:
        raise RuntimeError("No games remained pregame after model fitting")
    output=Path(out);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"target_date":date,"training_games":len(train),
          "forecast_count":len(records),"forecasts":records},indent=2))
    print("NHL_PREGAME_FORECAST="+json.dumps({"date":date,"training_games":len(train),
          "forecast_count":len(records),"output":str(output),
          "limitations":["No confirmed goalie or injury inputs",
                         "Scheduled start checked against NHL API; quote must also predate puck drop",
                         "No live price or fee join"]}),flush=True)
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--date",required=True)
    p.add_argument("--history",default="data/games.csv")
    p.add_argument("--out",default="results/pregame_forecasts.json")
    a=p.parse_args()
    forecast(a.date,a.history,a.out)
