"""Capture live pregame evidence or score saved research snapshots. No orders."""
import argparse
from collections import Counter, defaultdict
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



def economic_exposure(row):
    """Collapse contracts representing the same NHL outcome, including YES/NO complements."""
    contract = row.get("contract") or {}
    side = row.get("contract_side")
    game = contract.get("nhl_game_id")
    kind = contract.get("market_type")
    if kind == "moneyline":
        forecast = row.get("forecast") or {}
        selected = forecast.get("contract_selection_team")
        home, away = contract.get("home_team"), contract.get("away_team")
        if selected not in (home,away) or side not in ("yes","no"):
            return ("unknown", row.get("ticker"), side)
        winning_team = selected if side == "yes" else (away if selected == home else home)
        return ("winner",game,winning_team)
    if kind == "total":
        return ("total",game,contract.get("threshold"),side)
    return ("contract",row.get("ticker"),side)


def rank_unique_exposures(rows, variant=None):
    """Take the highest modeled EV quote for each unique underlying payout."""
    selected = {}
    for row in rows:
        position = (row.get("starter_shadow") or {}).get(variant) if variant else row
        if not position or position.get("status") != "research_candidate":
            continue
        if position.get("expected_profit_usd",0) <= 0:
            continue
        key = economic_exposure(row)
        previous = selected.get(key)
        def preference(entry):
            p = (entry.get("starter_shadow") or {}).get(variant) if variant else entry
            return (p["expected_profit_usd"], p.get("quote_quantity",0))
        if previous is None or preference(row) > preference(previous):
            selected[key]=row
    return sorted(selected.values(),key=lambda r: (
        -((r.get("starter_shadow") or {}).get(variant) if variant else r)["expected_profit_usd"],
        -((r.get("starter_shadow") or {}).get(variant) if variant else r).get("quote_quantity",0),
        r["ticker"],r.get("contract_side","yes")))


def capture(session, forecasts):
    """Capture both YES and NO actionable sides without inventing executable fills."""
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
            base_row = {"ticker": ticker, "contract": contract, "market": market,
                        "fee_schedule": {k: metadata.get(k) for k in ("fee_type", "fee_multiplier")}}
            if forecast is None:
                rows.append(dict(base_row, reason="no matched forecast"))
                continue
            game = games.get(forecast["game_id"])
            if (not game or game.get("gameState") not in ("FUT", "PRE")
                or parse_timestamp(game["startTimeUTC"]) != parse_timestamp(forecast["scheduled_start_utc"])
                or game["homeTeam"]["abbrev"] != forecast["home_team"]
                or game["awayTeam"]["abbrev"] != forecast["away_team"]):
                rows.append(dict(base_row, reason="NHL fixture changed or no longer pregame"))
                continue
            try:
                book = get(session, "/markets/" + ticker + "/orderbook", {"depth": 1})
                observed = utc_now()
                (yes_bid, yes_size), (no_bid, no_size) = book_bids(book)
            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                rows.append(dict(base_row, reason="orderbook unavailable: " + str(exc)))
                continue
            finally:
                time.sleep(.1)
            yes_ask = float(Decimal(100) - Decimal(str(no_bid))) if no_bid is not None else None
            no_ask = float(Decimal(100) - Decimal(str(yes_bid))) if yes_bid is not None else None
            quote = {"ticker": ticker, "snapshot_kind": "live_orderbook",
                     "observed_at_utc": observed, "yes_bid_cents": yes_bid,
                     "no_bid_cents": no_bid, "yes_ask_implied_cents": yes_ask,
                     "no_ask_implied_cents": no_ask, "yes_bid_qty": yes_size,
                     "no_bid_qty": no_size}
            if (yes_bid is not None and yes_ask is not None and yes_bid > yes_ask) or (
                    no_bid is not None and no_ask is not None and no_bid > no_ask):
                rows.append(dict(base_row, quote=quote, reason="crossed orderbook"))
                continue
            selection = {}
            if series == "KXNHLGAME":
                team = CODES.get(ticker.rsplit("-", 1)[-1])
                name = market.get("yes_sub_title")
                if not name or not (market.get("rules_primary") or "").startswith(f"If {name} wins the "):
                    rows.append(dict(base_row, quote=quote, reason="unverified winner settlement rule"))
                    continue
                selection = {"selection_ticker": ticker, "contract_selection_team": team}
            chosen_forecast = dict(forecast, **selection)
            for side, price in (("yes", yes_ask), ("no", no_ask)):
                row = dict(base_row, forecast=chosen_forecast, quote=quote, contract_side=side)
                result = join_quote(contract, quote, chosen_forecast,
                                    fee_cents(metadata, price) if price is not None else None, side=side)
                row.update(result)
                if result["status"] == "research_candidate" and forecast.get("starter_shadow"):
                    probabilities = forecast["starter_shadow"]
                    row["starter_input_types"] = {
                        team_side: entry[0]
                        for team_side, entry in probabilities.get("starter_inputs", {}).items()}
                    for variant in ("baseline", "adjusted"):
                        values = probabilities[variant]
                        paired = dict(chosen_forecast, p_home_win=values["moneyline"],
                                      p_over_5_5=values["over_5_5"],
                                      p_over_6_5=values["over_6_5"])
                        row.setdefault("starter_shadow", {})[variant] = join_quote(
                            contract, quote, paired, result["fee_cents_per_contract"], side=side)
                if yes_bid is not None and yes_ask is not None:
                    midpoint_yes = (yes_bid + yes_ask) / 200
                    row["market_probability"] = midpoint_yes if side == "yes" else 1 - midpoint_yes
                rows.append(row)
    ranked = rank_unique_exposures(rows)
    for row in ranked[:5]:
        row["paper_selected"] = True
    for variant in ("baseline", "adjusted"):
        for row in rank_unique_exposures(rows,variant)[:5]:
            row["starter_shadow"][variant]["paper_selected"] = True
    return {"captured_at_utc": utc_now(), "forecasts": forecasts, "rows": rows,
            "top_five": [{"ticker": r["ticker"], "side": r["contract_side"],
                          "expected_profit_usd": r["expected_profit_usd"]}
                         for r in ranked[:5]],
            "unique_positive_exposures": len(ranked),
            "counts": dict(Counter(r.get("reason", "evaluated")
                                   for r in rows)),
            "method": "Immutable pregame research snapshot; model/quote join on both YES and NO; one-contract taker-fee assumption; no execution"}


