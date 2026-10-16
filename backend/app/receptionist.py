import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

import httpx

from .document_search import DocumentExcerpt, LocalDocumentSearch
from .prompt_builder import build_document_prompt, build_system_prompt
from .tools import execute_tool, tool_schemas_for_business


class LlmUnavailableError(RuntimeError):
    pass


def _normalize_booking_date(value: str) -> str | None:
    cleaned = re.sub(
        r"^(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b[,]?\s*",
        "",
        value.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(\d{1,2})(st|nd|rd|th)\b", r"\1", cleaned, flags=re.IGNORECASE)
    for date_format in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_booking_time(value: str) -> str | None:
    for time_format in ("%H:%M", "%I:%M %p", "%I %p"):
        try:
            return datetime.strptime(value.strip().upper(), time_format).strftime("%H:%M")
        except ValueError:
            continue
    return None


def validate_local_ollama_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Ollama URL must be an HTTP loopback URL without credentials.")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Ollama URL must be the server root, without a path, query, or fragment.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Ollama URL contains an invalid port.") from exc
    try:
        is_loopback = ip_address(parsed.hostname).is_loopback
    except ValueError:
        is_loopback = parsed.hostname.lower() == "localhost"
    if not is_loopback:
        raise ValueError("Ollama URL must use localhost or a loopback IP address.")
    return f"http://{parsed.netloc}"


class OllamaClient:
    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model = model
        self.base_url = validate_local_ollama_url(base_url)
        self._transport = transport

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "temperature": 0,
        }
        if tools is not None:
            payload.update({"tools": tools, "tool_choice": "auto"})
        try:
            async with httpx.AsyncClient(timeout=120, transport=self._transport) as client:
                response = await client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmUnavailableError(f"Local Ollama request failed at {self.base_url}: {exc}") from exc
        try:
            message = result["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmUnavailableError("Local Ollama returned a malformed chat-completion response.") from exc
        if not isinstance(message, dict):
            raise LlmUnavailableError("Local Ollama returned a malformed assistant message.")
        return message

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=3, transport=self._transport) as client:
                response = await client.get(f"{self.base_url}/v1/models")
                response.raise_for_status()
                result = response.json()
            models = result.get("data")
            if not isinstance(models, list):
                raise ValueError("Ollama model list has an invalid format.")
            model_names = [item.get("id") for item in models if isinstance(item, dict)]
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            return {
                "provider": "ollama",
                "reachable": False,
                "model": self.model,
                "model_available": False,
                "error": f"Local Ollama is unavailable at {self.base_url}: {exc}",
            }
        model_available = self.model in model_names
        return {
            "provider": "ollama",
            "reachable": True,
            "model": self.model,
            "model_available": model_available,
            "error": None if model_available else f"Model '{self.model}' is not installed in local Ollama.",
        }


@dataclass
class Conversation:
    business: dict[str, Any]
    document_search: LocalDocumentSearch | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_document_excerpts: list[DocumentExcerpt] = field(default_factory=list)
    checked_available_slots: set[tuple[str, str]] = field(default_factory=set)

    def add_user_message(self, text: str) -> None:
        self.checked_available_slots.clear()
        self.messages.append({"role": "user", "content": text})


