"""Inspect real NHL Kalshi contract metadata before implementing game matching."""
import json,requests
base="https://api.elections.kalshi.com/trade-api/v2"
for series in ["KXNHLGAME","KXNHLTOTAL","KXNHLFIRSTGOAL","KXNHLPTS","KXNHLGOAL"]:
    r=requests.get(base+"/markets",params={"series_ticker":series,"status":"open","limit":3},timeout=30)
    r.raise_for_status()
    markets=r.json().get("markets",[])
    print("MARKET_SCHEMA="+json.dumps({"series":series,"count":len(markets),"examples":[{
        k:m.get(k) for k in ["ticker","event_ticker","title","subtitle","yes_sub_title","no_sub_title","close_time","expiration_time","strike_type","floor_strike","cap_strike","custom_strike","rules_primary","rules_secondary"]} for m in markets]},default=str),flush=True)
