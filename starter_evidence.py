"""Validate a manually sourced starter snapshot before shadow forecasting."""
from datetime import datetime
from math import isclose


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp must include its UTC offset")
    return parsed


def starter_options(game, snapshot, cutoff):
    """Return the latest usable report for each team in home-away order."""
    if cutoff >= timestamp(game["start_time_utc"]):
        raise ValueError("Starter forecast cutoff must precede puck drop")
    options = []
    for team in (game["home"], game["away"]):
        matching = [row for row in snapshot if row["game_id"] == game["game_id"]
                    and row["team"] == team and timestamp(row["observed_at_utc"]) <= cutoff]
        row = max(matching, key=lambda item: timestamp(item["observed_at_utc"]), default={})
        options.append(report_distribution(row))
    if all(options) and set(options[0][1]) & set(options[1][1]):
        return [None, None]
    return options


def report_distribution(row):
    if not row.get("source_url"):
        return None
    status = row.get("status")
    if status == "confirmed":
        goalie_id = str(row.get("goalie_id", ""))
        if goalie_id.isdecimal() and int(goalie_id) > 0:
            return status, {goalie_id: 1.0}
    if status == "projected":
        candidates = row.get("candidates")
        if (isinstance(candidates, dict) and candidates
            and all(k.isdecimal() and int(k) > 0 and type(v) in (int, float) and 0 < v <= 1
                    for k, v in candidates.items())
            and isclose(sum(candidates.values()), 1, rel_tol=0, abs_tol=1e-6)):
            return status, candidates
    return None


def confirmed_pair(game, snapshot, cutoff):
    options = starter_options(game, snapshot, cutoff)
    if all(option and option[0] == "confirmed" for option in options):
        return tuple(next(iter(option[1])) for option in options)
    return None
