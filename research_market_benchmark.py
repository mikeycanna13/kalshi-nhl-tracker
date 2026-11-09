"""Point-in-time NHL sportsbook consensus benchmark (research only).

Accepts an immutable The Odds API v4 snapshot and an immutable Kalshi capture.
Does NOT backfill current odds into historical timestamps, infer missing odds,
train a model, or place any orders. No subscription is needed to run this module
on user-supplied historical data. Data acquisition is separate.
"""
import argparse
import json
import hashlib
import math
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

# NHL names are matched explicitly to prevent accidental cross-game joins.
NAMES = {
    "Anaheim Ducks":"ANA", "Boston Bruins":"BOS", "Buffalo Sabres":"BUF",
    "Carolina Hurricanes":"CAR", "Columbus Blue Jackets":"CBJ",
    "Calgary Flames":"CGY", "Chicago Blackhawks":"CHI",
    "Colorado Avalanche":"COL", "Dallas Stars":"DAL", "Detroit Red Wings":"DET",
    "Edmonton Oilers":"EDM", "Florida Panthers":"FLA", "Los Angeles Kings":"LAK",
    "Minnesota Wild":"MIN", "Montreal Canadiens":"MTL", "New Jersey Devils":"NJD",
    "Nashville Predators":"NSH", "New York Islanders":"NYI", "New York Rangers":"NYR",
    "Ottawa Senators":"OTT", "Philadelphia Flyers":"PHI",
    "Pittsburgh Penguins":"PIT", "Seattle Kraken":"SEA", "San Jose Sharks":"SJS",
    "St. Louis Blues":"STL", "Tampa Bay Lightning":"TBL", "Toronto Maple Leafs":"TOR",
    "Utah Hockey Club":"UTA", "Utah Mammoth":"UTA", "Utah HC":"UTA",
    "Vancouver Canucks":"VAN", "Vegas Golden Knights":"VGK",
    "Winnipeg Jets":"WPG", "Washington Capitals":"WSH"
}

def aware(value):
    if not isinstance(value,str):
        raise ValueError("Missing timestamp")
    x=datetime.fromisoformat(value.replace("Z","+00:00"))
    if x.tzinfo is None or x.utcoffset() is None:
        raise ValueError("Timezone required")
    return x.astimezone(timezone.utc)

def implied_probability(decimal_price):
    value=float(decimal_price)
    if not math.isfinite(value) or not 1.001 < value <= 1000:
        raise ValueError("Invalid positive decimal odds")
    return 1.0/value

def valid_book_probability(book,home,away,snapshot_time,quote_time,max_age_seconds):
    # The Odds API v4 bookmakers[].markets[] uses decimal prices, even for US teams.
    if not book.get("key"):
        return None
    candidate=[]
    for market in book.get("markets",[]):
        if market.get("key")!="h2h":
            continue
        try:
            updated=aware(market.get("last_update") or book.get("last_update"))
            if updated > snapshot_time or updated > quote_time:
                continue
            if (quote_time-updated).total_seconds() > max_age_seconds:
                continue
            outcomes=market.get("outcomes",[])
            if len(outcomes)!=2:
                continue # 3-way regulation draw is not an NHL full-game moneyline
            prices={NAMES.get(x.get("name")):x.get("price") for x in outcomes}
            if set(prices)!={home,away}:
                continue
            ih=implied_probability(prices[home])
            ia=implied_probability(prices[away])
            total=ih+ia
            if not 1.0 <= total <= 1.25:
                continue
            candidate.append((updated,ih/total,total))
        except (ValueError, TypeError, OverflowError):
            continue
    if not candidate:
        return None
    _,fair,overround=max(candidate,key=lambda x:x[0])
    return {"bookmaker":book["key"],"fair_home":fair,
            "overround":overround}

