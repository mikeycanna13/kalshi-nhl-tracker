"""Build strictly pregame rolling xG and goalie GSAx from MoneyPuck shot CSV/ZIP.

MoneyPuck data is licensed for non-commercial use; obtain data via its approved
downloads page (https://www.moneypuck.com/data.htm). This script never scrapes.
Usage:
  python advanced_stats.py --shots /path/to/shots_2025.zip --out data/advanced_2025.csv
The output contains game-level pregame team features, NOT in-game outcomes.
"""
import argparse
from collections import defaultdict, deque
from pathlib import Path
from zipfile import ZipFile
import numpy as np
import pandas as pd

ALIASES = {
    "game_id": ("game_id", "gameId"),
    "date": ("game_date", "gameDate", "date"),
    "team": ("teamCode", "shootingTeam", "team"),
    "opponent": ("opposingTeam", "opponent", "opposingTeamCode"),
    "xg": ("xGoal", "xGoals", "xG"),
    "goalie": ("goalieIdForShot", "goalieId", "goalie_id"),
    "goal": ("isGoal", "goal"),
    "home": ("homeTeamCode", "homeTeam"),
    "away": ("awayTeamCode", "awayTeam"),
    "home_skaters": ("homeSkatersOnIce",),
    "away_skaters": ("awaySkatersOnIce",),
}

