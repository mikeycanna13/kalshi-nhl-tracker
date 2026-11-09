from unittest import TestCase
from unittest.mock import patch

from research_kalshi_paper import fee_cents, score


class PaperTests(TestCase):
    def test_taker_fee_rounds_up_to_centicent(self):
        self.assertEqual(fee_cents({"fee_type": "quadratic", "fee_multiplier": 1}, 49), 1.75)
        self.assertIsNone(fee_cents({"fee_type": "unknown", "fee_multiplier": 1}, 49))

    @patch("research_kalshi_paper.get")
    def test_score_uses_settled_results_and_frozen_prices(self, get):
        get.side_effect = [
            {"market": {"status": "finalized", "result": "yes"}},
            {"market": {"status": "active", "result": ""}},
        ]
        selected = {"status": "research_candidate", "ticker": "WIN", "paper_selected": True,
                    "yes_ask_cents": 45, "fee_cents_per_contract": 1.74,
                    "model_probability": .6, "market_probability": .5}
        result = score(None, {"rows": [selected, dict(selected, ticker="OPEN"), {"status": "skipped"}]})
        self.assertEqual(result["counts"], {"settled": 1, "pending_or_nonbinary": 1, "excluded": 1})
        self.assertAlmostEqual(result["model_brier"], .16)
        self.assertAlmostEqual(result["market_brier"], .25)
        self.assertAlmostEqual(result["paper_profit_usd"], .5326)