def benchmark_game(forecast,kalshi_quote_utc,snapshot,min_books=3,
                   max_age_minutes=15,commence_tolerance_minutes=30):
    """Fail closed if odds, timestamps, event IDs or independent books are weak."""
    base={"game_id":forecast.get("game_id"),"status":"unavailable"}
    try:
        start=aware(forecast["scheduled_start_utc"])
        forecast_at=aware(forecast["generated_at_utc"])
        quote_at=aware(kalshi_quote_utc)
        snapshot_at=aware(snapshot["timestamp"])
    except (KeyError, ValueError, TypeError):
        return dict(base,reason="missing or invalid as-of timestamps")
    if not (forecast_at <= snapshot_at <= quote_at < start):
        return dict(base,reason="future or post-puckdrop sportsbook/model snapshot")
    if (quote_at-snapshot_at).total_seconds()>max_age_minutes*60:
        return dict(base,reason="sportsbook snapshot too stale relative to Kalshi quote")
    if snapshot.get("source") not in ("the_odds_api_historical","the_odds_api_live"):
        return dict(base,reason="unknown sportsbook snapshot provenance")
    home,away=forecast.get("home_team"),forecast.get("away_team")
    if not (home and away and home!=away):
        return dict(base,reason="invalid NHL team identifiers")
    matching=[]
    for event in snapshot.get("data",[]):
        if NAMES.get(event.get("home_team"))!=home or NAMES.get(event.get("away_team"))!=away:
            continue
        try:
            commence=aware(event["commence_time"])
        except (ValueError,TypeError,KeyError):
            continue
        if abs((commence-start).total_seconds())<=commence_tolerance_minutes*60:
            matching.append(event)
    if len(matching)!=1:
        return dict(base,reason="no unique NHL event mapping",events_matched=len(matching))
    event=matching[0]
    books={}
    for book in event.get("bookmakers",[]):
        p=valid_book_probability(book,home,away,snapshot_at,quote_at,max_age_minutes*60)
        if p is not None:
            books[p["bookmaker"]]=p # one contemporaneous market per bookmaker
    if len(books)<min_books:
        return dict(base,reason="insufficient fresh independent bookmaker quotes",
                    qualifying_books=len(books),minimum_books=min_books)
    probs=[p["fair_home"] for p in books.values()]
    model=float(forecast.get("p_home_win",float("nan")))
    if not math.isfinite(model) or not 0<=model<=1:
        return dict(base,reason="invalid NHL model home-win probability")
    fair=median(probs)
    return {"status":"paired","game_id":forecast["game_id"],"home_team":home,
            "away_team":away,"event_id":event["id"],
            "forecast_at_utc":forecast_at.isoformat(),
            "sportsbook_snapshot_at_utc":snapshot_at.isoformat(),
            "kalshi_quote_at_utc":quote_at.isoformat(),
            "scheduled_start_utc":start.isoformat(),
            "model_home_probability":model,
            "sportsbook_fair_home_probability":round(fair,8),
            "model_minus_consensus":round(model-fair,8),
            "sportsbook_dispersion":round(max(probs)-min(probs),8),
            "bookmakers":sorted(books),"bookmaker_count":len(books),
            "method":"Median of bookmaker two-way proportional de-vig probabilities, point-in-time and no future quotes",
            "warning":"Bookmakers may share information; no evidence of model profitability"}

def compare_capture(capture,snapshot,min_books=3,max_age_minutes=15):
    """One game/quote pair per game; do not treat YES and NO as independent samples."""
    by_game={}
    for row in capture.get("rows",[]):
        contract=row.get("contract") or {}
        forecast=row.get("forecast") or {}
        quote=row.get("quote") or {}
        if contract.get("market_type")!="moneyline" or not forecast or not quote.get("observed_at_utc"):
            continue
        game_id=forecast.get("game_id")
        if game_id is None:
            continue
        existing=by_game.get(game_id)
        # Compare against the earliest corresponding Kalshi capture quote.
        try:
            ts=aware(quote["observed_at_utc"])
            if existing and ts>=aware(existing["quote"]["observed_at_utc"]):
                continue
        except ValueError:
            continue
        by_game[game_id]={"forecast":forecast,"quote":quote}
    pairs=[]
    for game_id,item in sorted(by_game.items()):
        pairs.append(benchmark_game(item["forecast"],item["quote"]["observed_at_utc"],
                                    snapshot,min_books=min_books,max_age_minutes=max_age_minutes))
    return {"status":"paired" if any(x["status"]=="paired" for x in pairs) else "no_paired_benchmark",
            "comparison_count":len(pairs),
            "paired_games":sum(x["status"]=="paired" for x in pairs),
            "comparisons":pairs,
            "limitations":["No odds source is fabricated if historical data is unavailable",
                           "No training or model blending is performed",
                           "No sportsbook or Kalshi executions are assumed"]}