def load_shots(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as z:
            csvs = [name for name in z.namelist() if name.lower().endswith(".csv")]
            if len(csvs) != 1:
                raise ValueError("Expected exactly one CSV inside ZIP")
            with z.open(csvs[0]) as f:
                return pd.read_csv(f, low_memory=False)
    return pd.read_csv(path, low_memory=False)

def normalize(raw, game_dates=None):
    # Official MoneyPuck shots use team=HOME/AWAY and often omit game date.
    raw = raw.copy()
    if not any(col in raw.columns for col in ALIASES["date"]):
        if game_dates is None:
            raise ValueError("MoneyPuck shots lack dates: provide --games with game_id and date")
        mapping = game_dates.copy()
        if "game_id" not in mapping.columns or "date" not in mapping.columns:
            raise ValueError("Game schedule must contain game_id and date")
        mapping["game_id"] = pd.to_numeric(mapping.game_id, errors="raise").astype("int64")
        if mapping.duplicated("game_id").any():
            raise ValueError("Duplicate game IDs in schedule")
        raw["game_id"] = pd.to_numeric(raw.game_id, errors="raise").astype("int64")
        raw = raw.merge(mapping[["game_id", "date"]], on="game_id", how="left", validate="many_to_one")
        if raw.date.isna().any():
            raise ValueError("Schedule is missing dates for shot games")
    if "team" in raw.columns and raw["team"].isin(["HOME", "AWAY"]).all():
        raw["teamCode"] = np.where(raw["team"] == "HOME", raw["homeTeamCode"], raw["awayTeamCode"])
        raw = raw.drop(columns=["team"])
    if not any(col in raw.columns for col in ALIASES["opponent"]):
        if "teamCode" not in raw.columns:
            raise ValueError("Cannot infer opponent without team codes")
        raw["opposingTeam"] = np.where(raw["teamCode"] == raw["homeTeamCode"], raw["awayTeamCode"], raw["homeTeamCode"])
    columns = {}
    for name, candidates in ALIASES.items():
        hit = next((c for c in candidates if c in raw.columns), None)
        if hit is None:
            raise ValueError(f"Required MoneyPuck field {name} not found; candidates={candidates}. "
                             f"Available={list(raw.columns)}")
        columns[name] = hit
    d = pd.DataFrame({name: raw[source] for name, source in columns.items()})
    dates = d["date"].astype(str)
    if dates.str.fullmatch(r"\d{8}").all():
        d["date"] = pd.to_datetime(dates, format="%Y%m%d", errors="raise")
    else:
        d["date"] = pd.to_datetime(d.date, errors="raise").dt.normalize()
    d["game_id"] = pd.to_numeric(d.game_id, errors="raise").astype("int64")
    d["xg"] = pd.to_numeric(d.xg, errors="raise")
    d["goal"] = pd.to_numeric(d.goal, errors="raise")
    d["home_skaters"] = pd.to_numeric(d.home_skaters, errors="raise")
    d["away_skaters"] = pd.to_numeric(d.away_skaters, errors="raise")
    if d[["game_id","date","team","opponent","home","away","xg","goal"]].isna().any().any():
        raise ValueError("Missing required shot observations")
    if not d.xg.between(0,1).all() or not d.goal.isin([0,1]).all():
        raise ValueError("Invalid shot probability or goal indicator")
    if not ((d.team == d.home) | (d.team == d.away)).all():
        raise ValueError("Shot team does not match home or away team")
    # 4v4 and 3v3 are NOT 5v5. Do not contaminate 5v5 xG with OT.
    is_5v5 = (d.home_skaters == 5) & (d.away_skaters == 5)
    shooter_advantage = (((d.team == d.home) & (d.home_skaters > d.away_skaters)) |
                         ((d.team == d.away) & (d.away_skaters > d.home_skaters)))
    shooter_disadvantage = (((d.team == d.home) & (d.home_skaters < d.away_skaters)) |
                            ((d.team == d.away) & (d.away_skaters < d.home_skaters)))
    d["situation"] = np.select(
        [is_5v5, shooter_advantage, shooter_disadvantage],
        ["even", "power_play", "shorthanded"], default="other")
    d["goalie"] = d.goalie.astype("string")
    return d

def pregame_advanced_features(shots, window=20, goalie_prior_minutes_equiv_games=12, game_dates=None):
    """One row per game. Daily batch updates avoid leakage from same-day games.

    Goalie features describe observed historical goalie quality of the prior
    game's goalie pool, NOT a claimed confirmed starter. For starter-specific
    predictions, a separate timestamped starter feed is required.
    """
    d = normalize(shots, game_dates=game_dates)
    teams = defaultdict(lambda: deque(maxlen=window))
    goalies = defaultdict(lambda: [0.0, 0.0, 0])  # xGA, GA, observed games
    rows = []
    for date, day in d.groupby("date", sort=True):
        updates = []
        for game_id, game in day.groupby("game_id", sort=True):
            home, away = game.home.iloc[0], game.away.iloc[0]
            if len({home,away}) != 2 or not game.team.isin([home,away]).all():
                raise ValueError(f"Inconsistent teams in game {game_id}")
            row = {"game_id": int(game_id), "date": str(date.date())}
            for side, team, opp in (("home",home,away),("away",away,home)):
                history = list(teams[team])
                n = len(history)
                for situation in ("even","power_play","penalty_kill"):
                    # xG per game; use prior observations only and a shrinkage prior.
                    for direction in ("for","against"):
                        values = [v[f"{situation}_{direction}"] for v in history]
                        row[f"{side}_{situation}_xg_{direction}_pg"] = (sum(values) + 3.0*1.0)/(n+3.0)
                row[f"{side}_advanced_games"] = n
            rows.append(row)
            update = {"game_id": game_id, "home": home, "away": away, "teams": {}, "goalies": {}}
            for team,opp in ((home,away),(away,home)):
                # Interpret manpower from the perspective of the team, not the shooter.
                # Opponent PP shots are our PK xGA, not our PP xGA.
                team_shots = game[game.team == team]
                opp_shots = game[game.team == opp]
                update["teams"][team] = {
                    "even_for": float(team_shots.loc[team_shots.situation == "even", "xg"].sum()),
                    "even_against": float(opp_shots.loc[opp_shots.situation == "even", "xg"].sum()),
                    "power_play_for": float(team_shots.loc[team_shots.situation == "power_play", "xg"].sum()),
                    "power_play_against": float(opp_shots.loc[opp_shots.situation == "shorthanded", "xg"].sum()),
                    "penalty_kill_for": float(team_shots.loc[team_shots.situation == "shorthanded", "xg"].sum()),
                    "penalty_kill_against": float(opp_shots.loc[opp_shots.situation == "power_play", "xg"].sum()),
                }
            # Goalie GSAx is retained as a separate historical table for future
            # timestamped starter integration. Do not leak actual game goalie into features.
            for goalie, group in game.dropna(subset=["goalie"]).groupby("goalie"):
                update["goalies"][goalie] = (float(group.xg.sum()), float(group.goal.sum()))
            updates.append(update)
        for update in updates:
            for team, values in update["teams"].items():
                teams[team].append(values)
            for goalie, (xga, ga) in update["goalies"].items():
                stats = goalies[goalie]
                stats[0] += xga
                stats[1] += ga
                stats[2] += 1
    features = pd.DataFrame(rows).sort_values(["date","game_id"]).reset_index(drop=True)
    goalie_history = pd.DataFrame([
        {"goalie_id": goalie, "xga": v[0], "ga": v[1],
         "gsax": v[0]-v[1], "games_observed": v[2],
         "shrunk_gsax_per_game": (v[0]-v[1])/(v[2]+goalie_prior_minutes_equiv_games)}
        for goalie,v in goalies.items()])
    return features, goalie_history

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--shots",required=True,help="Approved MoneyPuck shot CSV or ZIP already downloaded")
    parser.add_argument("--games",help="Schedule CSV containing game_id and date; required if shots lack dates")
    parser.add_argument("--out",default="data/advanced_features.csv")
    parser.add_argument("--goalies-out",default="data/goalie_history.csv")
    args=parser.parse_args()
    schedule = pd.read_csv(args.games) if args.games else None
    features, goalies = pregame_advanced_features(load_shots(args.shots), game_dates=schedule)
    for name, frame in ((args.out,features),(args.goalies_out,goalies)):
        path=Path(name)
        path.parent.mkdir(parents=True,exist_ok=True)
        frame.to_csv(path,index=False)
        print(f"Saved {len(frame)} rows to {path}",flush=True)

if __name__=="__main__":
    main()
