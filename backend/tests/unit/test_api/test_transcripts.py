"""Tests for the Transcripts API router.

Covers list (with filters), get, messages, and delete operations.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.models import Message, Source, Transcript


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_source(db: AsyncSession, title: str = "Test Source") -> Source:
    """Create a source for use in transcript tests."""
    source = Source(source_type="audio_file", title=title)
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def _create_transcript(
    db: AsyncSession,
    source: Source,
    title: str = "Test Transcript",
    status: str = "pending",
    **kwargs,
) -> Transcript:
    """Create a transcript in the database."""
    transcript = Transcript(
        source_id=source.id,
        title=title,
        status=status,
        language=kwargs.get("language", "en"),
        raw_text=kwargs.get("raw_text", "Test transcript content"),
        metadata_=kwargs.get("metadata", {}),
    )
    db.add(transcript)
    await db.commit()
    await db.refresh(transcript)
    return transcript


async def _create_message(
    db: AsyncSession,
    transcript: Transcript,
    content: str = "Hello world",
    speaker: str = "Alice",
    sequence: int = 0,
) -> Message:
    """Create a message in the database."""
    message = Message(
        transcript_id=transcript.id,
        content=content,
        speaker=speaker,
        sequence=sequence,
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)
    return message


# ---------------------------------------------------------------------------
# List Transcripts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_transcripts_empty(client: AsyncClient) -> None:
    """Listing transcripts when none exist returns empty items."""
    response = await client.get("/api/v1/transcripts/")
    assert response.status_code == 200

    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_transcripts_with_data(client: AsyncClient, db_session: AsyncSession) -> None:
    """Listing transcripts returns paginated results."""
    source = await _create_source(db_session)
    for i in range(3):
        await _create_transcript(db_session, source, title=f"Transcript {i}")

    response = await client.get("/api/v1/transcripts/?limit=2")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 2
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_list_transcripts_filter_by_status(client: AsyncClient, db_session: AsyncSession) -> None:
    """Filtering by status returns only matching transcripts."""
    source = await _create_source(db_session)
    await _create_transcript(db_session, source, title="Pending", status="pending")
    await _create_transcript(db_session, source, title="Completed", status="completed")
    await _create_transcript(db_session, source, title="Error", status="error")

    response = await client.get("/api/v1/transcripts/?status=completed")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_transcripts_search(client: AsyncClient, db_session: AsyncSession) -> None:
    """Search parameter filters transcripts by title."""
    source = await _create_source(db_session)
    await _create_transcript(db_session, source, title="Python Basics")
    await _create_transcript(db_session, source, title="Advanced JavaScript")

    response = await client.get("/api/v1/transcripts/?search=Python")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert "Python" in data["items"][0]["title"]


@pytest.mark.asyncio
async def test_list_transcripts_sort_descending(client: AsyncClient, db_session: AsyncSession) -> None:
    """Sorting with - prefix returns results in descending order."""
    source = await _create_source(db_session)
    await _create_transcript(db_session, source, title="First")
    await _create_transcript(db_session, source, title="Second")

    response = await client.get("/api/v1/transcripts/?sort=-created_at")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# Get Transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_transcript_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Retrieving an existing transcript returns it with messages."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source, title="My Transcript")
    await _create_message(db_session, transcript, content="Hello", sequence=0)
    await _create_message(db_session, transcript, content="World", sequence=1)

    response = await client.get(f"/api/v1/transcripts/{transcript.id}")
    assert response.status_code == 200

    data = response.json()
    assert data["id"] == str(transcript.id)
    assert data["title"] == "My Transcript"
    assert data["source"] is not None


@pytest.mark.asyncio
async def test_get_transcript_not_found(client: AsyncClient) -> None:
    """Retrieving a non-existent transcript returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/transcripts/{random_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_transcript_invalid_uuid(client: AsyncClient) -> None:
    """Retrieving with an invalid UUID returns 422."""
    response = await client.get("/api/v1/transcripts/invalid-uuid")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Get Transcript Messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_transcript_messages(client: AsyncClient, db_session: AsyncSession) -> None:
    """Getting messages for a transcript returns ordered messages."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source)
    await _create_message(db_session, transcript, content="First", sequence=0)
    await _create_message(db_session, transcript, content="Second", sequence=1)

    response = await client.get(f"/api/v1/transcripts/{transcript.id}/messages")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2
    assert data[0]["content"] == "First"
    assert data[0]["sequence"] == 0
    assert data[1]["content"] == "Second"
    assert data[1]["sequence"] == 1


@pytest.mark.asyncio
async def test_get_transcript_messages_pagination(client: AsyncClient, db_session: AsyncSession) -> None:
    """Message pagination works with skip/limit."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source)
    for i in range(5):
        await _create_message(db_session, transcript, content=f"Msg {i}", sequence=i)

    response = await client.get(f"/api/v1/transcripts/{transcript.id}/messages?skip=0&limit=2")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2
    assert data[0]["content"] == "Msg 0"


@pytest.mark.asyncio
async def test_get_messages_transcript_not_found(client: AsyncClient) -> None:
    """Getting messages for a non-existent transcript returns 404."""
    random_id = uuid.uuid4()
    response = await client.get(f"/api/v1/transcripts/{random_id}/messages")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Delete Transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_transcript_success(client: AsyncClient, db_session: AsyncSession) -> None:
    """Deleting a transcript returns 204."""
    source = await _create_source(db_session)
    transcript = await _create_transcript(db_session, source, title="To Delete")

    response = await client.delete(f"/api/v1/transcripts/{transcript.id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_delete_transcript_not_found(client: AsyncClient) -> None:
    """Deleting a non-existent transcript returns 404."""
    random_id = uuid.uuid4()
    response = await client.delete(f"/api/v1/transcripts/{random_id}")
    assert response.status_code == 404
