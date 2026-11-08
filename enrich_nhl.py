"""Incremental NHL boxscore enrichment: shots, goalie saves and pregame rolling features.

Fetch once per historical game and persist CSV. Never use the current game's
boxscore in its own prediction. Run separately from the weekly core pipeline:
python enrich_nhl.py --games data/games.csv --out data/boxscore_features.csv
"""
import argparse,time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

def fetch_boxscores(games,out,max_games=None):
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    existing=pd.read_csv(out) if out.exists() else pd.DataFrame()
    done=set(existing.game_id.astype(int)) if not existing.empty else set()
    rows=[];session=requests.Session()
    def checkpoint():
        if not rows:return existing
        combined=pd.concat([existing,pd.DataFrame(rows)],ignore_index=True)
        combined=combined.drop_duplicates("game_id",keep="last").sort_values(["date","game_id"])
        tmp=out.with_suffix(out.suffix+".tmp")
        combined.to_csv(tmp,index=False)
        tmp.replace(out)
        return combined
    failures=[]
    pending=games[~games.game_id.astype(int).isin(done)].sort_values(["date","game_id"])
    if max_games is not None:pending=pending.head(max_games)
    last_saved=0
    for _,g in pending.iterrows():
        url=f"https://api-web.nhle.com/v1/gamecenter/{int(g.game_id)}/boxscore"
        try:
            r=session.get(url,timeout=25);r.raise_for_status();j=r.json()
            h,a=j.get("homeTeam",{}),j.get("awayTeam",{})
            # 'sog' is shots on goal; save percentage is a historical team
            # proxy, NOT a known starting goalie's future performance.
            hs=h.get("sog");ass=a.get("sog")
            if hs is None or ass is None:raise ValueError("missing team SOG")
            rows.append({"game_id":int(g.game_id),"date":str(g.date),
                "home":g.home,"away":g.away,"home_sog":float(hs),
                "away_sog":float(ass),"home_goals":int(g.home_goals),
                "away_goals":int(g.away_goals)})
        except (requests.RequestException,ValueError,TypeError) as e:
            failures.append(int(g.game_id))
            print(f"SKIP {g.game_id}: {e}",flush=True)
        if len(rows)%50==0 and rows and len(rows)!=last_saved:
            checkpoint()
            last_saved=len(rows)
            print(f"Fetched {len(rows)} new boxscores (checkpoint saved)",flush=True)
        time.sleep(.08)
    merged=checkpoint()
    print(f"Boxscores: {len(merged)} cached, {len(rows)} newly fetched, {len(failures)} failed",flush=True)
    return merged

def rolling_shots_features(games,boxscores,window=15):
    """Compute strictly prior-game shots, shot differential and save rate."""
    df=games.sort_values(["date","game_id"]).copy()
    b=boxscores.set_index("game_id")
    history={};result=[]
    for date,day in df.groupby("date",sort=True):
        updates=[]
        for _,g in day.iterrows():
            row={"game_id":int(g.game_id)}
            for side,team in [("home",g.home),("away",g.away)]:
                past=history.get(team,[])[-window:]
                row[side+"_shots_for"]=float(np.mean([x[0] for x in past])) if past else 30.
                row[side+"_shots_against"]=float(np.mean([x[1] for x in past])) if past else 30.
                saves=sum(x[1]-x[3] for x in past)
                faced=sum(x[1] for x in past)
                row[side+"_save_pct"]=(saves+92)/(faced+100)
            result.append(row)
            if int(g.game_id) in b.index:
                v=b.loc[int(g.game_id)]
                updates.extend([(g.home,float(v.home_sog),float(v.away_sog),
                                 float(g.home_goals),float(g.away_goals)),
                                (g.away,float(v.away_sog),float(v.home_sog),
                                 float(g.away_goals),float(g.home_goals))])
        for team,sf,sa,gf,ga in updates:
            history.setdefault(team,[]).append((sf,sa,gf,ga))
    return pd.DataFrame(result)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--games",default="data/games.csv")
    p.add_argument("--out",default="data/boxscores.csv")
    p.add_argument("--max-games",type=int,default=250)
    args=p.parse_args()
    games=pd.read_csv(args.games)
    box=fetch_boxscores(games,args.out,args.max_games)
    if not box.empty:
        rolling_shots_features(games,box).to_csv("data/shot_features.csv",index=False)
        print("Saved pregame-only shot features",flush=True)
