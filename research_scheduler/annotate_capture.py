"""Attach a vetted pregame collection window to a frozen research capture."""
import argparse
import json
from pathlib import Path

ALLOWED={"development","morning","two_hours","fifteen_minutes"}

def annotate(capture,context):
    if context.get("window") not in ALLOWED:
        raise ValueError("Unknown research scheduler window")
    if context.get("target_date") != capture.get("forecasts",{}).get("target_date"):
        raise ValueError("Scheduler date does not match model target")
    if "scheduler_context" in capture:
        raise ValueError("Capture was already annotated")
    output=dict(capture)
    output["scheduler_context"]={k:context[k] for k in
                                 ("target_date","window","bucket","game_ids","trigger_path") if k in context}
    return output

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--capture",type=Path,required=True)
    parser.add_argument("--context",type=Path,required=True)
    args=parser.parse_args()
    capture=json.loads(args.capture.read_text(encoding="utf-8"))
    context=json.loads(args.context.read_text(encoding="utf-8"))
    args.capture.write_text(json.dumps(annotate(capture,context),indent=2,allow_nan=False),encoding="utf-8")

if __name__=="__main__":
    main()
