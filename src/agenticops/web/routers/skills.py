"""Skills API endpoints — extracted from app.py (no logic change)."""

from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Body, File, HTTPException, UploadFile

from agenticops.web.schemas import *  # noqa — keep same namespace as app.py

router = APIRouter()


@router.get("/api/skills")
async def api_list_skills():
    """Return available agent skills with rich metadata."""
    from agenticops.skills.loader import discover_skills

    skills = discover_skills()
    result = []
    for s in skills:
        refs_dir = s.path / "references"
        ref_count = len(list(refs_dir.glob("*.md"))) if refs_dir.is_dir() else 0
        domain = s.metadata.get("domain", "general")
        result.append({
            "name": s.name,
            "description": s.description,
            "is_draft": s.is_draft,
            "domain": domain,
            "tools": s.tools,
            "ref_count": ref_count,
        })
    return result


@router.get("/api/skills/improvements")
async def api_list_skill_improvements(status: str = "all", limit: int = 50):
    """List skill improvements, optionally filtered by status."""
    from agenticops.skills.improvement_store import list_pending, list_history, list_all
    if status == "pending":
        return list_pending()
    elif status == "history":
        return list_history(limit)
    else:
        return list_all(limit)


@router.get("/api/skills/improvements/history")
async def api_skill_improvements_history(limit: int = 50):
    """Backward-compatible alias."""
    from agenticops.skills.improvement_store import list_history
    return list_history(limit=limit)


@router.post("/api/skills/improvements/batch-dismiss")
async def api_batch_dismiss_improvements(body: dict):
    """Dismiss multiple improvement records by setting status to 'dismissed'."""
    from agenticops.skills.improvement_store import update_improvement
    ids = body.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
    results = []
    for record_id in ids:
        updated = update_improvement(record_id, "dismissed")
        results.append({"id": record_id, "dismissed": updated is not None})
    return {"results": results}


@router.get("/api/skills/{name}")
async def api_get_skill(name: str):
    """Return full skill detail including SKILL.md body and references."""
    from agenticops.skills.loader import discover_skills, load_skill_body

    skills = discover_skills()
    skill = None
    for s in skills:
        if s.name == name:
            skill = s
            break
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    body = load_skill_body(name) or ""
    refs_dir = skill.path / "references"
    references = (
        [f.name for f in sorted(refs_dir.glob("*.md"))]
        if refs_dir.is_dir()
        else []
    )
    domain = skill.metadata.get("domain", "general")

    return {
        "name": skill.name,
        "description": skill.description,
        "is_draft": skill.is_draft,
        "domain": domain,
        "tools": skill.tools,
        "ref_count": len(references),
        "references": references,
        "body_markdown": body,
        "metadata": skill.metadata,
    }


@router.post("/api/skills/generate")
async def api_generate_skill(req: dict):
    """Generate a skill from a natural language description (LLM call)."""
    description = req.get("description", "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    from agenticops.skills.evolution import generate_skill_from_description

    result = generate_skill_from_description(description)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])

    content = result.get("content", "")
    return {
        "name": result["name"],
        "description": result["description"],
        "body_preview": content[:2000],
        "full_content": content,
        "references": result.get("references", {}),
    }


@router.post("/api/skills/draft")
async def api_save_draft_skill(req: dict):
    """Save a generated or imported skill as a draft."""
    name = req.get("name", "").strip()
    description = req.get("description", "").strip()
    content = req.get("content", "").strip()
    if not name or not description or not content:
        raise HTTPException(
            status_code=400, detail="name, description, and content are required"
        )

    from agenticops.skills.evolution import create_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache

    references = req.get("references") or None
    path = create_draft_skill(name, description, content, references)
    _invalidate_skills_cache()
    return {"name": name, "path": str(path)}


