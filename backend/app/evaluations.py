import json
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from .document_search import LocalDocumentSearch
from .message_protocol import parse_chat_payload
from .prompt_builder import BusinessConfigStore
from .receptionist import Conversation, LlmUnavailableError, OllamaClient, OllamaReceptionist


def load_eval_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid eval JSON on line {line_number}: {exc}") from exc
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError(f"Eval case on line {line_number} must be an object with a string id.")
        cases.append(case)
    if not cases:
        raise ValueError(f"No eval cases found in {path}.")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Eval case ids must be unique.")
    return cases


def _mock_transport(case: dict[str, Any], captured: list[dict[str, Any]]) -> httpx.MockTransport:
    responses = deque(case.get("mock_responses", []))
    health_status = case.get("mock_health", {"data": [{"id": "llama3.1:8b"}]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization"):
            captured.append({"authorization_header_sent": True})
            return httpx.Response(401)
        if request.url.path == "/v1/models":
            if "status_code" in health_status:
                return httpx.Response(health_status["status_code"])
            return httpx.Response(200, json=health_status)
        if request.url.path != "/v1/chat/completions":
            return httpx.Response(404)
        try:
            payload = json.loads(request.content)
        except json.JSONDecodeError:
            return httpx.Response(400)
        captured.append(payload)
        if not responses:
            return httpx.Response(500, json={"error": "No mocked model response remains."})
        mocked = responses.popleft()
        if "status_code" in mocked:
            return httpx.Response(mocked["status_code"], json=mocked.get("body", {}))
        if "body" in mocked:
            return httpx.Response(200, json=mocked["body"])
        return httpx.Response(200, json={"choices": [{"message": mocked["message"]}]})

    return httpx.MockTransport(handler)


def _missing_tool_sequences(tool_names: list[str], sequences: list[list[str]]) -> list[list[str]]:
    missing = []
    for sequence in sequences:
        actual_names = iter(tool_names)
        if not all(any(actual == expected for actual in actual_names) for expected in sequence):
            missing.append(sequence)
    return missing


async def run_offline_case(
    case: dict[str, Any],
    businesses: dict[str, dict[str, Any]],
    knowledge_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    failures: list[str] = []
    tools: list[dict[str, Any]] = []
    responses: list[str] = []
    sources: set[str] = set()
    error_code: str | None = None
    captured_requests: list[dict[str, Any]] = []
    kind = case["kind"]

    if kind == "message_validation":
        _, error_code = parse_chat_payload(case["raw"])
    elif kind == "unknown_profile":
        error_code = "unknown_business" if case["profile"] not in businesses else None
    elif kind == "model_health":
        client = OllamaClient(
            "llama3.1:8b",
            transport=_mock_transport(case, captured_requests),
        )
        health = await client.health()
        error_code = "model_unavailable" if not health["model_available"] else None
        if health["reachable"] != case.get("expected_reachable", True):
            failures.append("Ollama reachability did not match expected outcome.")
    elif kind == "missing_document":
        missing_path = case.get("document_path", "missing/policy.md")
        try:
            LocalDocumentSearch(knowledge_root, [missing_path])
        except FileNotFoundError:
            error_code = "missing_document"
    elif kind == "corrupt_document":
        relative_path = case.get("document_path", "corrupt/policy.md")
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            document_path = temporary_root / relative_path
            document_path.parent.mkdir(parents=True, exist_ok=True)
            document_path.write_text(case.get("document_content", ""), encoding="utf-8")
            try:
                LocalDocumentSearch(temporary_root, [relative_path])
            except ValueError:
                error_code = "corrupt_document"
    else:
        profile_id = case["profile"]
        business = businesses[profile_id]
        search: LocalDocumentSearch | None = None
        if business.get("persona_type") == "document":
            try:
                search = LocalDocumentSearch(knowledge_root, business["document_files"])
            except (FileNotFoundError, ValueError) as exc:
                failures.append(f"Document index setup failed: {exc}")
        transport = _mock_transport(case, captured_requests)
        receptionist = OllamaReceptionist("llama3.1:8b", transport=transport)
        conversation = Conversation(business=business, document_search=search)
        for message in case.get("turns", []):
            conversation.add_user_message(message)
            try:
                reply, executions = await receptionist.reply(conversation)
                responses.append(reply)
                tools.extend(executions)
                sources.update(excerpt.source for excerpt in conversation.last_document_excerpts)
            except LlmUnavailableError:
                error_code = "llm_unavailable"
                break

        if any(request.get("authorization_header_sent") for request in captured_requests):
            failures.append("Offline run unexpectedly sent an Authorization header.")

    expected_error = case.get("expected_error")
    if error_code != expected_error:
        failures.append(f"Expected error {expected_error!r}, received {error_code!r}.")
    tool_names = [tool["name"] for tool in tools]
    successful_tool_names = [tool["name"] for tool in tools if "error" not in tool]
    missing_tools = set(case.get("required_tools", [])) - set(successful_tool_names)
    if missing_tools:
        failures.append(f"Expected tools did not succeed: {sorted(missing_tools)}.")
    missing_sequences = _missing_tool_sequences(successful_tool_names, case.get("required_tool_sequences", []))
    if missing_sequences:
        failures.append(f"Required tool-call order was not followed: {missing_sequences}.")
    forbidden_tools = set(case.get("forbidden_tools", [])) & set(tool_names)
    if forbidden_tools:
        failures.append(f"Forbidden tool calls occurred: {sorted(forbidden_tools)}.")
    tool_errors = {tool["name"] for tool in tools if "error" in tool}
    missing_tool_errors = set(case.get("expected_tool_errors", [])) - tool_errors
    if missing_tool_errors:
        failures.append(f"Missing expected tool errors: {sorted(missing_tool_errors)}.")
    missing_sources = set(case.get("expected_sources", [])) - sources
    if missing_sources:
        failures.append(f"Missing expected source excerpts: {sorted(missing_sources)}.")
    response_text = "\n".join(responses).lower()
    missing_terms = {term.lower() for term in case.get("required_terms", []) if term.lower() not in response_text}
    if missing_terms:
        failures.append(f"Response missed expected concepts/terms: {sorted(missing_terms)}.")
    forbidden_terms = {term.lower() for term in case.get("forbidden_terms", []) if term.lower() in response_text}
    if forbidden_terms:
        failures.append(f"Response included forbidden concepts/terms: {sorted(forbidden_terms)}.")
    for request in captured_requests:
        if request.get("model") != "llama3.1:8b":
            failures.append("Request used an unexpected model.")

    return {
        "id": case["id"],
        "passed": not failures,
        "failures": failures,
        "error": error_code,
        "responses": responses,
        "tools": tools,
        "sources": sorted(sources),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }


async def run_live_evaluations(
    cases: list[dict[str, Any]],
    businesses: dict[str, dict[str, Any]],
    receptionist: OllamaReceptionist,
    document_search: LocalDocumentSearch,
    judge: bool = False,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for case in cases:
        if not case.get("live", False):
            continue
        started = time.perf_counter()
        response_texts: list[str] = []
        tools: list[dict[str, Any]] = []
        sources: set[str] = set()
        error: str | None = None
        business = businesses[case["profile"]]
        conversation = Conversation(
            business=business,
            document_search=document_search if business.get("persona_type") == "document" else None,
        )
        for message in case.get("turns", []):
            conversation.add_user_message(message)
            try:
                reply, executions = await receptionist.reply(conversation)
            except LlmUnavailableError as exc:
                error = str(exc)
                break
            response_texts.append(reply)
            tools.extend(executions)
            sources.update(excerpt.source for excerpt in conversation.last_document_excerpts)
        response_text = "\n".join(response_texts)
        tool_names = [tool["name"] for tool in tools]
        successful_tool_names = [tool["name"] for tool in tools if "error" not in tool]
        failures = []
        for name in set(case.get("required_tools", [])) - set(successful_tool_names):
            failures.append(f"Expected tool did not succeed: {name}.")
        missing_sequences = _missing_tool_sequences(successful_tool_names, case.get("required_tool_sequences", []))
        if missing_sequences:
            failures.append(f"Required tool-call order was not followed: {missing_sequences}.")
        for name in set(case.get("forbidden_tools", [])) & set(tool_names):
            failures.append(f"Forbidden tool was called: {name}.")
        for source in set(case.get("expected_sources", [])) - sources:
            failures.append(f"Expected source was not retrieved: {source}.")
        lower_response = response_text.lower()
        for term in case.get("required_terms", []):
            if term.lower() not in lower_response:
                failures.append(f"Expected concept/term missing: {term}.")
        for term in case.get("forbidden_terms", []):
            if term.lower() in lower_response:
                failures.append(f"Forbidden concept/term found: {term}.")
        tool_errors = {tool["name"] for tool in tools if "error" in tool}
        for name in set(case.get("expected_tool_errors", [])) - tool_errors:
            failures.append(f"Expected tool failure did not occur: {name}.")
        if error:
            failures.append(f"Local model request failed: {error}")
        result: dict[str, Any] = {
            "id": case["id"],
            "passed": not failures,
            "failures": failures,
            "responses": response_texts,
            "tools": tools,
            "sources": sorted(sources),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "human_review_notes": "",
        }
        if judge and response_texts:
            prompt = (
                "Evaluate the response against the supplied case criteria. Return JSON with integer "
                "scores from 0 to 2 for groundedness, relevance, and policy compliance, plus a short "
                "explanation. This score is advisory and must not change the automated pass/fail result.\n"
                f"Case: {json.dumps({key: case[key] for key in ('id', 'scenario', 'required_terms', 'forbidden_terms') if key in case})}\n"
                f"Response: {response_text}"
            )
            judge_message = await receptionist._client.complete([{"role": "user", "content": prompt}])
            result["advisory_local_judge"] = judge_message.get("content")
        results.append(result)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": receptionist.model,
        "provider": "ollama",
        "results": results,
        "summary": {
            "total": len(results),
            "passed": sum(result["passed"] for result in results),
            "failed": sum(not result["passed"] for result in results),
        },
    }