def score(session, capture_data):
    pairs = []
    shadow_pairs = []
    shadow_groups = defaultdict(list)
    shadow_pnl = Counter()
    shadow_cost = Counter()
    pnl = cost = 0
    settled_paper = 0
    counts = Counter()
    fetched_markets = {}
    for row in capture_data["rows"]:
        if row.get("status") != "research_candidate":
            counts["excluded"] += 1
            continue
        ticker = row["ticker"]
        if ticker not in fetched_markets:
            fetched_markets[ticker] = get(session, "/markets/" + ticker)["market"]
        market = fetched_markets[ticker]
        if market.get("status") != "finalized" or market.get("result") not in ("yes", "no"):
            counts["pending_or_nonbinary"] += 1
            continue
        contract_side = row.get("contract_side", "yes")
        if contract_side not in ("yes", "no"):
            counts["invalid_side"] += 1
            continue
        outcome = int(market["result"] == contract_side)
        counts["settled"] += 1
        # Count each contract once for probability calibration, not once per side.
        if contract_side == "yes" and "market_probability" in row:
            pairs.append((row["model_probability"], row["market_probability"], outcome))
        shadow = row.get("starter_shadow", {})
        if all(shadow.get(k, {}).get("status") == "research_candidate" for k in ("baseline", "adjusted")):
            pair = (shadow["baseline"]["model_probability"], shadow["adjusted"]["model_probability"], outcome)
            if contract_side == "yes":
                shadow_pairs.append(pair)
                types = row.get("starter_input_types", {})
                shadow_groups[" + ".join(sorted(types.values())) or "unspecified"].append(pair)
            for variant, position in shadow.items():
                if position.get("paper_selected"):
                    entry = (position.get("ask_cents", position.get("yes_ask_cents")) + position["fee_cents_per_contract"]) / 100
                    shadow_cost[variant] += entry
                    shadow_pnl[variant] += outcome - entry
        if row.get("paper_selected"):
            entry = (row.get("ask_cents", row.get("yes_ask_cents")) + row["fee_cents_per_contract"]) / 100
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
                "by_input_types": {
                    kind: {"settled_pairs": len(group),
                           "baseline_brier": sum((p-y)**2 for p, _, y in group) / len(group),
                           "adjusted_brier": sum((p-y)**2 for _, p, y in group) / len(group)}
                    for kind, group in shadow_groups.items()},
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
