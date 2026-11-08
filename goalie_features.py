"""Leakage-safe daily goalie GSAx snapshots for pregame starter projections.

Only games strictly before snapshot_date are included. This module deliberately
does NOT infer a confirmed starter from game-day shot data.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import pandas as pd
from advanced_stats import load_shots, normalize

def goalie_snapshots(raw, prior_games=12):
    d=normalize(raw)
    history=defaultdict(lambda: [0.,0.,0])
    output=[]
    for date,day in d.groupby("date",sort=True):
        # A snapshot for each goalie observed up to the previous date,
        # before applying any of today's outcomes.
        for goalie, (xga,ga,games) in history.items():
            output.append({
                "snapshot_date":str(date.date()),
                "goalie_id":goalie,
                "prior_games":games,
                "prior_xga":xga,
                "prior_ga":ga,
                "prior_gsax":xga-ga,
                "shrunk_gsax_per_game":(xga-ga)/(games+prior_games),
            })
        updates=defaultdict(lambda:[0.,0.,0])
        for (_,game_id), game in day.groupby(["date","game_id"],sort=True):
            for goalie,group in game.dropna(subset=["goalie"]).groupby("goalie"):
                updates[goalie][0]+=float(group.xg.sum())
                updates[goalie][1]+=float(group.goal.sum())
                updates[goalie][2]+=1
        for goalie, values in updates.items():
            for i,value in enumerate(values):
                history[goalie][i]+=value
    return pd.DataFrame(output,columns=[
        "snapshot_date","goalie_id","prior_games","prior_xga","prior_ga",
        "prior_gsax","shrunk_gsax_per_game"])

def attach_projected_goalies(games, projections, snapshots):
    """Join externally timestamped starter projections, never actual game starters.

    projections columns: game_id, prediction_date, goalie_id, probability.
    Each game must have valid probabilities summing to 1. Caller must provide
    historical projections actually available before the prediction cutoff.
    """
    required={"game_id","prediction_date","goalie_id","probability"}
    if not required.issubset(projections.columns):
        raise ValueError(f"Missing projected goalie fields: {required-set(projections.columns)}")
    p=projections.copy()
    p["prediction_date"]=pd.to_datetime(p.prediction_date).dt.strftime("%Y-%m-%d")
    p["probability"]=pd.to_numeric(p.probability,errors="raise")
    if p.empty or not p.probability.between(0,1).all():
        raise ValueError("Invalid goalie probabilities")
    sums=p.groupby("game_id").probability.sum()
    if not ((sums-1).abs()<1e-6).all():
        raise ValueError("Starter probabilities must sum to one per game")
    if p.duplicated(["game_id","goalie_id"]).any():
        raise ValueError("Duplicate projected goalie")
    g=games[["game_id","date"]].copy()
    g["date"]=pd.to_datetime(g.date).dt.strftime("%Y-%m-%d")
    p=p.merge(g,on="game_id",validate="many_to_one")
    if not (p.prediction_date<=p.date).all():
        raise ValueError("Starter projection timestamp after game date")
    # Snapshot must be strictly prior to prediction date, never same-day outcomes.
    s=snapshots.rename(columns={"snapshot_date":"prediction_date"})
    p=p.merge(s[["prediction_date","goalie_id","shrunk_gsax_per_game"]],
              on=["prediction_date","goalie_id"],how="left",validate="many_to_one")
    if p.shrunk_gsax_per_game.isna().any():
        raise ValueError("Missing pregame goalie history; explicitly handle unknown goalies")
    p["weighted_gsax"]=p.probability*p.shrunk_gsax_per_game
    return p.groupby("game_id",as_index=False).weighted_gsax.sum()

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--shots",required=True)
    parser.add_argument("--out",default="data/goalie_snapshots.csv")
    args=parser.parse_args()
    out=Path(args.out);out.parent.mkdir(parents=True,exist_ok=True)
    snapshots=goalie_snapshots(load_shots(args.shots))
    snapshots.to_csv(out,index=False)
    print(f"Saved {len(snapshots)} historical pregame goalie snapshots to {out}")
