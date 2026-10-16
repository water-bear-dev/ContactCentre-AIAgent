import json

import pytest

from app.prompt_builder import BusinessConfigStore, UnknownBusinessError, build_system_prompt


def test_business_config_and_prompt_are_tenant_specific(tmp_path):
    config = {"demo": {"business_name": "Demo Dental", "knowledge_base_summary": "Open weekdays.", "required_variables": ["name", "date"]}}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    business = BusinessConfigStore(path).get("demo")
    prompt = build_system_prompt(business)
    assert "Demo Dental" in prompt
    assert "Open weekdays." in prompt
    assert "name, date" in prompt


def test_missing_business_raises(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(UnknownBusinessError):
        BusinessConfigStore(path).get("missing")

