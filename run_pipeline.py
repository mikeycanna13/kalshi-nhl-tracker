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

from improved_model import evaluate
improved_report,improved_predictions=evaluate(games)
Path('results/walkforward_metrics.json').write_text(json.dumps(improved_report,indent=2))
improved_predictions.to_csv('results/walkforward_predictions.csv',index=False)
print('WALKFORWARD_REPORT_BEGIN',flush=True)
print(json.dumps(improved_report,indent=2),flush=True)
print('WALKFORWARD_REPORT_END',flush=True)

from independent_model import evaluate as evaluate_independent
independent_report,independent_predictions=evaluate_independent(games)
Path("results/independent_metrics.json").write_text(json.dumps(independent_report,indent=2))
independent_predictions.to_csv("results/independent_predictions.csv",index=False)
print("INDEPENDENT_REPORT_BEGIN",flush=True)
print(json.dumps(independent_report,indent=2),flush=True)
print("INDEPENDENT_REPORT_END",flush=True)
