"""Export audit-friendly research results from an immutable Kalshi capture.

No trades, fills, or forecasts are generated here. This only reformats
timestamped predictions and quote evidence already recorded in the capture.
"""
import argparse
import csv
import json
from pathlib import Path

FIELDS = ["ticker","side","market_type","nhl_game_id","game_date","home_team","away_team",
          "scheduled_start_utc","quote_observed_at_utc","forecast_generated_at_utc",
          "model_probability","market_midpoint_probability","implied_ask_cents",
          "fee_cents_per_contract","break_even_probability","ev_per_contract_usd",
          "roi_estimate","ask_side_depth","paper_selected","status","reason"]


def make_rows(capture):
    result = []
    for row in capture.get("rows", []):
        forecast = row.get("forecast") or {}
        contract = row.get("contract") or {}
        quote = row.get("quote") or {}
        result.append({
            "ticker": row.get("ticker"), "side": row.get("contract_side"),
            "market_type": contract.get("market_type"),
            "nhl_game_id": contract.get("nhl_game_id"),
            "game_date": forecast.get("date"),
            "home_team": forecast.get("home_team"),
            "away_team": forecast.get("away_team"),
            "scheduled_start_utc": forecast.get("scheduled_start_utc"),
            "quote_observed_at_utc": quote.get("observed_at_utc"),
            "forecast_generated_at_utc": forecast.get("generated_at_utc"),
            "model_probability": row.get("model_probability"),
            "market_midpoint_probability": row.get("market_probability"),
            "implied_ask_cents": row.get("ask_cents", row.get("yes_ask_cents")),
            "fee_cents_per_contract": row.get("fee_cents_per_contract"),
            "break_even_probability": row.get("breakeven_probability"),
            "ev_per_contract_usd": row.get("expected_profit_usd"),
            "roi_estimate": row.get("expected_roi"),
            "ask_side_depth": row.get("quote_quantity"),
            "paper_selected": bool(row.get("paper_selected")),
            "status": row.get("status", "skipped"),
            "reason": row.get("reason", "")})
    return result


def render_markdown(capture, rows, benchmark=None, audit=None):
    valid = [r for r in rows if r["status"] == "research_candidate"]
    ranked = sorted((r for r in valid if (r["ev_per_contract_usd"] or 0) > 0),
                    key=lambda r: -r["ev_per_contract_usd"])
    chosen = [r for r in ranked if r["paper_selected"]]
    if not chosen:
        # A legacy capture may not include a paper portfolio.
        chosen = ranked
    date = capture.get("forecasts", {}).get("target_date", "unknown")
    lines = [f"# NHL/Kalshi pregame research — {date}", "",
             f"Captured: {capture.get('captured_at_utc', 'unknown')}", "",
             f"Markets / sides captured: {len(rows)}; validated sides: {len(valid)}; "
             f"positive-EV sides: {len(ranked)}; unique top paper positions: {len(chosen[:5])}.", "",
             "## Top five modeled opportunities", "",
             "| Side | Market | Model P | Ask | Fee | Break-even P | Model EV / contract | Depth |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in chosen[:5]:
        lines.append("| {side} | `{ticker}` | {prob:.2%} | {ask:.2f}¢ | {fee:.2f}¢ | "
                     "{breakeven:.2%} | ${ev:+.4f} | {depth:g} |".format(
                         side=r["side"].upper(), ticker=r["ticker"],
                         prob=r["model_probability"],
                         ask=r["implied_ask_cents"],
                         fee=r["fee_cents_per_contract"],
                         breakeven=r["break_even_probability"],
                         ev=r["ev_per_contract_usd"],
                         depth=r["ask_side_depth"]))
    if not ranked:
        lines.append("| — | No positive modeled EV with a validated quote | — | — | — | — | — | — |")
    if benchmark is not None:
        lines += ["", "## Independent market benchmark", "",
                  f"Paired games with fresh sportsbook consensus: **{benchmark.get('paired_games',0)}** / "
                  f"{benchmark.get('comparison_count',0)} researched games.", ""]
        if benchmark.get("paired_games",0)==0:
            lines.append("**No validated sportsbook comparison is available. Positive model EV is NOT evidence of market-beating accuracy.**")
        else:
            lines.append("Market-relative estimates are preliminary; outcome scoring requires independently finalized games.")
    if audit is not None:
        statuses=audit.get("forecast_status_counts",{})
        lines += ["", "## Point-in-time audit", "",
                  f"Audit status: **{audit.get('overall_status','unknown')}**; operational pregame forecasts: "
                  f"{statuses.get('operational_pregame_only',0)}; "
                  "historical source-vintage replay: **not verified**.", ""]
    lines += ["", "## Method and limitations", "",
              "All prices come from frozen pregame public orderbook snapshots.",
              "The ask is inferred from opposite-side bid depth; it is **not** a verified fill.",
              "Fee estimates use the series-level fee metadata for one taker contract.",
              "Returns are model-based expectations, **not realized profit**, and omit slippage.",
              "Model probabilities have not demonstrated statistically significant market-beating performance.",
              "Every scored outcome must be compared to an independently verified final settlement.",
              "Excluded markets, negative EV and missing bids are retained in the CSV audit trail.", ""]
    return "\n".join(lines)


def export(capture, csv_path, markdown_path, benchmark=None, audit=None):
    rows = make_rows(capture)
    csv_path, markdown_path = Path(csv_path), Path(markdown_path)
    csv_path.parent.mkdir(parents=True,exist_ok=True)
    markdown_path.parent.mkdir(parents=True,exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    markdown_path.write_text(render_markdown(capture,rows,benchmark,audit),encoding="utf-8")
    return {"rows":len(rows),"evaluated":sum(r["status"]=="research_candidate" for r in rows),
            "positive_ev":sum((r["ev_per_contract_usd"] or 0)>0 for r in rows)}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("capture",type=Path)
    parser.add_argument("--csv",type=Path,default=Path("results/paper_report.csv"))
    parser.add_argument("--markdown",type=Path,default=Path("results/paper_report.md"))
    parser.add_argument("--benchmark",type=Path)
    parser.add_argument("--audit",type=Path)
    args=parser.parse_args()
    capture=json.loads(args.capture.read_text(encoding="utf-8"))
    benchmark=json.loads(args.benchmark.read_text(encoding="utf-8")) if args.benchmark else None
    audit=json.loads(args.audit.read_text(encoding="utf-8")) if args.audit else None
    print(json.dumps(export(capture,args.csv,args.markdown,benchmark,audit)),flush=True)