@router.post("/api/skills/import")
async def api_import_skill(file: UploadFile = File(...)):
    """Import a skill from an uploaded .md or .zip file."""
    import tempfile
    import zipfile

    from agenticops.skills.evolution import create_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache, parse_frontmatter

    filename = file.filename or "upload"
    content_bytes = await file.read()

    if filename.endswith(".md"):
        text = content_bytes.decode("utf-8")
        fm, body = parse_frontmatter(text)
        name = fm.get("name", filename.replace(".md", "").replace("SKILL", "skill"))
        description = fm.get("description", name)
        path = create_draft_skill(name, description, body)
        _invalidate_skills_cache()
        return {"name": name, "path": str(path)}

    elif filename.endswith(".zip"):
        with tempfile.TemporaryDirectory() as tmpdir:
            zip_path = Path(tmpdir) / "upload.zip"
            zip_path.write_bytes(content_bytes)

            with zipfile.ZipFile(zip_path, "r") as zf:
                for info in zf.infolist():
                    if info.filename.startswith("/") or ".." in info.filename:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid path in zip: {info.filename}",
                        )
                    if not info.filename.endswith(".md") and not info.is_dir():
                        raise HTTPException(
                            status_code=400,
                            detail=f"Only .md files allowed in zip, found: {info.filename}",
                        )
                zf.extractall(tmpdir)

            extracted = Path(tmpdir)
            skill_md_files = list(extracted.rglob("SKILL.md"))
            if not skill_md_files:
                raise HTTPException(
                    status_code=400,
                    detail="No SKILL.md found in zip archive",
                )

            skill_md = skill_md_files[0]
            skill_dir = skill_md.parent
            text = skill_md.read_text(encoding="utf-8")
            fm, body = parse_frontmatter(text)
            name = fm.get("name", skill_dir.name)
            description = fm.get("description", name)

            refs_dir = skill_dir / "references"
            references = None
            if refs_dir.is_dir():
                references = {}
                for ref_file in refs_dir.glob("*.md"):
                    references[ref_file.name] = ref_file.read_text(encoding="utf-8")

            path = create_draft_skill(name, description, body, references)
            _invalidate_skills_cache()
            return {"name": name, "path": str(path)}

    else:
        raise HTTPException(
            status_code=400,
            detail="Only .md and .zip files are supported",
        )


@router.delete("/api/skills/{name}")
async def api_delete_skill(name: str):
    """Delete a draft skill. Published skills cannot be deleted via API."""
    from agenticops.skills.loader import discover_skills
    from agenticops.skills.review import reject_draft_skill

    skills = discover_skills()
    for s in skills:
        if s.name == name:
            if not s.is_draft:
                raise HTTPException(
                    status_code=403,
                    detail=f"Skill '{name}' is published and cannot be deleted via API",
                )
            if reject_draft_skill(name):
                return {"deleted": True, "name": name}
            raise HTTPException(status_code=500, detail="Failed to delete skill")
    raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")


@router.put("/api/skills/{name}")
async def api_update_skill(name: str, body: dict = Body(...)):
    """Update a draft skill's SKILL.md content. Only drafts are editable."""
    from agenticops.skills.evolution import update_draft_skill
    from agenticops.skills.loader import _invalidate_skills_cache
    content = body.get("content", "")
    if not content.strip():
        raise HTTPException(status_code=400, detail="content is required")
    result = update_draft_skill(name, content)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found")
    _invalidate_skills_cache()
    return {"updated": True, "name": name, "path": str(result)}


@router.post("/api/skills/{name}/review")
async def api_review_skill(name: str):
    """Get diff data for a draft skill vs its published version."""
    from agenticops.skills.review import review_draft_skill
    result = review_draft_skill(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found or not a draft")
    return result


@router.post("/api/skills/{name}/promote")
async def api_promote_skill(name: str):
    """Promote a draft skill to published. The current published version is backed up."""
    from agenticops.skills.review import promote_skill
    from agenticops.skills.loader import _invalidate_skills_cache
    success = promote_skill(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Draft skill '{name}' not found or promotion failed")
    _invalidate_skills_cache()
    return {"promoted": True, "name": name}


@router.post("/api/skills/{name}/improve")
async def api_improve_skill(name: str, body: dict = Body(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    """Use LLM to auto-improve an existing skill. Creates a draft."""
    from agenticops.services.skill_improvement_service import trigger_skill_improvement, run_skill_improvement
    improvement = body.get("improvement", "")
    if not improvement.strip():
        raise HTTPException(status_code=400, detail="improvement description is required")
    result = trigger_skill_improvement(
        skill_name=name,
        gap_description=improvement,
        trigger=body.get("trigger", "manual"),
        source=body.get("source", "web"),
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    # Schedule LLM generation in background
    background_tasks.add_task(
        run_skill_improvement,
        record_id=result["record_id"],
        skill_name=name,
        gap_description=improvement,
    )

    return result


@router.post("/api/skills/{name}/rollback")
async def api_rollback_skill(name: str):
    """Roll back a published skill to its most recent archived version (multi-gen backup)."""
    from agenticops.skills.review import rollback_skill
    if not rollback_skill(name):
        raise HTTPException(status_code=404, detail=f"No archived version to roll back for '{name}'")
    return {"rolled_back": True, "name": name}


@router.post("/api/skills/{name}/restore")
async def api_restore_skill(name: str):
    """Restore a curator-archived skill from skills/.archive/ back to draft."""
    from agenticops.skills.curator import restore_skill
    if not restore_skill(name):
        raise HTTPException(status_code=404, detail=f"Archived skill '{name}' not found")
    return {"restored": True, "name": name}
