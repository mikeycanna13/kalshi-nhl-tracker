from datetime import datetime
from unittest import TestCase

from starter_evidence import confirmed_pair


class StarterEvidenceTests(TestCase):
    def test_requires_two_confirmations_available_at_forecast_cutoff(self):
        cutoff = datetime.fromisoformat("2026-11-10T22:00:00+00:00")
        game = {"game_id": 1, "home": "TOR", "away": "COL",
                "start_time_utc": "2026-11-11T00:00:00Z"}
        home = {"game_id": 1, "team": "TOR", "goalie_id": 1, "status": "confirmed",
                "source_url": "https://example.org/home", "observed_at_utc": "2026-11-10T21:00:00Z"}
        away = dict(home, team="COL", goalie_id=2)
        self.assertEqual(confirmed_pair(game, [home, away], cutoff), ("1", "2"))
        self.assertIsNone(confirmed_pair(game, [home, dict(away, status="unconfirmed")], cutoff))
        self.assertIsNone(confirmed_pair(game, [home, dict(away, observed_at_utc="2026-11-10T23:00:00Z")], cutoff))
        self.assertIsNone(confirmed_pair(game, [home, away, dict(away, status="unconfirmed",
                         observed_at_utc="2026-11-10T21:30:00Z")], cutoff))
