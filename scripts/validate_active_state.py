#!/usr/bin/env python3
"""Fail fast when the cross-harness handoff record is incomplete."""
from pathlib import Path
import sys

required = ("## Objective", "## Status", "## Last updated", "## Current step", "## Exact next action", "## Blockers", "## Resume prompt")
state = Path(__file__).resolve().parents[1] / "ACTIVE_STATE.md"
contents = state.read_text(encoding="utf-8") if state.exists() else ""
missing = [heading for heading in required if heading not in contents]
placeholders = [line for line in contents.splitlines() if "TODO" in line.upper()]
if missing or placeholders:
    if missing:
        print(f"Missing ACTIVE_STATE.md sections: {', '.join(missing)}")
    if placeholders:
        print("ACTIVE_STATE.md contains unresolved TODO placeholders")
    sys.exit(1)
print("ACTIVE_STATE.md is handoff-ready")

