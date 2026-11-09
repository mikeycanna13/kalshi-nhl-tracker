"""Conservative point-in-time provenance audit for NHL/Kalshi research captures.

Separate operational pregame validation from historical reproducibility.
A live forecast can have valid pregame ordering yet lack vintaged feature data
needed to replay the same game from a historical point in time.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
import re

_SHA256=re.compile(r"^[0-9a-f]{64}$")

def utc(text):
    if not isinstance(text,str):
        raise ValueError("missing time")
    x=datetime.fromisoformat(text.replace("Z","+00:00"))
    if x.tzinfo is None or x.utcoffset() is None:
        raise ValueError("timezone required")
    return x.astimezone(timezone.utc)

def audit_forecast(record):
    reasons=[]
    game_id=record.get("game_id")
    try:
        start=utc(record["scheduled_start_utc"])
        generated=utc(record["generated_at_utc"])
        cutoff=utc(record["model_trained_through_utc"])
        loaded=utc(record["training_source_loaded_at_utc"])
        game_date=datetime.strptime(record["date"],"%Y-%m-%d").date()
        last_training_date=datetime.strptime(record["last_training_game_date"],"%Y-%m-%d").date()
    except (KeyError,TypeError,ValueError):
        return {"game_id":game_id,"status":"invalid","reasons":["missing or malformed timestamps / training dates"]}
    if not (loaded<=cutoff<=generated<start):
        reasons.append("training source, model cutoff or forecast occurs after allowed time")
    if not last_training_date<game_date:
        reasons.append("training includes same-day or future games by date")
    if record.get("pregame_verified") is not True:
        reasons.append("pregame verification flag absent")
    sha=record.get("training_source_sha256")
    if not isinstance(sha,str) or not _SHA256.fullmatch(sha):
        reasons.append("missing immutable training source SHA256")
    if record.get("training_source_type")!="nhl_completed_game_scores":
        reasons.append("unrecognized training source type")
    if reasons:
        return {"game_id":game_id,"status":"invalid","reasons":reasons}
    # Do not claim exact historical replay: game publication timestamps, xG
    # vintages, injury revision history and original quote timestamps are separate.
    return {"game_id":game_id,"status":"operational_pregame_only",
            "historical_replay_verified":False,
            "data_sha256":sha,
            "model_code_commit":record.get("model_code_commit"),
            "limitations":["Game rows verified by date only, not original publication time",
                           "Source version downloaded at forecast time; older vintages not reconstructed",
                           "Historical goalie/xG/lineup publication vintages not established"]}

def audit_quote(row):
    if row.get("status")!="research_candidate":
        return {"status":"not_scored","reason":"not a model research candidate"}
    forecast=row.get("forecast") or {}
    quote=row.get("quote") or {}
    try:
        observed=utc(quote["observed_at_utc"])
        generated=utc(forecast["generated_at_utc"])
        start=utc(forecast["scheduled_start_utc"])
    except (ValueError,TypeError,KeyError):
        return {"status":"invalid","reason":"missing pregame quote timestamps"}
    if not generated<=observed<start:
        return {"status":"invalid","reason":"quote is future relative to forecast or at/after puck drop"}
    if quote.get("snapshot_kind")!="live_orderbook":
        return {"status":"invalid","reason":"quote is not a live orderbook observation"}
    # Preserve the uncertainty on the fee calculation, rather than declaring
    # all prices executable or fees proven.
    schedule=row.get("fee_schedule") or {}
    if schedule.get("fee_type") not in ("quadratic","quadratic_with_maker_fees"):
        return {"status":"conditional","reason":"unknown series fee schedule"}
    return {"status":"conditional",
            "reason":"Pregame quote ordering verified; event-level fee overrides, fills, and slippage remain unverified"}

def audit_capture(capture):
    forecast_data=capture.get("forecasts") or {}
    records=[audit_forecast(x) for x in forecast_data.get("forecasts",[])]
    rows=[audit_quote(r) for r in capture.get("rows",[])]
    forecast_counts=Counter(x["status"] for x in records)
    quote_counts=Counter(x["status"] for x in rows)
    return {"overall_status":"invalid" if forecast_counts["invalid"] or quote_counts["invalid"] else "conditional",
            "forecast_count":len(records),"quote_row_count":len(rows),
            "forecast_status_counts":dict(forecast_counts),
            "quote_status_counts":dict(quote_counts),
            "forecasts":records,"quote_audits":rows,
            "historical_backtest_point_in_time_verified":False,
            "not_covered":["Historical odds not available unless supplied separately",
                           "No source-vintage time machine for historical xG or injuries",
                           "No event-level fee override check",
                           "No measured fill, slippage, or latency"],
            "conclusion":"Operational pregame ordering is not proof of reproducible historical inputs or positive expected value"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("capture",type=Path)
    p.add_argument("--out",default="results/asof_audit.json",type=Path)
    args=p.parse_args()
    result=audit_capture(json.loads(args.capture.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print("NHL_ASOF_AUDIT="+json.dumps({k:result[k] for k in (
        "overall_status","forecast_status_counts","quote_status_counts")}),flush=True)
    if result["overall_status"]=="invalid":
        raise RuntimeError("Invalid point-in-time source or quote evidence")

if __name__=="__main__":
    main()
