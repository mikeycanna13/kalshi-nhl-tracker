"""Discover Kalshi NHL market series from public API, without guessing tickers.

Research-only: prints matching series and sample events; no orders or credentials.
"""
import argparse
import json
import requests

BASE="https://api.elections.kalshi.com/trade-api/v2"
def fetch(session,path,params):
    r=session.get(BASE+path,params=params,timeout=30)
    r.raise_for_status()
    return r.json()
def discover(max_pages=30):
    s=requests.Session()
    s.headers["User-Agent"]="nhl-model-research/0.2"
    cursor=None
    matches=[]
    total=0
    for _ in range(max_pages):
        params={"limit":200}
        if cursor:params["cursor"]=cursor
        page=fetch(s,"/series",params)
        series=page.get("series",[])
        total+=len(series)
        for x in series:
            title=" ".join(str(x.get(k) or "") for k in ("title","category","tags","ticker"))
            low=title.lower()
            if any(w in low for w in ("nhl","hockey","stanley cup")):
                matches.append({"ticker":x.get("ticker"),"title":x.get("title"),
                                "category":x.get("category"),"tags":x.get("tags")})
        cursor=page.get("cursor")
        if not cursor:break
    if cursor:
        raise RuntimeError("Incomplete series pagination; increase --max-pages")
    print("NHL_SERIES_DISCOVERY="+json.dumps({"series_scanned":total,"matches":matches},sort_keys=True),flush=True)
    if not matches:
        raise RuntimeError("No NHL series found; verify API schema and taxonomy")
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--max-pages",type=int,default=30)
    args=p.parse_args()
    discover(args.max_pages)
