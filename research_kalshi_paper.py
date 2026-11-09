"""Capture live pregame evidence or score saved research snapshots. No orders."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
import json
from pathlib import Path
import time

import requests

from research_kalshi_contract_match import parse
from research_kalshi_probability_join import join_quote, parse_timestamp
from research_kalshi_schedule_match import CODES, reconcile
from research_kalshi_snapshots import book_bids, collect, get


SERIES = ("KXNHLGAME", "KXNHLTOTAL")


def fee_cents(series, ask):
    if series.get("fee_type") not in ("quadratic", "quadratic_with_maker_fees"):
        return None
    multiplier = series.get("fee_multiplier")
    if multiplier is None or not 0 <= multiplier:
        return None
    price = Decimal(str(ask)) / 100
    # General taker schedule, rounded up to a centicent.
    return float((Decimal(str(multiplier)) * 7 * price * (1 - price))
                 .quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def capture(session, forecasts):
    date = forecasts["target_date"]
    response = session.get("https://api-web.nhle.com/v1/score/" + date, timeout=30)
    response.raise_for_status()
    schedule = response.json()
    games = {g["id"]: g for g in schedule["games"]}
    by_id = {f["game_id"]: f for f in forecasts["forecasts"]}
    rows = []
    for series in SERIES:
        metadata = get(session, "/series/" + series)["series"]
        for market in collect(session, series):
            parsed = parse(market)
            if parsed.get("original_date") != date:
                continue
            ticker = market["ticker"]
            contract = reconcile(market, schedule)
            forecast = by_id.get(contract.get("nhl_game_id"))
            row = {"ticker": ticker, "contract": contract, "market": market,
                   "fee_schedule": {k: metadata.get(k) for k in ("fee_type", "fee_multiplier")}}
            rows.append(row)
            if forecast is None:
                row["reason"] = "no matched forecast"
                continue
            row["forecast"] = forecast
            game = games[forecast["game_id"]]
            if (game.get("gameState") not in ("FUT", "PRE")
                or parse_timestamp(game["startTimeUTC"]) != parse_timestamp(forecast["scheduled_start_utc"])
                or game["homeTeam"]["abbrev"] != forecast["home_team"]
                or game["awayTeam"]["abbrev"] != forecast["away_team"]):
                row["reason"] = "NHL fixture changed or no longer pregame"
                continue
            try:
                book = get(session, "/markets/" + ticker + "/orderbook", {"depth": 1})
                observed = utc_now()
                (bid, _), (no_bid, size) = book_bids(book)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                row["reason"] = "orderbook unavailable: " + str(exc)
                continue
            finally:
                time.sleep(.1)
            ask = float(Decimal(100) - Decimal(str(no_bid))) if no_bid is not None else None
            quote = {"ticker": ticker, "snapshot_kind": "live_orderbook", "observed_at_utc": observed,
                     "yes_ask_implied_cents": ask, "yes_bid_cents": bid, "no_bid_qty": size}
            row["quote"] = quote
            if bid is not None and ask is not None and bid > ask:
                row["reason"] = "crossed orderbook"
                continue
            if series == "KXNHLGAME":
                team = CODES.get(ticker.rsplit("-", 1)[-1])
                name = market.get("yes_sub_title")
                if not name or not (market.get("rules_primary") or "").startswith(f"If {name} wins the "):
                    row["reason"] = "unverified winner settlement rule"
                    continue
                forecast = dict(forecast, selection_ticker=ticker, contract_selection_team=team)
            result = join_quote(contract, quote, forecast, fee_cents(metadata, ask) if ask else None)
            row.update(result)
            if result["status"] == "research_candidate" and forecast.get("starter_shadow"):
                probabilities = forecast["starter_shadow"]
                for variant in ("baseline", "adjusted"):
                    values = probabilities[variant]
                    paired = dict(forecast, p_home_win=values["moneyline"],
                                  p_over_5_5=values["over_5_5"], p_over_6_5=values["over_6_5"])
                    row.setdefault("starter_shadow", {})[variant] = join_quote(
                        contract, quote, paired, result["fee_cents_per_contract"])
            if bid is not None and ask is not None:
                row["market_probability"] = (bid + ask) / 200
    ranked = sorted((r for r in rows if r.get("expected_profit_usd", 0) > 0),
                    key=lambda r: (-r["expected_profit_usd"], r["ticker"]))
    for row in ranked[:5]:
        row["paper_selected"] = True
    for variant in ("baseline", "adjusted"):
        shadow_ranked = sorted((r["starter_shadow"][variant] for r in rows
                               if r.get("starter_shadow", {}).get(variant, {}).get("expected_profit_usd", 0) > 0),
                               key=lambda r: (-r["expected_profit_usd"], r["ticker"]))
        for candidate in shadow_ranked[:5]:
            candidate["paper_selected"] = True
    return {"captured_at_utc": utc_now(), "forecasts": forecasts, "rows": rows,
            "top_five": [r["ticker"] for r in ranked[:5]],
            "counts": dict(Counter(r.get("reason", "evaluated") for r in rows))}


def score(session, capture_data):
    pairs = []
    shadow_pairs = []
    shadow_pnl = Counter()
    shadow_cost = Counter()
    pnl = cost = 0
    settled_paper = 0
    counts = Counter()
    for row in capture_data["rows"]:
        if row.get("status") != "research_candidate":
            counts["excluded"] += 1
            continue
        market = get(session, "/markets/" + row["ticker"])["market"]
        if market.get("status") != "finalized" or market.get("result") not in ("yes", "no"):
            counts["pending_or_nonbinary"] += 1
            continue
        outcome = int(market["result"] == "yes")
        counts["settled"] += 1
        if "market_probability" in row:
            pairs.append((row["model_probability"], row["market_probability"], outcome))
        shadow = row.get("starter_shadow", {})
        if all(shadow.get(k, {}).get("status") == "research_candidate" for k in ("baseline", "adjusted")):
            shadow_pairs.append((shadow["baseline"]["model_probability"],
                                 shadow["adjusted"]["model_probability"], outcome))
            for variant, position in shadow.items():
                if position.get("paper_selected"):
                    entry = (position["yes_ask_cents"] + position["fee_cents_per_contract"]) / 100
                    shadow_cost[variant] += entry
                    shadow_pnl[variant] += outcome - entry
        if row.get("paper_selected"):
            entry = (row["yes_ask_cents"] + row["fee_cents_per_contract"]) / 100
            cost += entry
            pnl += outcome - entry
            settled_paper += 1
    calibration = []
    for index in range(10):
        bucket = [(p, y) for p, _, y in pairs if min(9, int(p * 10)) == index]
        if bucket:
            calibration.append({"bucket": index, "count": len(bucket),
                                "mean_forecast": sum(p for p, _ in bucket) / len(bucket),
                                "actual_rate": sum(y for _, y in bucket) / len(bucket)})
    return {"counts": dict(counts), "paired_brier_count": len(pairs),
            "starter_shadow": {
                "settled_pairs": len(shadow_pairs),
                **{variant: {"brier": sum((p[index] - p[2])**2 for p in shadow_pairs) / len(shadow_pairs)
                             if shadow_pairs else None,
                             "paper_profit_usd": round(shadow_pnl[variant], 6) if shadow_cost[variant] else None,
                             "paper_roi": shadow_pnl[variant] / shadow_cost[variant] if shadow_cost[variant] else None}
                   for index, variant in enumerate(("baseline", "adjusted"))}},
            "model_brier": sum((p-y)**2 for p, _, y in pairs)/len(pairs) if pairs else None,
            "market_brier": sum((p-y)**2 for _, p, y in pairs)/len(pairs) if pairs else None,
            "calibration": calibration, "settled_paper_positions": settled_paper,
            "paper_profit_usd": round(pnl, 6) if settled_paper else None,
            "paper_roi": pnl/cost if cost else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "score"))
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    with requests.Session() as session:
        result = (capture if args.mode == "capture" else score)(session, data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, allow_nan=False)
    print(json.dumps({k: result[k] for k in ("counts", "top_five") if k in result}))
