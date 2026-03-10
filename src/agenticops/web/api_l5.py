"""Memory + Proactive + Learning API routes for ClawOps frontend."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, HTTPException

logger = logging.getLogger(__name__)

memory_router = APIRouter(prefix="/api/memory", tags=["memory"])
proactive_router = APIRouter(prefix="/api/proactive", tags=["proactive"])
learning_router = APIRouter(prefix="/api/learning", tags=["learning"])


# ── Memory APIs ───────────────────────────────────────────────

@memory_router.get("/agents")
async def memory_agents():
    """Per-agent memory statistics."""
    try:
        from agenticops.memory import get_agent_memory
        agent_ids = [
            "rca_agent", "detect_agent", "scan_agent", "executor_agent",
            "sre_agent", "reporter_agent", "main_agent", "proactive_agent",
        ]
        results = []
        for aid in agent_ids:
            try:
                mem = get_agent_memory(aid)
                stats = await mem.get_stats()
                results.append({"agent_id": aid, **stats})
            except Exception:
                results.append({"agent_id": aid, "total": 0, "by_type": {}})
        return {"agents": results}
    except ImportError:
        return {"agents": [], "error": "Memory module not available"}


@memory_router.get("/{agent_id}/entries")
async def memory_entries(
    agent_id: str,
    memory_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Query memory entries for a specific agent."""
    try:
        from agenticops.memory import get_agent_memory
        mem = get_agent_memory(agent_id)
        entries = await mem.recall_recent(limit=limit)
        if memory_type:
            entries = [e for e in entries if e.memory_type.value == memory_type]
        return {
            "agent_id": agent_id,
            "count": len(entries),
            "entries": [
                {
                    "id": e.id,
                    "content": e.content[:500],
                    "memory_type": e.memory_type.value,
                    "confidence": round(e.confidence, 3),
                    "recall_count": e.recall_count,
                    "created_at": e.created_at,
                }
                for e in entries
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@memory_router.get("/{agent_id}/reflections")
async def memory_reflections(agent_id: str, limit: int = Query(20, ge=1, le=100)):
    """Get reflection entries for agent."""
    try:
        from agenticops.memory import get_agent_memory
        from agenticops.memory.types import MemoryType
        mem = get_agent_memory(agent_id)
        entries = await mem.recall_recent(limit=200)
        reflections = [e for e in entries if e.memory_type == MemoryType.REFLECTION][:limit]
        return {
            "agent_id": agent_id,
            "count": len(reflections),
            "reflections": [
                {
                    "id": e.id,
                    "content": e.content,
                    "confidence": round(e.confidence, 3),
                    "created_at": e.created_at,
                }
                for e in reflections
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Proactive APIs ────────────────────────────────────────────

@proactive_router.get("/alerts")
async def proactive_alerts(limit: int = Query(20, ge=1, le=100)):
    """Recent proactive (predictive) alerts."""
    try:
        from agenticops.memory import get_agent_memory
        mem = get_agent_memory("proactive_agent")
        entries = await mem.recall_recent(limit=200)
        alerts = [
            {
                "id": e.id,
                "content": e.content,
                "confidence": round(e.confidence, 3),
                "created_at": e.created_at,
            }
            for e in entries
            if "PROACTIVE_ALERT" in e.content
        ][:limit]
        return {"count": len(alerts), "alerts": alerts}
    except Exception as exc:
        return {"count": 0, "alerts": [], "error": str(exc)}


@proactive_router.get("/patterns")
async def proactive_patterns():
    """Detected recurring patterns."""
    try:
        from agenticops.memory import get_agent_memory
        from agenticops.proactive.pattern_watch import PatternWatch
        mem = get_agent_memory("proactive_agent")
        pw = PatternWatch()
        patterns = await pw.scan(mem)
        return {
            "count": len(patterns),
            "patterns": [
                {
                    "category": p.category,
                    "occurrences": p.occurrences,
                    "score": round(p.score, 3),
                }
                for p in patterns
            ],
        }
    except Exception as exc:
        return {"count": 0, "patterns": [], "error": str(exc)}


@proactive_router.get("/stats")
async def proactive_stats():
    """Proactive agent statistics."""
    try:
        from agenticops.memory import get_agent_memory
        mem = get_agent_memory("proactive_agent")
        stats = await mem.get_stats()
        entries = await mem.recall_recent(limit=200)
        alert_count = sum(1 for e in entries if "PROACTIVE_ALERT" in e.content)
        return {
            "total_memories": stats.get("total", 0),
            "total_alerts": alert_count,
            "by_type": stats.get("by_type", {}),
        }
    except Exception as exc:
        return {"total_memories": 0, "total_alerts": 0, "error": str(exc)}


# ── Learning APIs ─────────────────────────────────────────────

@learning_router.get("/timeline")
async def learning_timeline(limit: int = Query(30, ge=1, le=100)):
    """Learning events timeline (skills created, SOPs generated, patterns learned)."""
    events = []

    # Gather from multiple agents' memories
    try:
        from agenticops.memory import get_agent_memory
        for agent_id in ["rca_agent", "proactive_agent"]:
            try:
                mem = get_agent_memory(agent_id)
                entries = await mem.recall_recent(limit=100)
                for e in entries:
                    event_type = None
                    if "CASE_STUDY" in e.content:
                        event_type = "case_study"
                    elif "SKILL_GAP" in e.content or "skill" in e.content.lower():
                        event_type = "skill"
                    elif "SOP" in e.content:
                        event_type = "sop"
                    elif "PROACTIVE_ALERT" in e.content:
                        event_type = "prediction"
                    if event_type:
                        events.append({
                            "type": event_type,
                            "agent": agent_id,
                            "content": e.content[:300],
                            "confidence": round(e.confidence, 3),
                            "created_at": e.created_at,
                        })
            except Exception:
                continue
    except ImportError:
        pass

    # Sort by time, newest first
    events.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"count": len(events[:limit]), "events": events[:limit]}


@learning_router.get("/skills")
async def learning_skills():
    """Auto-detected skill gaps and created skills."""
    try:
        from agenticops.memory import get_agent_memory
        mem = get_agent_memory("rca_agent")
        entries = await mem.recall_recent(limit=200)
        skills = [
            {
                "id": e.id,
                "content": e.content[:300],
                "confidence": round(e.confidence, 3),
                "created_at": e.created_at,
            }
            for e in entries
            if "SKILL_GAP" in e.content or "skill" in e.content.lower()
        ]
        return {"count": len(skills), "skills": skills}
    except Exception as exc:
        return {"count": 0, "skills": [], "error": str(exc)}


@learning_router.get("/sops")
async def learning_sops():
    """Auto-generated SOPs."""
    try:
        import os
        sop_dir = os.path.join(os.path.dirname(__file__), "..", "..", "sop_drafts")
        sops = []
        if os.path.isdir(sop_dir):
            for fname in sorted(os.listdir(sop_dir), reverse=True):
                if fname.endswith(".md"):
                    fpath = os.path.join(sop_dir, fname)
                    with open(fpath) as f:
                        content = f.read(1000)
                    sops.append({
                        "filename": fname,
                        "preview": content[:500],
                        "size": os.path.getsize(fpath),
                    })
        return {"count": len(sops), "sops": sops}
    except Exception as exc:
        return {"count": 0, "sops": [], "error": str(exc)}
