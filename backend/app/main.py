from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .document_search import LocalDocumentSearch
from .message_protocol import parse_chat_payload
from .prompt_builder import BusinessConfigStore, UnknownBusinessError
from .receptionist import Conversation, LlmUnavailableError, OllamaReceptionist
from .tools import get_mock_availability_slots


def event(event_type: str, **payload: object) -> dict[str, object]:
    return {"type": event_type, "timestamp": datetime.now(timezone.utc).isoformat(), **payload}


app = FastAPI(title="Universal AI Contact Centre POC")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"])
app.state.businesses = BusinessConfigStore(settings.business_config_path)
document_files = {
    path
    for business in app.state.businesses.all().values()
    if business.get("persona_type") == "document"
    for path in business["document_files"]
}
app.state.document_search = LocalDocumentSearch(settings.knowledge_path, document_files)
app.state.receptionist = OllamaReceptionist(settings.ollama_model, settings.ollama_base_url)


@app.get("/health")
async def health() -> dict[str, object]:
    inference = await app.state.receptionist.health()
    return {
        "status": "ok",
        "businesses": list(app.state.businesses.all()),
        "inference": inference,
    }


@app.get("/businesses")
async def businesses() -> dict[str, object]:
    return {"businesses": [{"id": key, "name": value["business_name"]} for key, value in app.state.businesses.all().items()]}


@app.get("/availability/{business_id}")
async def availability(business_id: str, date: str | None = None) -> dict[str, object]:
    try:
        business = app.state.businesses.get(business_id)
    except UnknownBusinessError:
        return {"error": f"No business configuration exists for '{business_id}'."}
    target_date = date or datetime.now(timezone.utc).date().isoformat()
    slots = get_mock_availability_slots(business, target_date)
    return {
        "business_id": business_id,
        "business_name": business["business_name"],
        "date": target_date,
        "slots": slots,
        "available_slots": [slot["time"] for slot in slots if slot["available"]],
    }


@app.websocket("/chat/{business_id}")
async def chat(websocket: WebSocket, business_id: str) -> None:
    await websocket.accept()
    try:
        business = app.state.businesses.get(business_id)
    except UnknownBusinessError:
        await websocket.send_json(event("error", code="unknown_business", message=f"No business configuration exists for '{business_id}'."))
        await websocket.close(code=1008)
        return

    conversation = Conversation(
        business=business,
        document_search=app.state.document_search if business.get("persona_type") == "document" else None,
    )
    await websocket.send_json(event("session.ready", business_id=business_id, business_name=business["business_name"]))
    try:
        while True:
            raw = await websocket.receive_text()
            text, error_code = parse_chat_payload(raw)
            if error_code == "invalid_message":
                await websocket.send_json(event("error", code=error_code, message='Send JSON like {"message": "hello"}.'))
                continue
            if error_code == "empty_message":
                await websocket.send_json(event("error", code=error_code, message="Please enter a message."))
                continue
            conversation.add_user_message(text)
            try:
                reply, executions = await app.state.receptionist.reply(conversation)
                await websocket.send_json(event("assistant.message", text=reply, tools=executions))
            except LlmUnavailableError as exc:
                await websocket.send_json(event("error", code="llm_unavailable", message=str(exc)))
    except WebSocketDisconnect:
        return
