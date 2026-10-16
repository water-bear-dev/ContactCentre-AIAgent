from pathlib import Path

from app.prompt_builder import BusinessConfigStore
from app.tools import TOOL_SCHEMAS, execute_tool, tool_schemas_for_business


BUSINESS = {"business_name": "Apex Auto Works", "knowledge_base_summary": "Vehicle servicing.", "required_variables": ["name"]}


def test_tool_schemas_expose_all_routing_actions():
    names = {tool["function"]["name"] for tool in TOOL_SCHEMAS}
    assert names == {"search_kb", "check_availability", "trigger_booking", "transfer_call", "save_message"}


def test_booking_schema_requires_profile_specific_fields_and_time():
    businesses = BusinessConfigStore(Path(__file__).resolve().parents[1] / "config.json").all()

    for business_id, time_field in (
        ("hua_lu_peking_duck", "booking_time"),
        ("apex_auto_works", "preferred_time"),
    ):
        schemas = tool_schemas_for_business(businesses[business_id])
        booking = next(tool["function"] for tool in schemas if tool["function"]["name"] == "trigger_booking")
        required = booking["parameters"]["required"]

        assert time_field in required
        assert set(businesses[business_id]["required_variables"]) <= set(required)
        assert "payload" not in booking["parameters"]["properties"]
        assert booking["parameters"]["additionalProperties"] is False


def test_mock_booking_tool_returns_success(capsys):
    result = execute_tool("trigger_booking", {"payload": {"name": "Alex", "phone": "0400000000"}}, BUSINESS)
    assert result == "trigger_booking completed successfully"
    assert "Apex Auto Works" in capsys.readouterr().out
