"""Research-only strict join of independently verified contracts and pregame model predictions.

Input predictions must have been generated before quote timestamp. This module
never fabricates future forecasts, fee schedules, fills, or player probabilities.
"""
from datetime import datetime
import math
from research_kalshi_ev import evaluate_quote

def parse_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp has no UTC offset")
    return parsed

def join_quote(contract, quote, forecast, fee_cents=None):
    if contract.get("status")!="game_matched":
        return {"status":"skipped","reason":"unverified NHL game match"}
    if str(contract["nhl_game_id"])!=str(forecast.get("game_id")):
        return {"status":"skipped","reason":"game ID mismatch"}
    try:
        observed = parse_timestamp(quote["observed_at_utc"])
        generated = parse_timestamp(forecast["generated_at_utc"])
        start = parse_timestamp(forecast["scheduled_start_utc"])
        cutoff_value = forecast.get("model_trained_through_utc")
        cutoff = parse_timestamp(cutoff_value) if cutoff_value else generated
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"status":"skipped","reason":"missing or invalid timestamp"}
    if generated > observed:
        return {"status":"skipped","reason":"future-dated pregame forecast"}
    if cutoff > generated:
        return {"status":"skipped","reason":"model training cutoff after forecast"}
    if generated >= start or observed >= start:
        return {"status":"skipped","reason":"forecast or quote not before verified scheduled puck drop"}
    if forecast.get("pregame_verified") is not True:
        return {"status":"skipped","reason":"forecast not verified pregame"}
    if quote.get("ticker")!=contract.get("ticker"):
        return {"status":"skipped","reason":"ticker mismatch"}
    if quote.get("snapshot_kind")!="live_orderbook":
        return {"status":"skipped","reason":"not a timestamped live orderbook"}
    if contract.get("market_type")=="moneyline":
        # The final ticker suffix must be explicitly mapped to the selected NHL team.
        selected=forecast.get("contract_selection_team")
        if selected not in (contract.get("home_team"),contract.get("away_team")):
            return {"status":"skipped","reason":"selection team not independently validated"}
        if forecast.get("selection_ticker")!=contract["ticker"]:
            return {"status":"skipped","reason":"selection ticker not independently validated"}
        home_prob=forecast.get("p_home_win")
        if home_prob is None:return {"status":"skipped","reason":"missing home-win probability"}
        p=home_prob if selected==contract["home_team"] else 1-home_prob
    elif contract.get("market_type")=="total":
        threshold=contract.get("threshold")
        if threshold not in (5.5,6.5):
            return {"status":"skipped","reason":"unsupported total threshold"}
        if not (contract.get("rules_primary") or "").lower().startswith(f"if the teams collectively score more than {threshold} goals"):
            return {"status":"skipped","reason":"unverified total settlement rule"}
        p=forecast.get("p_over_5_5" if threshold==5.5 else "p_over_6_5")
        if p is None:return {"status":"skipped","reason":"missing total probability"}
    else:
        return {"status":"skipped","reason":"player probabilities not modeled"}
    if not isinstance(p,(float,int)) or not math.isfinite(p) or not 0<=p<=1:
        return {"status":"skipped","reason":"invalid model probability"}
    price=quote.get("yes_ask_implied_cents")
    if price is None or fee_cents is None:
        return {"status":"skipped","reason":"missing quote or explicit fee"}
    try:
        quantity = float(quote.get("no_bid_qty") or 0)
        if not math.isfinite(quantity) or quantity < 1:
            return {"status":"skipped","reason":"no opposite-side liquidity"}
        ev=evaluate_quote(p,float(price),1,fee_cents)
    except (ValueError,TypeError,OverflowError) as exc:
        return {"status":"skipped","reason":"invalid price/fee: "+str(exc)}
    return {"status":"research_candidate","ticker":contract["ticker"],
            "nhl_game_id":contract["nhl_game_id"],"market_type":contract["market_type"],
            "model_probability":round(float(p),6),"quote_observed_at_utc":quote["observed_at_utc"],
            "quote_quantity":quantity,**ev,
            "warning":"Not a verified fill, trading recommendation, or profitability result"}
