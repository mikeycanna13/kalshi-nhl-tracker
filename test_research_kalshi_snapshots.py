"""Offline tests for Kalshi bid-side orderbook semantics and safe classification."""
import unittest
from research_kalshi_snapshots import best,classify

class TestKalshiSnapshots(unittest.TestCase):
    def test_best_bid(self):
        self.assertEqual(best([[30,20],[47,7],[41,100]]),(47,7))
    def test_empty_book(self):
        self.assertEqual(best([]),(None,None))
    def test_market_classes(self):
        self.assertEqual(classify("First goal scorer"),"first_goal")
        self.assertEqual(classify("Total goals over 5.5"),"total")
        self.assertEqual(classify("Winner of the game"),"moneyline")
        self.assertEqual(classify("Unrecognized contract"),"unclassified")
    def test_implied_ask_from_opposite_bid(self):
        no_bid,_=best([[35,4],[42,8]])
        self.assertEqual(100-no_bid,58)
if __name__=="__main__":unittest.main()

class FixedPointBookTests(unittest.TestCase):
    def test_live_schema_preserves_fractional_depth(self):
        from research_kalshi_snapshots import book_bids
        book = {"orderbook_fp": {"yes_dollars": [["0.4500", "3.23"]],
                                 "no_dollars": [["0.5100", "124.00"]]}}
        self.assertEqual(book_bids(book), ((45, 3.23), (51, 124.0)))

    def test_legacy_schema_still_supported(self):
        from research_kalshi_snapshots import book_bids
        self.assertEqual(book_bids({"orderbook": {"no": [[45, 2]]}}),
                         ((None, None), (45, 2)))
