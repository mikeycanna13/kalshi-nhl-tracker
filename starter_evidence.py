"""Validate a manually sourced starter snapshot before shadow forecasting."""
from datetime import datetime


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include its UTC offset")
    return parsed


def confirmed_pair(game, snapshot, cutoff):
    """Return both goalie IDs only when both team-specific reports qualify."""
    start = timestamp(game["start_time_utc"])
    if cutoff >= start:
        raise ValueError("Starter forecast cutoff must precede puck drop")
    goalies = []
    for team in (game["home"], game["away"]):
        matching = [row for row in snapshot if row["game_id"] == game["game_id"]
                    and row["team"] == team and timestamp(row["observed_at_utc"]) <= cutoff]
        if not matching:
            return None
        row = max(matching, key=lambda item: timestamp(item["observed_at_utc"]))
        goalie_id = str(row.get("goalie_id", ""))
        if row["status"] != "confirmed" or not goalie_id.isdecimal() or not row.get("source_url"):
            return None
        goalies.append(goalie_id)
    return tuple(goalies) if len(set(goalies)) == 2 else None
