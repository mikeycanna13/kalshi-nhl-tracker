"""Market-independent NHL score distribution and fair probabilities.

All features are pregame values produced by improved_model.build_features.
No bookmaker or prediction-market prices are used.
"""
import numpy as np
from scipy.stats import poisson, skellam
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss, log_loss

FEATURES=["elo_diff","home_gf","home_ga","away_gf","away_ga","home_form",
          "away_form","home_rest","away_rest","season_progress"]
SEASONS=["20232024","20242025","20252026"]

def fit(train):
    x=train[FEATURES].to_numpy(float)
    models={}
    for side in ("home","away"):
        models[side]=make_pipeline(StandardScaler(),PoissonRegressor(alpha=5.0,max_iter=500))
        models[side].fit(x,train[side+"_goals"].to_numpy(float))
    return models

def probabilities(models,features):
    x=features[FEATURES].to_numpy(float)
    home=np.clip(models["home"].predict(x),0.3,7)
    away=np.clip(models["away"].predict(x),0.3,7)
    total=home+away
    # NHL games tied after regulation are settled in OT/SO. This baseline
    # allocates ties equally; future models should estimate OT/SO separately.
    p_home=skellam.sf(0,home,away)+0.5*skellam.pmf(0,home,away)
    return {"moneyline":p_home,"over_5_5":poisson.sf(5,total),
            "over_6_5":poisson.sf(6,total),
            "home_expected_goals":home,"away_expected_goals":away}

def metrics(y,p):
    p=np.clip(np.asarray(p,float),1e-6,1-1e-6)
    return {"brier":float(brier_score_loss(y,p)),
            "log_loss":float(log_loss(y,p,labels=[0,1]))}

def evaluate(games):
    from improved_model import build_features
    import pandas as pd
    df=build_features(games)
    goals=games[["game_id","home_goals","away_goals"]].copy()
    df=df.merge(goals,on="game_id",validate="one_to_one")
    results=[]
    for season in SEASONS:
        train=df[df.season<season].copy()
        test=df[df.season==season].copy()
        if train.empty or test.empty:continue
        pred=probabilities(fit(train),test)
        fold={"test_season":season,"training_games":len(train),
              "test_games":len(test),"markets":{}}
        for market,target in [("moneyline","home_win"),
                              ("over_5_5","over_5_5"),("over_6_5","over_6_5")]:
            y=test[target].to_numpy(int)
            baseline=np.full(len(y),train[target].mean())
            fold["markets"][market]={"independent_goal_model":metrics(y,pred[market]),
                                    "constant_baseline":metrics(y,baseline)}
            test["pred_"+market]=pred[market]
        test["home_expected_goals"]=pred["home_expected_goals"]
        test["away_expected_goals"]=pred["away_expected_goals"]
        results.append((fold,test))
    report={"method":"market-independent, season-level expanding-window walk-forward",
            "features":FEATURES,"folds":[f for f,_ in results],
            "limitations":["No xG or confirmed goalies yet","No bookmaker odds used as features",
                           "OT/SO ties approximated as 50/50",
                           "Do not infer a trading edge from Brier scores alone"]}
    predictions=pd.concat([t for _,t in results],ignore_index=True) if results else pd.DataFrame()
    return report,predictions
