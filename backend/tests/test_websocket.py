import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.receptionist import Conversation, LlmUnavailableError, OllamaReceptionist


def test_chat_session_identifies_selected_business():
    with TestClient(app).websocket_connect("/chat/hua_lu_peking_duck") as socket:
        event = socket.receive_json()
    assert event["type"] == "session.ready"
    assert event["business_name"] == "Hua Lu Peking Duck"


def test_business_list_includes_all_four_chat_profiles():
    response = TestClient(app).get("/businesses")

    assert [business["id"] for business in response.json()["businesses"]] == [
        "hua_lu_peking_duck",
        "apex_auto_works",
        "insurance_comparison",
        "credit_card_comparison",
    ]


@pytest.mark.parametrize(
    ("persona_id", "persona_name"),
    [
        ("insurance_comparison", "Insurance Comparison"),
        ("credit_card_comparison", "Credit Card Comparison"),
    ],
)
def test_document_personas_open_chat_sessions(persona_id, persona_name):
    with TestClient(app).websocket_connect(f"/chat/{persona_id}") as socket:
        event = socket.receive_json()

    assert event["type"] == "session.ready"
    assert event["business_name"] == persona_name


def test_chat_rejects_invalid_message_shape():
    with TestClient(app).websocket_connect("/chat/apex_auto_works") as socket:
        socket.receive_json()
        socket.send_text("not-json")
        event = socket.receive_json()
    assert event["code"] == "invalid_message"


def test_availability_endpoint_reports_mock_slots():
    response = TestClient(app).get("/availability/hua_lu_peking_duck?date=2026-10-02")
    payload = response.json()
    assert response.status_code == 200
    assert payload["business_id"] == "hua_lu_peking_duck"
    assert any(slot["time"] == "2026-10-02T17:30:00" for slot in payload["slots"])
    assert any(slot["time"] == "2026-10-02T18:30:00" and not slot["available"] for slot in payload["slots"])


@pytest.mark.asyncio
async def test_receptionist_wraps_local_ollama_failures():
    class BrokenClient:
        async def complete(self, *args, **kwargs):
            raise LlmUnavailableError("Local Ollama is unavailable.")

    receptionist = OllamaReceptionist("llama3.1:8b", client=BrokenClient())
    conversation = Conversation(
        business={
            "business_name": "Demo",
            "knowledge_base_summary": "Test",
            "required_variables": ["name"],
        }
    )
    conversation.add_user_message("Hello")

    with pytest.raises(LlmUnavailableError, match="Local Ollama"):
        await receptionist.reply(conversation)
