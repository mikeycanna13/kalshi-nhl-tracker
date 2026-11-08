"""Run NHL ingestion and holdout backtest as a finite batch job."""
from nhl_mvp import download
from backtest import backtest
import pandas as pd,json
from pathlib import Path
seasons=["20212022","20222023","20232024","20242025","20252026"]
download(seasons,"data")
games=pd.read_csv("data/games.csv",dtype={"season":str})
report,pred=backtest(games)
Path("results").mkdir(exist_ok=True)
Path("results/holdout_metrics.json").write_text(json.dumps(report,indent=2))
pred.to_csv("results/holdout_predictions.csv",index=False)
print("BACKTEST_REPORT_BEGIN",flush=True)
print(json.dumps(report,indent=2),flush=True)
print("BACKTEST_REPORT_END",flush=True)
