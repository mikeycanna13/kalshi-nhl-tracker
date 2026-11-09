"""Score frozen NHL/Kalshi research selections over multiple game dates.

Select exactly one archived run per NHL target date (earliest snapshot).
Each Kalshi ticker's public final settlement is fetched at most once per run.
Unfinalized, nonbinary, revised, missing, or void settlements are NOT wins/losses.
Reported P&L is *paper*, not an executable return or risk-adjusted alpha.
"""
import argparse
import json
import math
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
import requests

from research_forward_ledger import load_archives, parse_time
from research_kalshi_snapshots import get

def primary_archives(records):
    by_date={}
    for record in records:
        day=record["target_date"]
        if day not in by_date or parse_time(record["captured_at_utc"]) < parse_time(by_date[day]["captured_at_utc"]):
            by_date[day]=record
    return sorted(by_date.values(),key=lambda x:x["target_date"])

def collection_window(archive):
    """Classification comes from frozen capture, not inferred after settlement."""
    return (archive.get("capture") or {}).get("scheduler_context",{}).get("window","development")


def per_window_archives(records):
    """Earliest frozen run for each target date and each capture window."""
    selection={}
    for archive in records:
        key=(archive["target_date"],collection_window(archive))
        if key not in selection or parse_time(archive["captured_at_utc"])<parse_time(selection[key]["captured_at_utc"]):
            selection[key]=archive
    return sorted(selection.values(),key=lambda x:(x["target_date"],collection_window(x)))


def outcome_cache(archives,session,provider=get):
    """Fetch only eligible archived contract tickers, de-duplicated."""
    tickers=sorted({
        row["ticker"]
        for archive in archives for row in archive["capture"].get("rows",[])
        if row.get("status")=="research_candidate" and row.get("ticker")})
    market={}
    errors={}
    for ticker in tickers:
        try:
            response=provider(session,"/markets/"+ticker)
            data=response["market"]
            market[ticker]={"status":data.get("status"),"result":data.get("result")}
        except (requests.RequestException,KeyError,TypeError,ValueError) as exc:
            errors[ticker]=type(exc).__name__
    return market,errors

