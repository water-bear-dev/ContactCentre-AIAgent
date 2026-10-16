import pytest

from app.document_search import LocalDocumentSearch
from app.receptionist import Conversation, OllamaReceptionist


def test_local_search_returns_source_page_and_section(tmp_path):
    policy = tmp_path / "insurance" / "policy.md"
    policy.parent.mkdir()
    policy.write_text(
        "# Policy\n\n<!-- Page: 7 -->\n\n## Accidental damage\n\n"
        "Accidental damage cover applies to insured vehicles under the policy.",
        encoding="utf-8",
    )
    search = LocalDocumentSearch(tmp_path, ["insurance/policy.md"])

    results = search.search("accidental damage cover", ["insurance/policy.md"])

    assert results
    assert results[0].source == "insurance/policy.pdf"
    assert results[0].page == 7
    assert results[0].section == "Accidental damage"
    assert "insured vehicles" in results[0].text


def test_local_search_returns_no_results_for_unmatched_terms(tmp_path):
    (tmp_path / "policy.md").write_text("# Policy\n\nVehicle cover applies.", encoding="utf-8")
    search = LocalDocumentSearch(tmp_path, ["policy.md"])

    assert search.search("dental surgery", ["policy.md"]) == []


def test_local_search_rejects_corrupt_empty_markdown(tmp_path):
    (tmp_path / "policy.md").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="no searchable text"):
        LocalDocumentSearch(tmp_path, ["policy.md"])


def test_local_search_prefers_the_relevant_section_over_document_title(tmp_path):
    (tmp_path / "policy.md").write_text(
        "AAMI Comprehensive Car Insurance\n\n"
        "<!-- Page: 3 -->\n\nGeneral policy introduction.\n\n"
        "<!-- Page: 25 -->\n\n## Windscreen damage\n\n"
        "The policy covers repair of a damaged windscreen.",
        encoding="utf-8",
    )
    search = LocalDocumentSearch(tmp_path, ["policy.md"])

    result = search.search("windscreen repair", ["policy.md"])[0]

    assert result.page == 25
    assert result.section == "Windscreen damage"


def test_local_search_extracts_plain_text_sections_from_pdf_conversion(tmp_path):
    (tmp_path / "policy.md").write_text(
        "<!-- Page: 12 -->\n\n"
        "3.2. How to get an interest-free period on purchases\n\n"
        "Pay the full closing balance by the due date to keep the interest-free period.",
        encoding="utf-8",
    )
    search = LocalDocumentSearch(tmp_path, ["policy.md"])

    result = search.search("interest free period", ["policy.md"])[0]

    assert result.page == 12
    assert result.section == "3.2. How to get an interest-free period on purchases"


def test_local_search_rejects_paths_outside_knowledge_root(tmp_path):
    with pytest.raises(ValueError, match="escapes"):
        LocalDocumentSearch(tmp_path, ["../outside.md"])


def test_local_search_includes_matching_excerpts_from_both_comparison_documents(tmp_path):
    documents = {
        "banking/nab.md": "# Interest free periods\n\nNAB interest free periods apply to purchases.",
        "banking/commbank.md": "# Interest-free period\n\nCommBank interest-free periods apply to purchases.",
    }
    for relative_path, content in documents.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    search = LocalDocumentSearch(tmp_path, documents)

    results = search.search(
        "compare interest free periods",
        documents,
        required_files=documents,
    )

    assert {result.source for result in results} == {
        "banking/nab.pdf",
        "banking/commbank.pdf",
    }


@pytest.mark.asyncio
async def test_document_persona_uses_excerpts_without_receptionist_tools(tmp_path):
    (tmp_path / "policy.md").write_text(
        "# Cover\n\n<!-- Page: 4 -->\n\n## Windscreen\n\n"
        "The policy covers repair or replacement of a damaged windscreen.",
        encoding="utf-8",
    )
    search = LocalDocumentSearch(tmp_path, ["policy.md"])
    calls: list[dict[str, object]] = []

    class FakeClient:
        async def complete(self, messages, tools=None):
            calls.append({"messages": messages, "tools": tools})
            return {"content": "The policy covers windscreen damage."}

    receptionist = OllamaReceptionist("test-model", client=FakeClient())
    conversation = Conversation(
        business={
            "business_name": "Insurance Comparison",
            "persona_type": "document",
            "document_files": ["policy.md"],
            "document_context": "Factual policy information only.",
        },
        document_search=search,
    )
    conversation.add_user_message("Does it cover a damaged windscreen?")

    reply, tools = await receptionist.reply(conversation)

    assert reply == "The policy covers windscreen damage."
    assert tools == []
    assert calls[0]["tools"] is None
    assert "[Source: policy.pdf; page: 4; section: Windscreen]" in calls[0]["messages"][0]["content"]
    assert "Do not include citations unless the user asks." in calls[0]["messages"][0]["content"]

    conversation.add_user_message("Please cite your sources.")
    await receptionist.reply(conversation)

    assert calls[1]["tools"] is None
    assert "[Source: policy.pdf; page: 4; section: Windscreen]" in calls[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_document_persona_reports_missing_evidence_without_calling_model(tmp_path):
    (tmp_path / "policy.md").write_text("# Policy\n\nVehicle cover applies.", encoding="utf-8")
    conversation = Conversation(
        business={
            "business_name": "Credit Card Comparison",
            "persona_type": "document",
            "document_files": ["policy.md"],
        },
        document_search=LocalDocumentSearch(tmp_path, ["policy.md"]),
    )
    class UnexpectedClient:
        async def complete(self, *args, **kwargs):
            raise AssertionError("The model should not be called without matching evidence.")

    receptionist = OllamaReceptionist("test-model", client=UnexpectedClient())
    conversation.add_user_message("What is the annual fee for a travel rewards card?")

    reply, tools = await receptionist.reply(conversation)

    assert "couldn't find relevant information" in reply
    assert tools == []