class OllamaReceptionist:
    """Local chat and tool-routing loop for one in-memory WebSocket conversation."""

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        transport: httpx.AsyncBaseTransport | None = None,
        client: OllamaClient | None = None,
    ):
        self.model = model
        self._client = client or OllamaClient(model=model, base_url=base_url, transport=transport)

    async def health(self) -> dict[str, Any]:
        return await self._client.health()

    async def reply(self, conversation: Conversation) -> tuple[str, list[dict[str, Any]]]:
        if conversation.business.get("persona_type") == "document":
            return await self._reply_from_documents(conversation)

        messages = [{"role": "system", "content": build_system_prompt(conversation.business)}, *conversation.messages]
        executions: list[dict[str, Any]] = []
        for _ in range(4):
            assistant = await self._client.complete(messages, tools=tool_schemas_for_business(conversation.business))
            tool_calls = assistant.get("tool_calls") or []
            messages.append(assistant)
            if not tool_calls:
                text = assistant.get("content")
                if not isinstance(text, str) or not text.strip():
                    raise LlmUnavailableError("Local Ollama returned an empty assistant response.")
                conversation.messages.extend(messages[1 + len(conversation.messages):])
                return text, executions
            if not isinstance(tool_calls, list):
                raise LlmUnavailableError("Local Ollama returned malformed tool calls.")
            for tool_call in tool_calls:
                execution, tool_message = self._execute_tool_call(tool_call, conversation)
                executions.append(execution)
                messages.append(tool_message)
        raise LlmUnavailableError("Local Ollama exceeded the maximum tool-routing steps for one message.")

    def _execute_tool_call(
        self,
        tool_call: Any,
        conversation: Conversation,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        if not isinstance(tool_call, dict):
            raise LlmUnavailableError("Local Ollama returned a malformed tool call.")
        function = tool_call.get("function")
        if not isinstance(function, dict):
            raise LlmUnavailableError("Local Ollama returned a tool call without a function.")
        call_id = tool_call.get("id")
        name = function.get("name")
        arguments_value = function.get("arguments", {})
        if not isinstance(call_id, str) or not call_id or not isinstance(name, str) or not name:
            raise LlmUnavailableError("Local Ollama returned a tool call without an id or function name.")
        arguments: dict[str, Any] = {}
        try:
            parsed_arguments = json.loads(arguments_value) if isinstance(arguments_value, str) else arguments_value
            if not isinstance(parsed_arguments, dict):
                raise ValueError("Tool arguments must be a JSON object.")
            arguments = parsed_arguments
            if name == "trigger_booking":
                payload_value = arguments.get("payload")
                if payload_value is None:
                    payload_value = {key: value for key, value in arguments.items() if key != "payload"}
                if not isinstance(payload_value, dict):
                    raise ValueError("Booking details must be provided as an object.")
                payload = dict(payload_value)
                arguments = {"payload": payload}
                aliases = {
                    "name": ("customer_name",),
                    "booking_date": ("preferred_date", "date"),
                    "preferred_date": ("booking_date", "date"),
                    "booking_time": ("preferred_time", "time"),
                    "preferred_time": ("booking_time", "time"),
                    "service_needed": ("booking_details", "service", "service_type"),
                    "vehicle_registration": ("registration", "rego"),
                }
                for required_name in conversation.business.get("required_variables", []):
                    if required_name not in payload:
                        for alias in aliases.get(required_name, ()):
                            if alias in payload:
                                payload[required_name] = payload[alias]
                                break
                missing_details = [
                    required_name
                    for required_name in conversation.business.get("required_variables", [])
                    if not isinstance(payload.get(required_name), str) or not payload[required_name].strip()
                ]
                if missing_details:
                    raise ValueError(f"Booking is missing required details: {', '.join(missing_details)}.")
                arguments["payload"] = payload
                booking_date = payload.get("booking_date", payload.get("preferred_date", payload.get("date")))
                booking_time = payload.get("booking_time", payload.get("preferred_time", payload.get("time")))
                normalized_date = _normalize_booking_date(booking_date) if isinstance(booking_date, str) else None
                normalized_time = _normalize_booking_time(booking_time) if isinstance(booking_time, str) else None
                if (
                    normalized_date is None
                    or normalized_time is None
                    or (normalized_date, normalized_time) not in conversation.checked_available_slots
                ):
                    raise ValueError(
                        "Check that this booking's date and time are available before creating it."
                    )
                for key in ("booking_date", "preferred_date", "date"):
                    if key in payload:
                        payload[key] = normalized_date
                for key in ("booking_time", "preferred_time", "time"):
                    if key in payload:
                        payload[key] = normalized_time
            result = execute_tool(name, arguments, conversation.business)
        except (json.JSONDecodeError, ValueError, TypeError, KeyError) as exc:
            result = f"Tool execution failed: {exc}"
            execution = {"name": name, "arguments": arguments, "error": result}
        else:
            execution = {"name": name, "arguments": arguments, "result": result}
            if (
                name == "check_availability"
                and isinstance(arguments.get("date"), str)
                and isinstance(arguments.get("time"), str)
                and result.endswith(" is available.")
            ):
                checked_date = _normalize_booking_date(arguments["date"])
                checked_time = _normalize_booking_time(arguments["time"])
                if checked_date and checked_time:
                    conversation.checked_available_slots.add((checked_date, checked_time))
        return execution, {"role": "tool", "tool_call_id": call_id, "content": result}

    async def _reply_from_documents(self, conversation: Conversation) -> tuple[str, list[dict[str, Any]]]:
        if conversation.document_search is None:
            raise LlmUnavailableError("Local policy document search is not configured for this persona.")
        query = next(
            (message["content"] for message in reversed(conversation.messages) if message["role"] == "user"),
            "",
        )
        if not isinstance(query, str) or not query.strip():
            raise LlmUnavailableError("A document question is required.")
        if re.search(r"\b(cite|citations?|sources?|references?)\b", query.lower()) and conversation.last_document_excerpts:
            excerpts = conversation.last_document_excerpts
        else:
            normalized_query = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
            files = list(conversation.business.get("default_comparison_files", conversation.business["document_files"]))
            for path, triggers in conversation.business.get("alternate_document_triggers", {}).items():
                if any(re.sub(r"[^a-z0-9]+", " ", trigger.lower()).strip() in normalized_query for trigger in triggers):
                    files.append(path)
            search_query = query
            if re.search(r"\b(compare|comparison|difference|differences|versus|vs)\b", normalized_query):
                search_query = f"{query} {conversation.business.get('comparison_search_terms', '')}"
            excerpts = conversation.document_search.search(
                search_query,
                files,
                required_files=conversation.business.get("default_comparison_files", ()),
            )
        if not excerpts:
            reply = "I couldn't find relevant information in the supplied policy documents. Please specify the policy or share an updated document if you need a more current answer."
            conversation.messages.append({"role": "assistant", "content": reply})
            return reply, []

        conversation.last_document_excerpts = excerpts
        prompt_excerpts = [
            {"source": excerpt.source, "section": excerpt.section, "page": excerpt.page, "text": excerpt.text}
            for excerpt in excerpts
        ]
        messages = [
            {"role": "system", "content": build_document_prompt(conversation.business, prompt_excerpts)},
            *conversation.messages,
        ]
        assistant = await self._client.complete(messages)
        reply = assistant.get("content")
        if not isinstance(reply, str) or not reply.strip():
            raise LlmUnavailableError("Local Ollama returned an empty assistant response.")
        conversation.messages.append({"role": "assistant", "content": reply})
        return reply, []
