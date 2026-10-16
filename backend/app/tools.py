import json
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Callable


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search the active business knowledge base before answering a general question.",
            "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check whether a requested booking time is available before confirming a reservation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date in YYYY-MM-DD format."},
                    "time": {"type": "string", "description": "Time in HH:MM 24-hour format."},
                },
                "required": ["date", "time"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_booking",
            "description": "Create a booking only after the caller has confirmed all required booking details.",
            "parameters": {"type": "object", "properties": {"payload": {"type": "object", "additionalProperties": {"type": "string"}}}, "required": ["payload"], "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transfer_call",
            "description": "Transfer a caller to a human for an escalation or when the knowledge base cannot answer.",
            "parameters": {"type": "object", "properties": {"department": {"type": "string"}}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_message",
            "description": "Save a caller message after collecting name, phone, and message.",
            "parameters": {"type": "object", "properties": {"payload": {"type": "object", "additionalProperties": {"type": "string"}}}, "required": ["payload"], "additionalProperties": False},
        },
    },
]


def tool_schemas_for_business(business: dict[str, Any]) -> list[dict[str, Any]]:
    schemas = deepcopy(TOOL_SCHEMAS)
    required_variables = list(business.get("required_variables", []))
    date_variable = next(
        (name for name in ("booking_date", "preferred_date") if name in required_variables),
        "preferred_date",
    )
    time_variable = "booking_time" if date_variable == "booking_date" else "preferred_time"
    booking_required = list(required_variables)
    if time_variable not in booking_required:
        booking_required.append(time_variable)
    booking_tool = next(tool for tool in schemas if tool["function"]["name"] == "trigger_booking")
    booking_tool["function"]["parameters"] = {
        "type": "object",
        "properties": {name: {"type": "string"} for name in booking_required},
        "required": booking_required,
        "additionalProperties": False,
    }
    return schemas


def get_mock_availability_slots(business: dict[str, Any], date: str) -> list[dict[str, Any]]:
    availability = business.get("availability", {})
    hours = availability.get("hours", {})
    date_obj = datetime.strptime(date, "%Y-%m-%d")
    daily_hours = hours.get(date_obj.strftime("%A"), {})
    if not daily_hours:
        return []
    start = datetime.strptime(f"{date} {daily_hours['open']}", "%Y-%m-%d %H:%M")
    end = datetime.strptime(f"{date} {daily_hours['close']}", "%Y-%m-%d %H:%M")
    slot_duration = int(availability.get("slot_duration_minutes", 60))
    booked_slots = {slot.strip() for slot in availability.get("booked_slots", [])}
    slots: list[dict[str, Any]] = []
    current = start
    while current + timedelta(minutes=slot_duration) <= end:
        slot_time = current.strftime("%Y-%m-%dT%H:%M:00")
        slots.append({"time": slot_time, "available": slot_time not in booked_slots})
        current += timedelta(minutes=slot_duration)
    return slots


def _logged_success(name: str, payload: dict[str, Any]) -> str:
    print(f"[mock tool] {name}: {json.dumps(payload, sort_keys=True)}")
    return f"{name} completed successfully"


def search_kb(query: str, *, business: dict[str, Any]) -> str:
    return _logged_success("search_kb", {"query": query, "knowledge_base_summary": business["knowledge_base_summary"]})


def check_availability(date: str, time: str, *, business: dict[str, Any]) -> str:
    slot_time = f"{date}T{time}:00"
    slots = get_mock_availability_slots(business, date)
    matched = next((slot for slot in slots if slot["time"] == slot_time), None)
    if matched is None:
        return f"No availability information for {date} at {time}."
    status = "available" if matched["available"] else "unavailable"
    _logged_success("check_availability", {"business": business["business_name"], "date": date, "time": time, "status": status})
    return f"The requested slot on {date} at {time} is {status}."


def trigger_booking(payload: dict[str, str], *, business: dict[str, Any]) -> str:
    return _logged_success("trigger_booking", {"business": business["business_name"], "payload": payload})


def transfer_call(department: str = "front desk", *, business: dict[str, Any]) -> str:
    return _logged_success("transfer_call", {"business": business["business_name"], "department": department})


def save_message(payload: dict[str, str], *, business: dict[str, Any]) -> str:
    return _logged_success("save_message", {"business": business["business_name"], "payload": payload})


def execute_tool(name: str, arguments: dict[str, Any], business: dict[str, Any]) -> str:
    handlers: dict[str, Callable[..., str]] = {
        "search_kb": search_kb,
        "check_availability": check_availability,
        "trigger_booking": trigger_booking,
        "transfer_call": transfer_call,
        "save_message": save_message,
    }
    if name not in handlers:
        raise ValueError(f"Unknown tool requested: {name}")
    return handlers[name](**arguments, business=business)
