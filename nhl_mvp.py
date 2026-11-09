"""NHL historical game downloader and leakage-safe Poisson baseline."""
import argparse,json,time,random,datetime as dt
from email.utils import parsedate_to_datetime
from pathlib import Path
import numpy as np
import pandas as pd
import requests
from scipy.stats import poisson,skellam
TEAMS="ANA BOS BUF CAR CBJ CGY CHI COL DAL DET EDM FLA LAK MIN MTL NJD NSH NYI NYR OTT PHI PIT SEA SJS STL TBL TOR UTA VAN VGK WPG WSH".split()
def download(seasons,out,refresh=False):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    cached=out/"games.csv"
    if cached.exists() and not refresh:
        previous=pd.read_csv(cached,dtype={"season":str})
        present=set(previous.season.unique())
        if set(seasons).issubset(present):
            print(f"Using {len(previous)} cached historical games; pass --refresh to fetch new results",flush=True)
            return
    games={};session=requests.Session()
    cache_dir=out/'nhl_schedule_cache';cache_dir.mkdir(parents=True,exist_ok=True)
    for season in seasons:
        for team in TEAMS:
            url=f"https://api-web.nhle.com/v1/club-schedule-season/{team}/{season}"
            cached_schedule=cache_dir/f"{team}_{season}.json"
            if cached_schedule.exists() and season != seasons[-1]:
                payload=json.loads(cached_schedule.read_text())
            else:
                for attempt in range(9):
                    try:
                        response=session.get(url,timeout=40)
                        if response.status_code in (429,500,502,503,504):
                            if attempt==8:response.raise_for_status()
                            retry=response.headers.get("Retry-After","")
                            try:wait=float(retry)
                            except ValueError:
                                try:wait=max(0,(parsedate_to_datetime(retry)-dt.datetime.now(dt.timezone.utc)).total_seconds())
                                except (TypeError,ValueError,OverflowError):wait=0
                            time.sleep(max(wait,min(90,3*2**attempt))+random.uniform(0,.5))
                            continue
                        response.raise_for_status()
                        payload=response.json()
                        cached_schedule.write_text(json.dumps(payload))
                        break
                    except (requests.Timeout,requests.ConnectionError):
                        if attempt==8:raise
                        time.sleep(min(90,3*2**attempt)+random.uniform(0,.5))
                time.sleep(1.0)
            for g in payload.get("games",[]):
                if g.get("gameType")!=2 or g.get("gameState") not in ("FINAL","OFF"):continue
                h,a=g.get("homeTeam",{}),g.get("awayTeam",{})
                if "score" not in h or "score" not in a:continue
                games[g["id"]]={"game_id":g["id"],"date":g["gameDate"],"season":str(season),"home":h["abbrev"],"away":a["abbrev"],"home_goals":h["score"],"away_goals":a["score"],"home_win":int(h["score"]>a["score"])}
            time.sleep(.15)
        print(f"Season {season}: {len(games)} unique games",flush=True)
    df=pd.DataFrame(games.values())
    if df.empty:raise RuntimeError("No completed NHL games returned")
    df.sort_values(["date","game_id"]).to_csv(out/"games.csv",index=False)
    print(f"Saved {len(df)} historical games",flush=True)
def pregame_features(games,lookback=20,prior_games=12):
    games=games.sort_values(["date","game_id"]);hist=[];rows=[]
    for date,day in games.groupby("date",sort=True):
        for _,g in day.iterrows():
            def rates(team):
                prior=[(gf,ga) for t,gf,ga in hist if t==team][-lookback:]
                n=len(prior)
                return ((sum(x for x,_ in prior)+prior_games*3)/(n+prior_games),(sum(x for _,x in prior)+prior_games*3)/(n+prior_games))
            hf,ha=rates(g.home);af,aa=rates(g.away)
            lh=float(np.clip(hf*aa/3*1.045,.7,6));la=float(np.clip(af*ha/3/1.045,.7,6))
            p=float(skellam.sf(0,lh,la)+.5*skellam.pmf(0,lh,la))
            rows.append(dict(g.to_dict(),p_home=p,p_over_5_5=float(poisson.sf(5,lh+la)),p_over_6_5=float(poisson.sf(6,lh+la))))
        for _,g in day.iterrows():
            hist.extend([(g.home,g.home_goals,g.away_goals),(g.away,g.away_goals,g.home_goals)])
    return pd.DataFrame(rows)
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="data");p.add_argument("--seasons",nargs="+",default=["20212022","20222023","20232024","20242025","20252026"]);p.add_argument("--refresh",action="store_true");a=p.parse_args();download(a.seasons,a.out,a.refresh)