def compute(archives,markets,errors=None):
    """Replay frozen quotes with later settlement, once per target game date."""
    primary=primary_archives(archives)
    errors=errors or {}
    counts=Counter()
    paper=[]
    calibration={}
    for archive in primary:
        for row in archive["capture"].get("rows",[]):
            if row.get("status")!="research_candidate":
                continue
            ticker=row.get("ticker")
            market=markets.get(ticker)
            if not market:
                counts["market_not_fetched"]+=1
                continue
            if market.get("status")!="finalized" or market.get("result") not in ("yes","no"):
                counts["not_finalized_or_nonbinary"]+=1
                continue
            side=row.get("contract_side")
            if side not in ("yes","no"):
                counts["unknown_side"]+=1
                continue
            outcome=int(market["result"]==side)
            counts["settled_eligible_sides"]+=1
            if row.get("paper_selected"):
                price=row.get("ask_cents",row.get("yes_ask_cents"))
                fee=row.get("fee_cents_per_contract")
                if not isinstance(price,(int,float)) or not isinstance(fee,(int,float)):
                    counts["missing_frozen_cost"]+=1
                    continue
                cost=(price+fee)/100
                if not (0<cost<1.1):
                    counts["invalid_frozen_cost"]+=1
                    continue
                paper.append({
                    "date":archive["target_date"],"source_run_id":archive["source_run_id"],
                    "ticker":ticker,"side":side,
                    "nhl_game_id":(row.get("contract") or {}).get("nhl_game_id"),
                    "observed_at_utc":(row.get("quote") or {}).get("observed_at_utc"),
                    "model_probability":row["model_probability"],
                    "ask_cents":price,"fee_cents":fee,"paper_cost_usd":round(cost,6),
                    "outcome":outcome,"paper_profit_usd":round(outcome-cost,6)})
            if side!="yes" or row.get("market_probability") is None:
                continue
            contract=row.get("contract") or {}
            kind=contract.get("market_type")
            forecast=row.get("forecast") or {}
            game=contract.get("nhl_game_id")
            if game is None or kind not in ("moneyline","total"):
                continue
            if kind=="moneyline":
                selected=forecast.get("contract_selection_team")
                home=contract.get("home_team")
                if selected not in (home,contract.get("away_team")):
                    continue
                # Prefer a home-team YES ticker, if available. Otherwise invert away.
                as_home=selected==home
                p_model=float(forecast.get("p_home_win",float("nan")))
                p_market=float(row["market_probability"])
                y=int(market["result"]=="yes")
                if not as_home:
                    p_market=1-p_market
                    y=1-y
                key=("moneyline",game)
                preference=1 if as_home else 0
            else:
                threshold=contract.get("threshold")
                if threshold not in (5.5,6.5):
                    continue
                p_model=float(forecast.get("p_over_5_5" if threshold==5.5 else "p_over_6_5",float("nan")))
                p_market=float(row["market_probability"])
                y=int(market["result"]=="yes")
                key=("total",game,threshold)
                preference=1
            if not (0<=p_model<=1 and 0<=p_market<=1 and math.isfinite(p_model) and math.isfinite(p_market)):
                continue
            # Same game's YES/NO is one event, multiple winner tickers are not independent.
            if key not in calibration or preference>calibration[key]["preference"]:
                calibration[key]={"kind":kind,"model":p_model,
                                  "market":p_market,"outcome":y,"preference":preference,
                                  "date":archive["target_date"]}
    scored={}
    for kind in ("moneyline","total"):
        samples=[x for x in calibration.values() if x["kind"]==kind]
        if not samples:
            scored[kind]={"n":0,"model_brier":None,"market_brier":None,"brier_delta":None}
            continue
        n=len(samples)
        model=sum((x["model"]-x["outcome"])**2 for x in samples)/n
        market=sum((x["market"]-x["outcome"])**2 for x in samples)/n
        scored[kind]={"n":n,"distinct_target_dates":len(set(x["date"] for x in samples)),
                      "model_brier":round(model,7),"market_brier":round(market,7),
                      "brier_delta_model_minus_kalshi":round(model-market,7),
                      "warning":"Uncertainty intervals and statistical significance not computed; same-game correlated contracts."}
    profit=sum(x["paper_profit_usd"] for x in paper)
    total_cost=sum(x["paper_cost_usd"] for x in paper)
    return {
        "status":"paper_scored" if paper else "no_settled_paper_positions",
        "primary_dates":len(primary),
        "evaluated_unique_contracts":len(markets),
        "counts":dict(counts),
        "source_errors":errors,
        "paper_positions_settled":len(paper),
        "paper_positions":paper,
        "paper_profit_usd":round(profit,6) if paper else None,
        "paper_roi":round(profit/total_cost,6) if total_cost else None,
        "calibration":scored,
        "limitations":[
            "Single primary capture per target game date; capture time varies",
            "Paper returns use frozen implied asks and estimated fees, not fills",
            "Missing Kalshi event fee overrides, latency, price impact, slippage",
            "No point-in-time sportsbook benchmark unless separately supplied",
            "No credible alpha claim until adequate forward outcomes and uncertainty testing"]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",default="forward_evidence",type=Path)
    p.add_argument("--out",default="results/forward_paper_score.json",type=Path)
    args=p.parse_args()
    archives=load_archives(args.base)
    window_records=per_window_archives(archives)
    with requests.Session() as session:
        markets,errors=outcome_cache(window_records,session)
    result=compute(archives,markets,errors)
    grouped=defaultdict(list)
    for archive in window_records:
        grouped[collection_window(archive)].append(archive)
    result["by_collection_window"]={
        window: {
            "target_dates":len(subset),
            "settled_paper_positions":metrics["paper_positions_settled"],
            "paper_profit_usd":metrics["paper_profit_usd"],
            "paper_roi":metrics["paper_roi"],
            "calibration":metrics["calibration"],
            "source_run_ids":[x["source_run_id"] for x in subset],
        }
        for window,subset in grouped.items()
        for metrics in [compute(subset,markets,errors)]
    }
    result["window_comparisons_are_correlated"]=True
    result["window_selection_method"]="One earliest frozen capture per target date per collection window"
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"status":result["status"],"primary_dates":result["primary_dates"],
                      "settled_positions":result["paper_positions_settled"],
                      "moneyline_calibration_n":result["calibration"]["moneyline"]["n"],
                      "total_calibration_n":result["calibration"]["total"]["n"]}),flush=True)

if __name__=="__main__":
    main()
