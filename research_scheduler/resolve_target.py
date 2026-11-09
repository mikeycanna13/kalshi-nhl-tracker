"""Resolve a strictly validated research scheduler-trigger target from Git history."""
import argparse
from datetime import date
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re
import subprocess

PREFIX = re.compile(r"^scheduler/triggers/(\d{4}-\d{2}-\d{2})/(morning|two_hours|fifteen_minutes)_[A-Za-z0-9T_-]+\.json$")

def target_is_past_in_new_york(target_date, now):
    """Avoid rejecting ET evening games merely because UTC is next day."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("UTC-offset-aware now required")
    return date.fromisoformat(target_date) < now.astimezone(ZoneInfo("America/New_York")).date()


def resolve(changed_paths, root, fallback):
    date.fromisoformat(fallback)
    matches = [p for p in changed_paths if PREFIX.fullmatch(p)]
    if len(matches) > 1:
        raise ValueError("Multiple scheduler triggers in one commit")
    if not matches:
        return {"target_date":fallback,"window":"development"}
    path = matches[0]
    match = PREFIX.fullmatch(path)
    content = json.loads((Path(root) / path).read_text(encoding="utf-8"))
    if content.get("schema") != "nhl_scheduler_trigger_v1":
        raise ValueError("Invalid scheduler schema")
    if content.get("target_date") != match.group(1) or content.get("window") != match.group(2):
        raise ValueError("Trigger path/metadata mismatch")
    if content.get("research_branch") != "research/nhl-model-benchmarks":
        raise ValueError("Scheduler cannot target another branch")
    game_ids = content.get("game_ids")
    if not isinstance(game_ids,list) or not game_ids or any(not isinstance(x,int) or x<=0 for x in game_ids):
        raise ValueError("Invalid NHL game IDs")
    if not re.fullmatch(r"[A-Za-z0-9T_-]+",str(content.get("bucket",""))):
        raise ValueError("Invalid scheduled time bucket")
    date.fromisoformat(content["target_date"])
    return {"target_date":content["target_date"],"window":content["window"],
            "bucket":content["bucket"],"game_ids":game_ids,"trigger_path":path}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit",required=True)
    parser.add_argument("--fallback",required=True)
    parser.add_argument("--root",default=".")
    args=parser.parse_args()
    paths=subprocess.check_output(["git","show","--pretty=format:","--name-only","--no-renames",args.commit],text=True).splitlines()
    print(json.dumps(resolve(paths,args.root,args.fallback),separators=(",",":")))

if __name__=="__main__":
    main()
