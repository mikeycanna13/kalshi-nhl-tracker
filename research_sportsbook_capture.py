"""Optional live The Odds API NHL h2h snapshot. No default paid API call.

Network access requires --enable AND a user-supplied THE_ODDS_API_KEY.
This script never performs historical paid queries, places bets, or prints keys.
The receipt time is captured after response; individual bookmaker updates
are validated independently before paired with Kalshi observations.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime,timezone
from pathlib import Path
import requests

ENDPOINT="https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds"

def now():
    return datetime.now(timezone.utc).isoformat()

def acquire(enabled,api_key=None,session=None):
    if not enabled:
        return {"status":"not_requested","source":"sportsbook_data_not_configured",
                "timestamp":now(),"data":[],
                "reason":"No paid or key-dependent odds query was authorized for this run"}
    if not api_key:
        raise RuntimeError("Explicit sportsbook collection requested but THE_ODDS_API_KEY was not configured")
    started=now()
    client=session or requests.Session()
    response=client.get(ENDPOINT,params={
        "apiKey":api_key,"regions":"us","markets":"h2h",
        "oddsFormat":"decimal","dateFormat":"iso"},timeout=30)
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,list):
        raise ValueError("Unexpected live odds API response")
    received=now()
    return {"status":"captured","source":"the_odds_api_live",
            "request_started_at_utc":started,"timestamp":received,
            "data":data,
            "raw_response_sha256":hashlib.sha256(response.content).hexdigest(),
            "event_count":len(data),
            "quota_last":response.headers.get("x-requests-last"),
            "quota_remaining":response.headers.get("x-requests-remaining"),
            "limitations":["Provider subscription/usage quota may apply",
                           "Bookmaker last_update checked separately",
                           "No backfilled prices or historical request"]}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default="results/sportsbook_snapshot.json",type=Path)
    parser.add_argument("--enable",action="store_true",
                        help="Explicitly permit a provider API call, which may consume paid quota")
    a=parser.parse_args()
    data=acquire(a.enable,os.environ.get("THE_ODDS_API_KEY"))
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(data,indent=2),encoding="utf-8")
    print(json.dumps({"status":data["status"],
                      "event_count":data.get("event_count",0),
                      "quota_last":data.get("quota_last")}),flush=True)

if __name__=="__main__":
    main()
