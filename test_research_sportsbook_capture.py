import json
import unittest
from unittest.mock import Mock
from research_sportsbook_capture import acquire

class ProviderTests(unittest.TestCase):
    def test_no_opt_in_never_calls_network(self):
        session=Mock()
        result=acquire(False,api_key="FAKE_SECRET",session=session)
        session.get.assert_not_called()
        self.assertEqual(result["status"],"not_requested")
    def test_explicit_opt_in_requires_key(self):
        with self.assertRaises(RuntimeError):
            acquire(True,api_key=None,session=Mock())
    def test_live_capture_records_source_and_does_not_expose_key(self):
        response=Mock()
        response.json.return_value=[{"id":"sample","home_team":"New York Rangers",
                                      "away_team":"Boston Bruins","bookmakers":[]}]
        response.content=b"fixture"
        response.headers={"x-requests-last":"1","x-requests-remaining":"999"}
        response.raise_for_status.return_value=None
        session=Mock()
        session.get.return_value=response
        result=acquire(True,api_key="SENSITIVE_FAKE_SECRET",session=session)
        self.assertEqual(result["source"],"the_odds_api_live")
        self.assertEqual(result["event_count"],1)
        self.assertEqual(result["quota_remaining"],"999")
        self.assertNotIn("SENSITIVE_FAKE_SECRET",json.dumps(result))
        self.assertEqual(session.get.call_count,1)
    def test_malformed_provider_payload_refused(self):
        response=Mock()
        response.json.return_value={"unexpected":"format"}
        response.raise_for_status.return_value=None
        session=Mock(get=Mock(return_value=response))
        with self.assertRaises(ValueError):
            acquire(True,api_key="FAKE",session=session)

if __name__=="__main__":
    unittest.main()
