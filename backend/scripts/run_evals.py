import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.document_search import LocalDocumentSearch
from app.evaluations import load_eval_cases, run_live_evaluations, run_offline_case
from app.prompt_builder import BusinessConfigStore
from app.receptionist import OllamaReceptionist


BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
CASES_PATH = BACKEND_ROOT / "evals" / "cases.jsonl"
REPORTS_PATH = BACKEND_ROOT / "eval-results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic or local Ollama evaluations.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Run all JSONL cases against mocked local services.")
    mode.add_argument("--live", action="store_true", help="Run model-quality cases against local Ollama.")
    parser.add_argument("--judge", action="store_true", help="Add an advisory score from the same local model.")
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only this case id; may be repeated.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    if args.judge and not args.live:
        raise ValueError("--judge can only be used with --live.")

    cases = load_eval_cases(CASES_PATH)
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case["id"] in requested]
        found = {case["id"] for case in cases}
        if found != requested:
            raise ValueError(f"Unknown evaluation case ids: {sorted(requested - found)}")
    businesses = BusinessConfigStore(settings.business_config_path).all()
    live = args.live

    if live:
        document_files = {
            path
            for business in businesses.values()
            if business.get("persona_type") == "document"
            for path in business["document_files"]
        }
        document_search = LocalDocumentSearch(settings.knowledge_path, document_files)
        receptionist = OllamaReceptionist(settings.ollama_model, settings.ollama_base_url)
        health = await receptionist.health()
        if not health["reachable"] or not health["model_available"]:
            raise RuntimeError(f"Live evaluations require a reachable Ollama model: {health['error']}")
        report = await run_live_evaluations(cases, businesses, receptionist, document_search, judge=args.judge)
    else:
        results = [
            await run_offline_case(case, businesses, settings.knowledge_path)
            for case in cases
        ]
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "provider": "ollama-mocked",
            "results": results,
            "summary": {
                "total": len(results),
                "passed": sum(result["passed"] for result in results),
                "failed": sum(not result["passed"] for result in results),
            },
        }

    REPORTS_PATH.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_PATH / f"eval-{('live' if live else 'offline')}-{timestamp}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "report": str(report_path)}, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
