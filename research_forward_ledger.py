"""Append-only forward NHL/Kalshi research evidence, research-branch only.

Archive public, timestamped NHL/Kalshi research captures together with
source integrity and provenance assessments. Never store sportsbook raw
responses, provider API keys, or private customer data in git.

Archiving is not proof of executable fills or profitable trades.
"""
import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date,datetime,timezone
from pathlib import Path

SCHEMA="nhl_forward_evidence_v1"
RUN_ID=re.compile(r"^[0-9]{1,20}$")

def canonical_bytes(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")

def sha256(obj):
    return hashlib.sha256(canonical_bytes(obj)).hexdigest()

def parse_time(value):
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timestamp must have an explicit UTC offset")
    return stamp.astimezone(timezone.utc)

def compact_public_capture(capture):
    """Remove redundant Kalshi market metadata while preserving replay inputs.

    The full original capture remains downloadable in the Actions artifact
    for its retention window. The long-term ledger stores all candidate
    contracts, observed quote sides, fees, forecast and scoring labels,
    but not a duplicate full market response per side.
    """
    keep=("ticker","contract","forecast","quote","contract_side","fee_schedule",
          "status","reason","model_probability","market_probability",
          "expected_profit_usd","expected_roi","ask_cents","yes_ask_cents",
          "fee_cents_per_contract","breakeven_probability","quote_quantity",
          "paper_selected","starter_shadow","starter_input_types")
    reduced={k:v for k,v in capture.items() if k!="rows"}
    reduced["rows"]=[{k:row[k] for k in keep if k in row}
                     for row in capture.get("rows",[])]
    return reduced

def make_archive(capture,audit,benchmark,run_id):
    if not RUN_ID.fullmatch(str(run_id)):
        raise ValueError("GitHub run id must be numeric")
    target=capture.get("forecasts",{}).get("target_date")
    if not isinstance(target,str) or date.fromisoformat(target).isoformat()!=target:
        raise ValueError("Missing ISO NHL target date")
    captured=parse_time(capture["captured_at_utc"])
    predictions=capture["forecasts"].get("forecasts",[])
    if not predictions:
        raise ValueError("Refusing empty forecast capture")
    if audit.get("overall_status")=="invalid" or audit.get("forecast_status_counts",{}).get("invalid",0):
        raise ValueError("PIT audit rejected this capture")
    audit_forecasts={str(row["game_id"]):row for row in audit.get("forecasts",[])}
    if len(audit_forecasts)!=len(predictions):
        raise ValueError("Incomplete forecast audit")
    for p in predictions:
        if audit_forecasts.get(str(p["game_id"]),{}).get("status")!="operational_pregame_only":
            raise ValueError("Forecast lacks operational pregame audit")
        if parse_time(p["generated_at_utc"])>captured:
            raise ValueError("Forecast timestamp after market capture")
    if benchmark.get("status") not in ("paired","no_paired_benchmark"):
        raise ValueError("Invalid sportsbook benchmark metadata")
    if audit.get("quote_status_counts",{}).get("invalid",0):
        raise ValueError("Invalid pregame quotes")
    selected=[x for x in capture.get("rows",[]) if x.get("paper_selected")]
    # The earlier selection policy chooses at most one contract per economic exposure.
    for row in selected:
        if row.get("status")!="research_candidate" or row.get("expected_profit_usd",0)<=0:
            raise ValueError("Invalid paper selection")
    return {
        "schema":SCHEMA,
        "source_run_id":str(run_id),
        "target_date":target,
        "captured_at_utc":captured.isoformat(),
        "capture_sha256":sha256(compact_public_capture(capture)),
        "original_capture_sha256":sha256(capture),
        "capture":compact_public_capture(capture),
        "audit_summary":{
            "overall_status":audit["overall_status"],
            "forecast_status_counts":audit.get("forecast_status_counts",{}),
            "quote_status_counts":audit.get("quote_status_counts",{}),
            "historical_backtest_point_in_time_verified":False},
        # Only store metadata about the sportsbook source, not paid quote content.
        "sportsbook_summary":{
            "status":benchmark["status"],
            "paired_games":benchmark.get("paired_games",0),
            "comparison_count":benchmark.get("comparison_count",0),
            "benchmark_sha256":sha256(benchmark)},
        "selected_count":len(selected),
        "model_probabilities_not_verified_as_edge":True,
        "execution_status":"research_only_no_trades"
    }

def write_archive(capture_path,audit_path,benchmark_path,run_id,base):
    capture=json.loads(Path(capture_path).read_text())
    audit=json.loads(Path(audit_path).read_text())
    benchmark=json.loads(Path(benchmark_path).read_text())
    archived=make_archive(capture,audit,benchmark,run_id)
    path=Path(base)/archived["target_date"]/(str(run_id)+".json")
    path.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive create forbids silent re-archiving or rewriting a frozen result.
    with path.open("x",encoding="utf-8") as stream:
        json.dump(archived,stream,sort_keys=True,indent=2,allow_nan=False)
    return path

def load_archives(base):
    records=[]
    for path in sorted(Path(base).glob("*/*.json")):
        record=json.loads(path.read_text())
        if record.get("schema")!=SCHEMA:
            raise ValueError("Unknown archive schema: "+str(path))
        if sha256(record.get("capture"))!=record.get("capture_sha256"):
            raise ValueError("Archived capture checksum mismatch: "+str(path))
        if path.stem!=str(record["source_run_id"]) or path.parent.name!=record["target_date"]:
            raise ValueError("Archive location and source identity mismatch: "+str(path))
        records.append(record)
    return records

def report(base):
    records=load_archives(base)
    by_date={}
    for record in records:
        date_=record["target_date"]
        if date_ not in by_date or parse_time(record["captured_at_utc"])<parse_time(by_date[date_]["captured_at_utc"]):
            by_date[date_]=record
    primary=sorted(by_date.values(),key=lambda x:x["target_date"])
    return {
        "schema":"nhl_forward_ledger_summary_v1",
        "archived_snapshots":len(records),
        "primary_target_dates":len(primary),
        "primary_selection_rule":"Earliest successful capture of each target date; research-only until fixed collection time is established",
        "primary_run_ids":[r["source_run_id"] for r in primary],
        "primary_candidates":sum(sum(x.get("status")=="research_candidate"
                          for x in r["capture"].get("rows",[])) for r in primary),
        "primary_selected_positions":sum(r["selected_count"] for r in primary),
        "primary_sportsbook_paired_games":sum(r["sportsbook_summary"]["paired_games"] for r in primary),
        "primary_dates":[{"date":r["target_date"],"run_id":r["source_run_id"],
                          "captured_at_utc":r["captured_at_utc"],
                          "paper_positions":r["selected_count"],
                          "sportsbook_paired_games":r["sportsbook_summary"]["paired_games"]}
                         for r in primary],
        "realized_paper_pnl":None,
        "not_yet_verified":["No completed settlement data assembled in this ledger",
                            "No fill or slippage evidence",
                            "Historical feature publication vintages incomplete",
                            "Variable capture times prevent claiming a fixed daily forward strategy"]
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("archive")
    a.add_argument("--capture",required=True,type=Path)
    a.add_argument("--audit",required=True,type=Path)
    a.add_argument("--benchmark",required=True,type=Path)
    a.add_argument("--run-id",required=True)
    a.add_argument("--base",default="forward_evidence",type=Path)
    b=sub.add_parser("summary")
    b.add_argument("--base",default="forward_evidence",type=Path)
    b.add_argument("--out",default="results/forward_ledger_summary.json",type=Path)
    args=p.parse_args()
    if args.mode=="archive":
        path=write_archive(args.capture,args.audit,args.benchmark,args.run_id,args.base)
        print(json.dumps({"status":"archived","path":str(path)}),flush=True)
    else:
        output=report(args.base)
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(output,indent=2),encoding="utf-8")
        print(json.dumps({"snapshots":output["archived_snapshots"],
                          "primary_dates":output["primary_target_dates"],
                          "selected":output["primary_selected_positions"]}),flush=True)

if __name__=="__main__":
    main()