def score_settled(comparisons,final_results,bootstrap_samples=1000,seed=2026):
    """Time-matched proper scoring with game-date block-bootstrap intervals.

    Statistical intervals are withheld for very small samples. They describe
    one frozen model/policy and DO NOT correct for repeated model selection.
    """
    lookup={str(g["game_id"]):g for g in final_results}
    scored=[]
    for pair in comparisons.get("comparisons",[]):
        if pair["status"]!="paired":
            continue
        result=lookup.get(str(pair["game_id"]))
        if result is None or result.get("status")!="final":
            continue
        winner=result.get("winner")
        if winner not in (pair["home_team"],pair["away_team"]):
            continue
        outcome=int(winner==pair["home_team"])
        model=pair["model_home_probability"]
        market=pair["sportsbook_fair_home_probability"]
        day=pair["scheduled_start_utc"][:10]
        scored.append((model,market,outcome,day))
    if not scored:
        return {"status":"not_evaluable","settled_games":0,
                "reason":"No verified finalized outcomes"}
    def loss(prob,outcome):
        p=min(1-1e-12,max(1e-12,prob))
        return -(outcome*math.log(p)+(1-outcome)*math.log(1-p))
    def stats(rows):
        n=len(rows)
        return {
            "model_brier":sum((m-y)**2 for m,_,y,_ in rows)/n,
            "sportsbook_brier":sum((p-y)**2 for _,p,y,_ in rows)/n,
            "model_log_loss":sum(loss(m,y) for m,_,y,_ in rows)/n,
            "sportsbook_log_loss":sum(loss(p,y) for _,p,y,_ in rows)/n}
    metrics=stats(scored)
    metrics["brier_delta_model_minus_sportsbook"]=(metrics["model_brier"]-
                                                    metrics["sportsbook_brier"])
    metrics["log_loss_delta_model_minus_sportsbook"]=(metrics["model_log_loss"]-
                                                       metrics["sportsbook_log_loss"])
    dates=defaultdict(list)
    for row in scored:
        dates[row[3]].append(row)
    interval=None
    if len(scored)>=50 and len(dates)>=20 and bootstrap_samples>=100:
        groups=list(dates.values())
        rng=random.Random(seed)
        deltas=[]
        log_deltas=[]
        for _ in range(bootstrap_samples):
            sample=[item for _ in range(len(groups))
                    for item in rng.choice(groups)]
            draw=stats(sample)
            deltas.append(draw["model_brier"]-draw["sportsbook_brier"])
            log_deltas.append(draw["model_log_loss"]-draw["sportsbook_log_loss"])
        deltas.sort();log_deltas.sort()
        lo=int(.025*bootstrap_samples)
        hi=min(bootstrap_samples-1,int(.975*bootstrap_samples))
        interval={"method":"game-date block bootstrap, fixed model",
                  "samples":bootstrap_samples,"dates":len(dates),
                  "brier_delta_95pct":[deltas[lo],deltas[hi]],
                  "log_loss_delta_95pct":[log_deltas[lo],log_deltas[hi]]}
    return {"status":"scored","settled_games":len(scored),
            "distinct_game_dates":len(dates),**metrics,
            "research_interval":interval,
            "interval_status":"available" if interval else "insufficient games/dates",
            "warning":"Negative delta favors model. Descriptive research only; model-selection bias, multiple testing, and trade execution are NOT accounted for. No demonstrated ROI."}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture",required=True,type=Path)
    p.add_argument("--odds-snapshot",required=True,type=Path)
    p.add_argument("--output",default="results/sportsbook_benchmark.json",type=Path)
    p.add_argument("--final-results",type=Path,help="Optional independently sourced finalized game outcomes JSON")
    p.add_argument("--max-age-minutes",type=int,default=15)
    p.add_argument("--min-books",type=int,default=3)
    args=p.parse_args()
    if args.max_age_minutes<=0 or args.min_books<2:
        p.error("Require positive max age and >=2 bookmakers")
    capture_bytes=args.capture.read_bytes()
    odds_bytes=args.odds_snapshot.read_bytes()
    capture=json.loads(capture_bytes)
    odds=json.loads(odds_bytes)
    report=compare_capture(capture,odds,args.min_books,args.max_age_minutes)
    report["capture_sha256"]=hashlib.sha256(capture_bytes).hexdigest()
    report["sportsbook_snapshot_sha256"]=hashlib.sha256(odds_bytes).hexdigest()
    if args.final_results:
        final_data=json.loads(args.final_results.read_text(encoding="utf-8"))
        if not isinstance(final_data,list):
            raise ValueError("Final results must be a JSON list of independently verified game outcomes")
        report["outcome_evaluation"]=score_settled(report,final_data)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"status":report["status"],"paired_games":report["paired_games"],
                      "comparison_count":report["comparison_count"]}),flush=True)

if __name__=="__main__":
    main()
