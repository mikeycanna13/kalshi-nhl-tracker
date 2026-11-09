"""Parse verified Kalshi NHL contract metadata, without guessing NHL game IDs.

Game matching must be separately validated against NHL schedule, home/away teams,
original scheduled date and settlement rules. An event ticker alone is not proof.
"""
import datetime as dt
import re

SERIES={"KXNHLGAME":"moneyline","KXNHLTOTAL":"total",
        "KXNHLFIRSTGOAL":"first_goal","KXNHLPTS":"player_points",
        "KXNHLGOAL":"player_goals"}
EVENT=re.compile(r"^(KXNHL(?:GAME|TOTAL|FIRSTGOAL|PTS|GOAL))-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")
def parse(m):
    ticker=m.get("ticker","")
    event=m.get("event_ticker","")
    match=EVENT.fullmatch(event)
    if not match or not ticker.startswith(event+"-"):
        return {"ticker":ticker,"status":"unmatched","reason":"unsupported event ticker"}
    series,year,month,day,teams=match.groups()
    try:
        scheduled=dt.date(2000+int(year),dt.datetime.strptime(month,"%b").month,int(day)).isoformat()
    except ValueError:
        return {"ticker":ticker,"status":"unmatched","reason":"invalid event date"}
    kind=SERIES[series]
    strike=m.get("floor_strike")
    custom=m.get("custom_strike") or {}
    player=custom.get("hockey_player")
    if kind in ("player_points","player_goals","first_goal") and not player:
        return {"ticker":ticker,"status":"unmatched","reason":"missing player identifier"}
    if kind in ("total","player_points","player_goals"):
        if m.get("strike_type")!="greater" or not isinstance(strike,(int,float)):
            return {"ticker":ticker,"status":"unmatched","reason":"unsupported strike"}
    return {"ticker":ticker,"event_ticker":event,"series":series,
        "market_type":kind,"original_date":scheduled,"team_code_pair":teams,
        "player_kalshi_id":player,"team_kalshi_id":custom.get("hockey_team"),
        "threshold":strike,"rules_primary":m.get("rules_primary"),
        "rules_secondary":m.get("rules_secondary"),
        "status":"parsed_unverified","nhl_game_id":None,
        "reason":"requires independent NHL schedule reconciliation"}
