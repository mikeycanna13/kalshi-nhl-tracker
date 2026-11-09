"""Research-only Kalshi NHL contract -> NHL schedule reconciliation.

Match only when event date AND both teams uniquely agree with NHL's game
schedule. Preserve unmatched/ambiguous contracts; never guess NHL IDs.
Player UUIDs remain Kalshi-specific and are NOT NHL player IDs.
"""
import datetime as dt
import json
import re
import requests
from research_kalshi_contract_match import parse

# Kalshi ticker abbreviations are not always NHL abbreviations.
# Explicit aliases; the remaining NHL abbreviations are used unchanged.
CODES = {
    "ANA":"ANA","BOS":"BOS","BUF":"BUF","CAR":"CAR","CBJ":"CBJ",
    "CGY":"CGY","CHI":"CHI","COL":"COL","DAL":"DAL","DET":"DET",
    "EDM":"EDM","FLA":"FLA","LA":"LAK","LAK":"LAK","MIN":"MIN",
    "MTL":"MTL","NJ":"NJD","NJD":"NJD","NSH":"NSH","NYI":"NYI",
    "NYR":"NYR","OTT":"OTT","PHI":"PHI","PIT":"PIT","SEA":"SEA",
    "SJ":"SJS","SJS":"SJS","STL":"STL","TB":"TBL","TBL":"TBL",
    "TOR":"TOR","UTA":"UTA","VAN":"VAN","VGK":"VGK","WPG":"WPG",
    "WSH":"WSH",
}
def pair_candidates(s):
    return {frozenset((CODES[s[:i]],CODES[s[i:]]))
            for i in range(2,len(s)-1)
            if s[:i] in CODES and s[i:] in CODES and CODES[s[:i]]!=CODES[s[i:]]}

def extract_games(payload, original_date):
    """Score endpoint returns daily games; filter by authoritative gameDate."""
    games=[]
    for g in payload.get("games",[]):
        home=(g.get("homeTeam") or {}).get("abbrev")
        away=(g.get("awayTeam") or {}).get("abbrev")
        if not all((home,away,g.get("id"))):continue
        if g.get("gameDate")!=original_date:continue
        if g.get("gameType") not in (2,3):continue
        games.append({"nhl_game_id":g["id"],"home":home,"away":away,
                      "date":g["gameDate"],"game_type":g.get("gameType")})
    return games

def reconcile(market, schedule_payload):
    p=parse(market)
    if p["status"]!="parsed_unverified":return p
    pairs=pair_candidates(p["team_code_pair"])
    if not pairs:
        p.update(status="unmatched",reason="unknown or ambiguous team codes")
        return p
    matches=[g for g in extract_games(schedule_payload,p["original_date"])
             if frozenset((g["home"],g["away"])) in pairs]
    if len(matches)!=1:
        p.update(status="unmatched",reason=f"schedule candidates: {len(matches)}")
        return p
    g=matches[0]
    # A unique NHL fixture is established; player identity and market
    # settlement conditions still require separate verification.
    p.update(status="game_matched",nhl_game_id=g["nhl_game_id"],
             home_team=g["home"],away_team=g["away"],
             reason="unique original-date and two-team NHL schedule match")
    return p

def run(series=("KXNHLGAME","KXNHLTOTAL","KXNHLFIRSTGOAL","KXNHLPTS","KXNHLGOAL")):
    session=requests.Session()
    session.headers["User-Agent"]="kalshi-nhl-research-reconciliation/0.1"
    def fetch(url,params=None):
        r=session.get(url,params=params,timeout=30);r.raise_for_status()
        return r.json()
    all_markets=[]
    for name in series:
        cursor=None
        for page in range(20):
            params={"series_ticker":name,"status":"open","limit":1000}
            if cursor:params["cursor"]=cursor
            result=fetch("https://api.elections.kalshi.com/trade-api/v2/markets",params)
            all_markets.extend(result.get("markets",[]))
            cursor=result.get("cursor")
            if not cursor:break
        if cursor:raise RuntimeError("Market pagination incomplete for "+name)
    parsed=[parse(m) for m in all_markets]
    dates=sorted({p["original_date"] for p in parsed if p["status"]=="parsed_unverified"})
    schedules={d:fetch("https://api-web.nhle.com/v1/score/"+d) for d in dates}
    results=[reconcile(m,schedules.get(p.get("original_date"),{}))
             for m,p in zip(all_markets,parsed)]
    from collections import Counter
    counts=Counter(x["status"] for x in results)
    print("NHL_CONTRACT_MATCH="+json.dumps({
        "contracts":len(results),"dates_checked":len(dates),"status_counts":dict(counts),
        "matched_examples":[{"ticker":x["ticker"],"nhl_game_id":x["nhl_game_id"],
                             "date":x["original_date"],"home":x["home_team"],"away":x["away_team"]}
                            for x in results if x["status"]=="game_matched"][:12],
        "unmatched_examples":[{"ticker":x["ticker"],"reason":x["reason"]}
                              for x in results if x["status"]!="game_matched"][:12],
        "limitations":["No verified player identity crosswalk","No model-probability join",
                       "No settlement-rule equivalence guarantee"]},sort_keys=True),flush=True)
    if not results:raise RuntimeError("No markets found")
    if counts.get("game_matched",0)==0:raise RuntimeError("Zero verified game matches")

if __name__=="__main__":run()
