"""Deterministic workspace document fixtures; no document service or model calls."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from deeptutor.learning import workspace_sources as documents
from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_generation import _source_payload, ground_topic_sources
from deeptutor.learning.topic_materials import build_topic_materials, render_topic_manifest


def source(**metadata):
    return TopicSource(
        id="file-source",
        kind=TopicSourceKind.WORKSPACE_FILE,
        source_id="lesson.pdf",
        label="Fixture lesson",
        excerpt="UNTRUSTED CLIENT EXCERPT",
        metadata={"workspace_id": "native-a", "path": "lesson.pdf", **metadata},
    )


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(documents, "current_workspace_id", lambda: "native-a")
    result = {
        "ok": True,
        "status": "partial",
        "path": "lesson.pdf",
        "format": "pdf",
        "document": {"sha256": "a" * 64, "bytes": 1024, "unit_count": 20},
        "text": "Fixture text from a physical PDF page.",
        "units": [
            {
                "kind": "page",
                "text": "Fixture text from a physical PDF page.",
                "locator": {"page": 3, "page_kind": "pdf_physical"},
                "assets": [{"id": "pdf-page:3", "mime_type": "image/png", "locator": {"page": 3}}],
            }
        ],
        "truncated": True,
        "next_cursor": "fixture-version-bound-cursor",
        "warnings": ["fixture_partial"],
    }
    mock = AsyncMock(return_value=result)
    monkeypatch.setattr(documents, "_read_document", mock)
    return mock


@pytest.mark.asyncio
async def test_grounding_retains_version_physical_locator_and_partial(reader):
    original = source(document_sha256="a" * 64, locator={"page": 3, "page_kind": "pdf_physical"})
    grounded = (await ground_topic_sources(name="Lesson", goal="Read", sources=[original]))[0]
    reader.assert_awaited_once_with(
        "native-a",
        path="lesson.pdf",
        max_chars=4000,
        max_units=8,
        start_unit=3,
        document_sha256="a" * 64,
    )
    assert grounded.available
    assert "UNTRUSTED" not in grounded.excerpt
    assert original.excerpt == "UNTRUSTED CLIENT EXCERPT"
    assert grounded.metadata["document_sha256"] == "a" * 64
    assert grounded.metadata["units"][0]["locator"] == {"page": 3, "page_kind": "pdf_physical"}
    assert grounded.metadata["next_cursor"] == "fixture-version-bound-cursor"
    assert grounded.metadata["partial"] is True
    payload = _source_payload([grounded])[0]
    assert payload["partial"] is True
    assert payload["provenance"]["document_sha256"] == "a" * 64
    assert payload["locators"][0]["page"] == 3
    assert TopicSource.model_validate_json(grounded.model_dump_json()).metadata == grounded.metadata


@pytest.mark.parametrize(
    "metadata",
    [
        {"workspace_id": "native-b"},
        {"content_workspace_id": "native-b"},
        {"workspace_id": "native-b", "content_workspace_id": "native-b"},
        {"root": "D:/not-authorized"},
        {"path": "../private.pdf"},
        {"path": "D:/private.pdf"},
        {"path": "\\\\server\\private.pdf"},
    ],
)
@pytest.mark.asyncio
async def test_untrusted_origins_and_roots_are_rejected_before_read(reader, metadata):
    grounded = await documents.ground_workspace_source(source(**metadata))
    reader.assert_not_awaited()
    assert grounded.available is False
    assert grounded.excerpt == ""
    assert grounded.metadata["read_error"].startswith("workspace_document_")


@pytest.mark.asyncio
async def test_changed_document_cannot_replace_saved_version(reader):
    grounded = await documents.ground_workspace_source(source(document_sha256="b" * 64))
    assert not grounded.available
    assert not grounded.excerpt
    assert grounded.metadata["read_error"] == "workspace_document_changed_reselect_source"


@pytest.mark.asyncio
async def test_even_an_overlong_complete_reader_result_remains_bounded_and_partial(reader):
    result = deepcopy(reader.return_value)
    result.update(status="complete", truncated=False, next_cursor=None)
    result["document"]["unit_count"] = 1
    result["units"][0]["text"] = "fixture " * 2000
    reader.return_value = result
    grounded = await documents.ground_workspace_source(source(), max_chars=1024)
    assert len(grounded.excerpt) <= 1024
    assert sum(len(unit["text"]) for unit in grounded.metadata["units"]) <= 1024
    assert grounded.metadata["partial"] is True
    assert "not the entire document" in grounded.excerpt


def test_topic_manifest_names_partial_document_without_putting_full_text_in_prompt(reader):
    materials = build_topic_materials([source()])
    manifest, index = render_topic_manifest(materials)
    assert "partial excerpt" in manifest
    assert "Fixture text from a physical PDF page" not in manifest
    assert len(index) == 1
    assert '"page": 3' in next(iter(index.values()))
    assert "a" * 64 in next(iter(index.values()))


def test_topic_origin_cannot_switch_into_another_workspace_to_authorize_a_file(reader):
    manifest, index = render_topic_manifest(
        build_topic_materials([source(workspace_id="native-b", content_workspace_id="native-b")])
    )
    reader.assert_not_awaited()
    assert index == {}
    assert "unavailable" in manifest


@pytest.mark.asyncio
async def test_unreadable_document_drops_supplied_excerpt(reader):
    reader.return_value = {"ok": False, "status": "error"}
    grounded = await documents.ground_workspace_source(source())
    assert not grounded.available
    assert not grounded.excerpt


@pytest.mark.asyncio
async def test_no_selection_reports_names_only_and_never_reads_bodies(monkeypatch, reader):
    catalog = AsyncMock(
        return_value={
            "ok": True,
            "entries": [
                {"path": "lesson.pdf", "name": "lesson.pdf", "is_dir": False, "size_bytes": 10},
            ],
            "truncated": True,
        }
    )
    monkeypatch.setattr(documents, "_list_documents", catalog)
    inventory = await documents.workspace_inventory()
    catalog.assert_awaited_once_with("native-a")
    reader.assert_not_awaited()
    assert inventory["documents"] == ["lesson.pdf"]
    assert inventory["document_bodies_read"] is False
    assert inventory["inventory_truncated"] is True
    monkeypatch.setattr(documents, "current_workspace_id", lambda: "")
    assert await documents.workspace_inventory() == {}
    assert catalog.await_count == 1


@pytest.mark.asyncio
async def test_topic_draft_with_only_workspace_names_cannot_claim_document_reading(
    monkeypatch, reader
):
    import json

    from deeptutor.learning import topic_generation

    monkeypatch.setattr(
        documents,
        "_list_documents",
        AsyncMock(
            return_value={
                "ok": True,
                "entries": [{"path": "lesson.pdf", "is_dir": False}],
            }
        ),
    )
    complete = AsyncMock(
        return_value=json.dumps(
            {
                "modules": [
                    {
                        "id": "draft",
                        "name": "Fixture",
                        "knowledge_points": [{"id": "kp", "name": "Fixture", "type": "concept"}],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(topic_generation, "complete", complete)
    draft = await topic_generation.generate_topic_draft(
        name="Fixture", goal="Read local lesson", sources=[], language="en"
    )
    reader.assert_not_awaited()
    assert draft["workspace_inventory"]["document_bodies_read"] is False
    prompt = complete.call_args.kwargs["prompt"]
    assert '"document_bodies_read": false' in prompt
    assert "do not describe or quote unread contents" in prompt


@pytest.mark.asyncio
async def test_failed_selected_workspace_document_stops_before_model_generation(
    monkeypatch, reader
):
    from deeptutor.learning import topic_generation

    reader.return_value = {"ok": False, "status": "error"}
    complete = AsyncMock()
    monkeypatch.setattr(topic_generation, "complete", complete)
    with pytest.raises(topic_generation.TopicGenerationError, match="could not be read"):
        await topic_generation.generate_topic_draft(
            name="Fixture", goal="Read local lesson", sources=[source()], language="en"
        )
    complete.assert_not_awaited()
