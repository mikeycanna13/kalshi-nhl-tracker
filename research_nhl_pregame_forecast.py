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

def forecast(date, history_file="data/games.csv", out="results/pregame_forecasts.json",
             starter_file=None, shots_file=None):
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
    shadow = {}
    starter_evidence = []
    if starter_file:
        from advanced_stats import ALIASES, load_shots, normalize
        from goalie_features import prior_goalie_features
        from starter_evidence import confirmed_pair

        starter_evidence = json.loads(Path(starter_file).read_text(encoding="utf-8"))
        cutoff = dt.datetime.now(dt.timezone.utc)
        pairs = {g["game_id"]: confirmed_pair(g, starter_evidence, cutoff)
                 for g in scheduled
                 if dt.datetime.fromisoformat(g["start_time_utc"].replace("Z", "+00:00")) > cutoff}
        if any(pairs.values()):
            # The input uses full NHL game IDs, including the season prefix.
            shots = load_shots(shots_file)
            raw_ids = next(c for c in ALIASES["game_id"] if c in shots)
            goalie_ids = next(c for c in ALIASES["goalie"] if c in shots)
            shots[goalie_ids] = pd.to_numeric(shots[goalie_ids], errors="raise").astype("Int64")
            shots = shots[pd.to_numeric(shots[raw_ids], errors="raise").isin(games.game_id)]
            historical = prior_goalie_features(shots, game_dates=games)
            training = train.merge(historical, on="game_id", validate="one_to_one")
            if len(training) < 1500:
                raise ValueError("Insufficient matched shot history for starter shadow model")
            # Use one common training sample for both members of the pair.
            normalized = normalize(shots, game_dates=games)
            goalie_rows = normalized.dropna(subset=["goalie"]).groupby("goalie")
            gsax = ((goalie_rows.xg.sum() - goalie_rows.goal.sum())
                    / (goalie_rows.game_id.nunique() + 12))
            columns = FEATURES + ["home_goalie_gsax", "away_goalie_gsax"]
            models = {}
            for name, label in MARKETS.items():
                for kind, inputs in (("baseline", FEATURES), ("adjusted", columns)):
                    model = make_pipeline(StandardScaler(), LogisticRegression(C=.08, max_iter=1000))
                    model.fit(training[inputs].to_numpy(float), training[label].to_numpy(int))
                    models[name, kind] = model, inputs
            for game_id, pair in pairs.items():
                if not pair or any(goalie not in gsax for goalie in pair):
                    continue
                row = test[test.game_id == game_id].assign(home_goalie_gsax=gsax[pair[0]],
                                                           away_goalie_gsax=gsax[pair[1]])
                result = {"goalie_ids_home_away": pair, "training_games": len(training),
                          "baseline": {}, "adjusted": {}}
                for (name, kind), (model, inputs) in models.items():
                    result[kind][name] = float(model.predict_proba(row[inputs].to_numpy(float))[0, 1])
                shadow[game_id] = result
    generated = dt.datetime.now(dt.timezone.utc)
    records=[]
    for i,(_,row) in enumerate(test.iterrows()):
        original=next(x for x in scheduled if x["game_id"]==int(row.game_id))
        if dt.datetime.fromisoformat(original["start_time_utc"].replace("Z", "+00:00")) <= generated:
            continue
        record = {"game_id":int(row.game_id),"home_team":original["home"],
          "away_team":original["away"],"date":date,
          "p_home_win":float(preds["moneyline"][i]),
          "p_over_5_5":float(preds["over_5_5"][i]),
          "p_over_6_5":float(preds["over_6_5"][i]),
          "generated_at_utc":generated.isoformat(),"model_trained_through_utc":generated.isoformat(),
          "last_training_game_date":str(games.date.max()),
          "scheduled_start_utc":original["start_time_utc"],
          "pregame_verified":True,
          "warning":"Pregame time verified against NHL schedule at generation; revalidate postponements and market settlement before analysis"}
        if original["game_id"] in shadow:
            record["starter_shadow"] = shadow[original["game_id"]]
        records.append(record)
    if not records:
        raise RuntimeError("No games remained pregame after model fitting")
    output=Path(out);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"target_date":date,"training_games":len(train),
          "forecast_count":len(records),"forecasts":records, "starter_evidence":starter_evidence},indent=2))
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
    p.add_argument("--starter-evidence", help="JSON list of timestamped, team-specific starter reports")
    p.add_argument("--starter-shots", help="Combined MoneyPuck shot CSV with full NHL game IDs")
    a=p.parse_args()
    if bool(a.starter_evidence) != bool(a.starter_shots):
        p.error("--starter-evidence and --starter-shots must be supplied together")
    forecast(a.date, a.history, a.out, a.starter_evidence, a.starter_shots)
