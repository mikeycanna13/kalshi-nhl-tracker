"""Research-only Kalshi NHL market snapshot collector.

Public market and orderbook endpoints; no authentication, trading, or execution.
Orderbook asks are inferred from opposing-side bids, NOT observed ask orders.
"""
import argparse
import csv
import datetime as dt
import json
import os
import time
from pathlib import Path
import requests

BASE="https://api.elections.kalshi.com/trade-api/v2"
FIELDS=["observed_at_utc","event_ticker","ticker","title","subtitle","status",
        "close_time","market_type","yes_bid_cents","yes_ask_implied_cents",
        "no_bid_cents","no_ask_implied_cents","yes_bid_qty","no_bid_qty",
        "last_price_cents","volume","open_interest","source","snapshot_kind"]
def classify(title):
    s=(title or "").lower()
    if any(x in s for x in ["first goal","first scorer"]):return "first_goal"
    if any(x in s for x in ["anytime goal","score a goal"]):return "anytime_goal"
    if any(x in s for x in ["player point","record a point"]):return "player_point"
    if any(x in s for x in ["total goals","over ","under "]):return "total"
    if any(x in s for x in ["winner","win the game","moneyline"]):return "moneyline"
    return "unclassified"
def get(session,path,params=None):
    r=session.get(BASE+path,params=params,timeout=25)
    r.raise_for_status()
    return r.json()
def best(levels):
    # Kalshi orderbooks contain bid ladders: [price_cents, quantity].
    if not levels:return None,None
    valid=[(int(x[0]),int(x[1])) for x in levels if isinstance(x,(list,tuple)) and len(x)>=2]
    if not valid:return None,None
    return max(valid,key=lambda x:x[0])
def collect(session,series,limit=1000):
    markets=[];cursor=None
    for _ in range(20):
        params={"limit":min(limit,1000),"status":"open"}
        if series:params["series_ticker"]=series
        if cursor:params["cursor"]=cursor
        page=get(session,"/markets",params)
        markets.extend(page.get("markets",[]))
        cursor=page.get("cursor")
        if not cursor:break
    if cursor:raise RuntimeError("Pagination cap reached: refusing incomplete collection")
    return markets
def snapshot(series,out,include_unclassified=False,max_markets=500):
    session=requests.Session()
    session.headers["User-Agent"]="nhl-research-market-snapshots/0.1"
    markets=collect(session,series)
    rows=[];failures=[]
    for market in markets:
        title=" ".join(str(market.get(k) or "") for k in ("title","subtitle","yes_sub_title"))
        kind=classify(title)
        if kind=="unclassified" and not include_unclassified:continue
        if len(rows)>=max_markets:raise RuntimeError("Market cap reached; narrow series")
        ticker=market.get("ticker")
        if not ticker:continue
        try:
            book=get(session,"/markets/"+ticker+"/orderbook").get("orderbook",{})
            yes_price,yes_qty=best(book.get("yes"))
            no_price,no_qty=best(book.get("no"))
            # Opposite-side bid implies the executable limit ask only if
            # that opposing liquidity remains available; NOT a fill guarantee.
            rows.append({"observed_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
                "event_ticker":market.get("event_ticker"),"ticker":ticker,
                "title":market.get("title"),"subtitle":market.get("subtitle"),
                "status":market.get("status"),"close_time":market.get("close_time"),
                "market_type":kind,"yes_bid_cents":yes_price,
                "yes_ask_implied_cents":100-no_price if no_price is not None else None,
                "no_bid_cents":no_price,
                "no_ask_implied_cents":100-yes_price if yes_price is not None else None,
                "yes_bid_qty":yes_qty,"no_bid_qty":no_qty,
                "last_price_cents":market.get("last_price"),
                "volume":market.get("volume"),"open_interest":market.get("open_interest"),
                "source":"kalshi_public_v2","snapshot_kind":"live_orderbook"})
        except (requests.RequestException,ValueError,TypeError,KeyError) as exc:
            failures.append({"ticker":ticker,"error":str(exc)[:160]})
        time.sleep(.08)
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    if rows:
        with out.open("a",newline="",encoding="utf-8") as file:
            writer=csv.DictWriter(file,fieldnames=FIELDS)
            if file.tell()==0:writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({"series":series,"discovered_markets":len(markets),
        "snapshots_written":len(rows),"failed_orderbooks":len(failures),
        "failures":failures[:10],"output":str(out),
        "limitations":["No historical orderbook reconstruction","No automatic NHL game-ID mapping",
        "No fee or realized-PnL estimate","Quotes may move before execution"]}),flush=True)
    if failures:raise RuntimeError(f"{len(failures)} orderbooks failed; partial data written")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--series",required=True,help="Verified Kalshi NHL series ticker; no inferred aliases")
    p.add_argument("--out",default="data/kalshi_nhl_orderbook_snapshots.csv")
    p.add_argument("--include-unclassified",action="store_true")
    p.add_argument("--max-markets",type=int,default=500)
    a=p.parse_args()
    snapshot(a.series,a.out,a.include_unclassified,a.max_markets)
