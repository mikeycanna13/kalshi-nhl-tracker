"""Leakage-safe Elo + rolling form, regularized logistic models, walk-forward evaluation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from nhl_mvp import pregame_features

SEASONS=["20212022","20222023","20232024","20242025","20252026"]
MARKETS={"moneyline":"home_win","over_5_5":"over_5_5","over_6_5":"over_6_5"}
FEATURES=["elo_diff","home_elo","away_elo","home_gf","home_ga","away_gf","away_ga",
          "home_form","away_form","home_rest","away_rest","rest_diff","home_n","away_n",
          "poisson_home","poisson_over55","poisson_over65","season_progress"]

def build_features(games):
    games=games.sort_values(["date","game_id"]).copy()
    games["date"]=pd.to_datetime(games["date"])
    base=pregame_features(games.assign(date=games.date.dt.strftime("%Y-%m-%d")))
    base=base.set_index("game_id")
    ratings={}; history={}; last_date={}; rows=[]
    # Update state only AFTER all games on a date have been predicted.
    for date,day in games.groupby("date",sort=True):
        updates=[]
        for _,g in day.iterrows():
            h,a=g.home,g.away
            eh,ea=ratings.get(h,1500.),ratings.get(a,1500.)
            def stats(team):
                past=history.get(team,[])[-20:]
                n=len(past)
                gf=(sum(x[0] for x in past)+36)/(n+12)
                ga=(sum(x[1] for x in past)+36)/(n+12)
                form=(sum(x[2] for x in past[-10:])+5)/(min(n,10)+10)
                rest=7 if team not in last_date else int(np.clip((date-last_date[team]).days-1,0,7))
                return gf,ga,form,rest,n
            hf,hga,hform,hr,hn=stats(h)
            af,aga,aform,ar,an=stats(a)
            b=base.loc[g.game_id]
            progress=(date-pd.Timestamp(int(str(g.season)[:4]),10,1)).days/210
            rows.append(dict(game_id=g.game_id,season=str(g.season),date=str(date.date()),
              home_win=int(g.home_goals>g.away_goals),
              over_5_5=int(g.home_goals+g.away_goals>=6),
              over_6_5=int(g.home_goals+g.away_goals>=7),
              elo_diff=eh-ea,home_elo=eh,away_elo=ea,home_gf=hf,home_ga=hga,
              away_gf=af,away_ga=aga,home_form=hform,away_form=aform,
              home_rest=hr,away_rest=ar,rest_diff=hr-ar,home_n=hn,away_n=an,
              poisson_home=float(b.p_home),poisson_over55=float(b.p_over_5_5),
              poisson_over65=float(b.p_over_6_5),season_progress=float(np.clip(progress,0,1.5))))
            updates.append(g)
        for g in updates:
            h,a=g.home,g.away
            eh,ea=ratings.get(h,1500.),ratings.get(a,1500.)
            expected=1/(1+10**(-(eh-ea+35)/400))
            actual=float(g.home_goals>g.away_goals)
            delta=18*(actual-expected)
            ratings[h]=eh+delta;ratings[a]=ea-delta
            history.setdefault(h,[]).append((g.home_goals,g.away_goals,actual))
            history.setdefault(a,[]).append((g.away_goals,g.home_goals,1-actual))
            last_date[h]=date;last_date[a]=date
    return pd.DataFrame(rows)

def score(y,p):
    p=np.clip(np.asarray(p,dtype=float),1e-6,1-1e-6)
    return {"brier":float(brier_score_loss(y,p)),"log_loss":float(log_loss(y,p,labels=[0,1]))}

def evaluate(games):
    df=build_features(games)
    folds=[]
    for season in SEASONS[2:]:
        train=df[df.season<season];test=df[df.season==season]
        if train.empty or test.empty:continue
        fold={"test_season":season,"training_games":len(train),"test_games":len(test),"markets":{}}
        for market,target in MARKETS.items():
            xtrain=train[FEATURES].to_numpy(float);xtest=test[FEATURES].to_numpy(float)
            ytrain=train[target].to_numpy(int);ytest=test[target].to_numpy(int)
            model=make_pipeline(StandardScaler(),LogisticRegression(C=.08,max_iter=1000))
            model.fit(xtrain,ytrain)
            p=model.predict_proba(xtest)[:,1]
            base=np.full(len(test),ytrain.mean())
            poisson_col={"moneyline":"poisson_home","over_5_5":"poisson_over55","over_6_5":"poisson_over65"}[market]
            fold["markets"][market]={"regularized_logistic":score(ytest,p),
                "constant_baseline":score(ytest,base),
                "original_poisson":score(ytest,test[poisson_col]),
                "mean_prediction":float(p.mean()),"actual_rate":float(ytest.mean())}
            df.loc[test.index,"pred_"+market]=p
        folds.append(fold)
    return {"method":"expanding-window season-by-season walk-forward; pregame features only",
      "features":FEATURES,"folds":folds,
      "limitations":["No market odds or transaction costs","No confirmed starting goalies, injuries or xG",
                     "Season-level evaluation is not a demonstrated trading edge"]},df

if __name__=="__main__":
    games=pd.read_csv("data/games.csv",dtype={"season":str})
    report,pred=evaluate(games)
    Path("results").mkdir(exist_ok=True)
    Path("results/walkforward_metrics.json").write_text(json.dumps(report,indent=2))
    pred.to_csv("results/walkforward_predictions.csv",index=False)
    print("WALKFORWARD_REPORT_BEGIN",flush=True)
    print(json.dumps(report,indent=2),flush=True)
    print("WALKFORWARD_REPORT_END",flush=True)
