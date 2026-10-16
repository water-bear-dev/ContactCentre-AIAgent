from pathlib import Path


def test_active_state_contains_resume_contract():
    state = Path(__file__).resolve().parents[2] / "ACTIVE_STATE.md"
    contents = state.read_text(encoding="utf-8")
    for heading in ("## Objective", "## Exact next action", "## Resume prompt"):
        assert heading in contents

