import json


def parse_chat_payload(raw: str) -> tuple[str | None, str | None]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None, "invalid_message"
    if not isinstance(payload, dict) or not isinstance(payload.get("message"), str):
        return None, "invalid_message"
    text = payload["message"].strip()
    return (text, None) if text else (None, "empty_message")
