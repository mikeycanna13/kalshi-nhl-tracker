from unittest import TestCase
from unittest.mock import patch

from research_kalshi_paper import fee_cents, score, rank_unique_exposures


class PaperTests(TestCase):
    def test_taker_fee_rounds_up_to_centicent(self):
        self.assertEqual(fee_cents({"fee_type": "quadratic", "fee_multiplier": 1}, 49), 1.75)
        self.assertIsNone(fee_cents({"fee_type": "unknown", "fee_multiplier": 1}, 49))


    def test_complementary_moneylines_count_as_one_economic_exposure(self):
        contract={"market_type":"moneyline","nhl_game_id":123,
                  "home_team":"CBJ","away_team":"FLA"}
        base={"status":"research_candidate","expected_profit_usd":.048,
              "quote_quantity":1}
        yes=dict(base, ticker="CBJ-YES", contract=contract,
                 contract_side="yes", quote_quantity=100,
                 forecast={"contract_selection_team":"CBJ"})
        no=dict(base, ticker="FLA-NO", contract=contract,
                contract_side="no", quote_quantity=1,
                forecast={"contract_selection_team":"FLA"})
        ranked=rank_unique_exposures([no,yes])
        self.assertEqual(len(ranked),1)
        self.assertEqual(ranked[0]["ticker"],"CBJ-YES")

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

    @patch("research_kalshi_paper.get")
    def test_no_side_settlement_and_calibration_not_double_counted(self, get):
        get.return_value = {"market":{"status":"finalized","result":"no"}}
        common = {"status":"research_candidate","ticker":"TOTAL",
                  "model_probability":.70,"market_probability":.65,
                  "paper_selected":False,"ask_cents":35,"fee_cents_per_contract":1}
        yes = dict(common,contract_side="yes",model_probability=.30,market_probability=.35)
        no = dict(common,contract_side="no",paper_selected=True)
        result = score(None,{"rows":[yes,no]})
        self.assertEqual(result["paired_brier_count"],1)
        self.assertAlmostEqual(result["model_brier"],.09)
        self.assertAlmostEqual(result["paper_profit_usd"],.64)
        self.assertEqual(result["settled_paper_positions"],1)
        self.assertEqual(get.call_count,1)
