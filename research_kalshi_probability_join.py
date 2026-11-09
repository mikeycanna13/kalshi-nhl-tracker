"""Research-only strict join of independently verified contracts and pregame model predictions.

Input predictions must have been generated before quote timestamp. This module
never fabricates future forecasts, fee schedules, fills, or player probabilities.
"""
import math
from research_kalshi_ev import evaluate_quote

def join_quote(contract, quote, forecast, fee_cents=None):
    if contract.get("status")!="game_matched":
        return {"status":"skipped","reason":"unverified NHL game match"}
    if str(contract["nhl_game_id"])!=str(forecast.get("game_id")):
        return {"status":"skipped","reason":"game ID mismatch"}
    observed=quote.get("observed_at_utc")
    generated=forecast.get("generated_at_utc")
    if not observed or not generated or generated>observed:
        return {"status":"skipped","reason":"missing or future-dated pregame forecast"}
    if forecast.get("model_trained_through_utc") and forecast["model_trained_through_utc"]>generated:
        return {"status":"skipped","reason":"model training cutoff after forecast"}
    start=forecast.get("scheduled_start_utc")
    if not start or generated>=start or observed>=start:
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
        if not (contract.get("rules_primary") or "").lower().startswith("if the teams collectively score more than"):
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
    if quote.get("no_bid_qty") is None or int(quote["no_bid_qty"])<1:
        return {"status":"skipped","reason":"no opposite-side liquidity"}
    try:
        ev=evaluate_quote(p,int(price),1,fee_cents)
    except (ValueError,TypeError,OverflowError) as exc:
        return {"status":"skipped","reason":"invalid price/fee: "+str(exc)}
    return {"status":"research_candidate","ticker":contract["ticker"],
            "nhl_game_id":contract["nhl_game_id"],"market_type":contract["market_type"],
            "model_probability":round(float(p),6),"quote_observed_at_utc":observed,
            "quote_quantity":int(quote["no_bid_qty"]),**ev,
            "warning":"Not a verified fill, trading recommendation, or profitability result"}
