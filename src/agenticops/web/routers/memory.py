"""Cross-session memory API endpoints (facts + experiences) — extracted from app.py."""

from typing import List

from fastapi import APIRouter, HTTPException, Query

from agenticops.models import AgentMemory, AgentMemoryFact, get_db_session
from agenticops.web.schemas import MemoryExperienceResponse, MemoryFactResponse

router = APIRouter()


@router.get("/api/memory/facts", response_model=List[MemoryFactResponse])
async def api_get_memory_facts(
    min_confidence: float = Query(default=0.7, ge=0.0, le=1.0),
):
    """Query structured facts from cross-session memory."""
    from agenticops.web.memory_service import MemoryService

    svc = MemoryService()
    facts = svc.get_facts(min_confidence=min_confidence)
    return [
        MemoryFactResponse(
            id=f.id,
            category=f.category,
            key=f.key,
            value=f.value,
            confidence_score=f.confidence_score,
            source_session_id=f.source_session_id,
            created_at=f.created_at,
            updated_at=f.updated_at,
        )
        for f in facts
    ]


@router.delete("/api/memory/facts/{fact_id}", status_code=204)
async def api_delete_memory_fact(fact_id: int):
    """Delete a specific fact by its primary key id."""
    with get_db_session() as db:
        fact = db.query(AgentMemoryFact).filter(AgentMemoryFact.id == fact_id).first()
        if not fact:
            raise HTTPException(404, "Fact not found")
        db.delete(fact)


@router.get("/api/memory/experiences", response_model=List[MemoryExperienceResponse])
async def api_get_memory_experiences():
    """Query vectorized experience memories (without embedding_vector)."""
    with get_db_session() as db:
        memories = (
            db.query(AgentMemory)
            .order_by(AgentMemory.created_at.desc())
            .all()
        )
        db.expunge_all()
    return [
        MemoryExperienceResponse(
            id=m.id,
            session_id=m.session_id,
            memory_type=m.memory_type,
            content_text=m.content_text,
            created_at=m.created_at,
        )
        for m in memories
    ]
