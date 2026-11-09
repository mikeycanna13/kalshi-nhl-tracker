"""Kalshi quote-level expected value calculator (research only; no orders).

Fees are INPUTS, not assumed Kalshi rates. Uses observed opposite-side bids
to infer a potential ask, subject to available liquidity and quote staleness.
"""
import math

def evaluate_quote(prob_yes,yes_ask_cents,quantity=1,fee_cents_per_contract=None):
    if not 0<=prob_yes<=1:raise ValueError("Probability outside [0,1]")
    if not isinstance(yes_ask_cents,int) or not 1<=yes_ask_cents<=99:
        raise ValueError("Missing or invalid executable-side price")
    if not isinstance(quantity,int) or quantity<1:raise ValueError("Invalid quantity")
    if fee_cents_per_contract is None:
        raise ValueError("Fee input required; do not assume a zero-fee contract")
    if not math.isfinite(fee_cents_per_contract) or fee_cents_per_contract<0:
        raise ValueError("Invalid fee")
    cost=quantity*(yes_ask_cents+fee_cents_per_contract)/100
    expected_payout=quantity*prob_yes
    ev=expected_payout-cost
    return {"quantity":quantity,"yes_ask_cents":yes_ask_cents,
            "fee_cents_per_contract":fee_cents_per_contract,
            "expected_profit_usd":round(ev,6),
            "expected_roi":round(ev/cost,6),
            "breakeven_probability":(yes_ask_cents+fee_cents_per_contract)/100,
            "assumptions":"Quote must still be available; no slippage; fees provided externally"}

if __name__=="__main__":
    import argparse,json
    p=argparse.ArgumentParser()
    p.add_argument("--probability",type=float,required=True)
    p.add_argument("--yes-ask-cents",type=int,required=True)
    p.add_argument("--fee-cents",type=float,required=True)
    p.add_argument("--quantity",type=int,default=1)
    a=p.parse_args()
    print(json.dumps(evaluate_quote(a.probability,a.yes_ask_cents,a.quantity,a.fee_cents),indent=2))
