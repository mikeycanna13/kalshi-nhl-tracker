"""Offline-only tests for free NHL schedule-trigger research integration."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research_scheduler.resolve_target import resolve,target_is_past_in_new_york
from research_scheduler.annotate_capture import annotate

BRANCH="research/nhl-model-benchmarks"
class TestResearchScheduler(unittest.TestCase):
    def trigger(self,root,window="two_hours",date="2026-11-10"):
        path=f"scheduler/triggers/{date}/{window}_20261110T2200Z.json"
        destination=Path(root)/path
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps({
            "schema":"nhl_scheduler_trigger_v1",
            "target_date":date,"window":window,"bucket":"20261110T2200Z",
            "game_ids":[123],"research_branch":BRANCH}))
        return path

    def test_valid_trigger_date_and_window(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.trigger(root)
            resolved=resolve([path],root,"2026-11-11")
            self.assertEqual(resolved["target_date"],"2026-11-10")
            self.assertEqual(resolved["window"],"two_hours")
            self.assertEqual(resolved["game_ids"],[123])

    def test_dev_push_uses_fallback(self):
        self.assertEqual(resolve(["research_scheduler/resolve_target.py"],".","2026-11-11"),
                         {"target_date":"2026-11-11","window":"development"})

    def test_multiple_trigger_files_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            a=self.trigger(root,"morning")
            b=self.trigger(root,"two_hours")
            with self.assertRaises(ValueError):resolve([a,b],root,"2026-11-11")

    def test_invalid_branch_and_date_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path=self.trigger(root)
            obj=json.loads((Path(root)/path).read_text())
            obj["research_branch"]="main"
            (Path(root)/path).write_text(json.dumps(obj))
            with self.assertRaises(ValueError):resolve([path],root,"2026-11-11")
            obj["research_branch"]=BRANCH
            obj["target_date"]="2026-11-12"
            (Path(root)/path).write_text(json.dumps(obj))
            with self.assertRaises(ValueError):resolve([path],root,"2026-11-11")

    def test_capture_rejects_incorrect_target_or_double_stamp(self):
        data={"forecasts":{"target_date":"2026-11-10"}}
        good={"target_date":"2026-11-10","window":"morning"}
        saved=annotate(data,good)
        self.assertEqual(saved["scheduler_context"]["window"],"morning")
        with self.assertRaises(ValueError):annotate(saved,good)
        with self.assertRaises(ValueError):annotate(data,{"target_date":"2026-11-11","window":"morning"})

    def test_eastern_november_night_not_past_after_midnight_utc(self):
        after_utc_midnight=datetime(2026,11,11,1,0,tzinfo=timezone.utc)
        self.assertFalse(target_is_past_in_new_york("2026-11-10",after_utc_midnight))

    def test_eastern_after_midnight_is_past(self):
        after_utc_midnight=datetime(2026,11,11,7,0,tzinfo=timezone.utc)
        self.assertTrue(target_is_past_in_new_york("2026-11-10",after_utc_midnight))

    def test_eastern_summer_dst(self):
        summer=datetime(2026,7,11,2,0,tzinfo=timezone.utc)
        self.assertFalse(target_is_past_in_new_york("2026-07-10",summer))

if __name__=="__main__":
    unittest.main()
