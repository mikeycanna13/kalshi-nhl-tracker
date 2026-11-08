"""Research-only, approved MoneyPuck download smoke test; prints aggregate reconciliation, not raw shots."""
import json
import os
import tempfile
from pathlib import Path
import requests
import pandas as pd
from nhl_mvp import download
from advanced_stats import load_shots, normalize, pregame_advanced_features

def main():
    season = os.environ.get("SHOT_SEASON", "2024")
    if season not in {"2022", "2023", "2024", "2025"}:
        raise ValueError("Unsupported season")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        schedule_season = f"{season}{int(season)+1}"
        download([schedule_season], root)
        games = pd.read_csv(root / "games.csv")
        url = f"https://peter-tanner.com/moneypuck/downloads/shots_{season}.zip"
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        if len(response.content) < 10000:
            raise ValueError("Shot archive suspiciously small")
        archive = root / "shots.zip"
        archive.write_bytes(response.content)
        raw = load_shots(archive)
        # Shot archive may include playoff games; retain completed regular-season schedule only.
        ids = set(games.game_id.astype(int))
        print("GAME_ID_DIAGNOSTICS=" + json.dumps({"schedule_examples": games.game_id.head(5).astype(str).tolist(), "shot_examples": raw.game_id.head(5).astype(str).tolist(), "shot_columns": list(raw.columns)[:35], "shot_rows": len(raw)}), flush=True)
        raw = raw[pd.to_numeric(raw.game_id, errors="coerce").isin(ids)].copy()
        if raw.empty:
            raise ValueError("No matching regular-season shots")
        normalized = normalize(raw, game_dates=games[["game_id", "date"]])
        features, goalies = pregame_advanced_features(raw, game_dates=games[["game_id", "date"]])
        matched = len(set(normalized.game_id))
        report = {
            "season": schedule_season,
            "scheduled_completed_games": len(games),
            "matched_games": matched,
            "coverage_pct": round(100 * matched / len(games), 2),
            "shot_rows": len(normalized),
            "pregame_feature_rows": len(features),
            "goalie_history_rows": len(goalies),
            "missing_game_count": len(ids - set(normalized.game_id)),
            "feature_nan_count": int(features.isna().sum().sum()),
            "five_on_five_shots": int((normalized.situation == "even").sum()),
        }
        print("MONEYPUCK_RECONCILIATION=" + json.dumps(report, sort_keys=True), flush=True)
        if matched / len(games) < 0.98:
            raise ValueError("MoneyPuck regular-season game coverage below 98%")
        if features.isna().any().any() or len(features) != matched:
            raise ValueError("Feature coverage or null validation failed")

if __name__ == "__main__":
    main()
