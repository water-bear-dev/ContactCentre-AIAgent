from pathlib import Path

import pytest

from app.evaluations import load_eval_cases, run_offline_case
from app.prompt_builder import BusinessConfigStore


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent


def test_eval_dataset_has_unique_ids_and_covers_all_four_profiles():
    cases = load_eval_cases(BACKEND_ROOT / "evals" / "cases.jsonl")

    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["profile"] for case in cases if case.get("live")} == {
        "hua_lu_peking_duck",
        "apex_auto_works",
        "insurance_comparison",
        "credit_card_comparison",
    }
    assert {case["kind"] for case in cases} >= {
        "model_call",
        "message_validation",
        "unknown_profile",
        "model_health",
        "missing_document",
        "corrupt_document",
    }


@pytest.mark.asyncio
async def test_all_deterministic_evaluation_cases_pass():
    cases = load_eval_cases(BACKEND_ROOT / "evals" / "cases.jsonl")
    businesses = BusinessConfigStore(BACKEND_ROOT / "config.json").all()

    results = [
        await run_offline_case(case, businesses, REPOSITORY_ROOT / "knowledge")
        for case in cases
    ]

    failures = {
        result["id"]: result["failures"]
        for result in results
        if not result["passed"]
    }
    assert failures == {}
