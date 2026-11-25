"""Model providers (MVP-2.9.0 N35): the providers beyond Bedrock, their models, the Bedrock switch.

    GET    /api/model-providers                              providers (never a key), Bedrock, presets, can_edit
    POST   /api/model-providers                              add one → 201
    PATCH  /api/model-providers/{name}                       edit (merges like an account edit; clear_api_key)
    DELETE /api/model-providers/{name}                       409 in_use + the settings that reference it
    PUT    /api/model-providers/bedrock                      {enabled} → the settings that resolve to Bedrock
    POST   /api/model-providers/{name}/test                  {model_id?} → list / chat / tools
    POST   /api/model-providers/{name}/refresh-models        read the provider's model list
    GET    /api/model-providers/{name}/models?purpose=       the models
    POST   /api/model-providers/{name}/models                add a model by hand
    PATCH  /api/model-providers/{name}/models/{model_id}     attributes, enabled
    GET    /api/kb/embedding                                 the knowledge base's embedding model, its vectors
    PUT    /api/kb/embedding                                 {model_ref} — "" = Titan on Bedrock
    POST   /api/kb/reembed                                   rebuild every vector with the model in use (SQLite)

With sign-in on, every write needs an admin (an API key's scopes cap it); a read is what Settings is — writers and
admins, a read-only account only holding `settings_read`. Refusals are `{"detail": {"detail", "code", ...}}`. Blocking work (the database, the
provider's own HTTP) runs in a worker thread. A write clears the cached chat agents (web and IM) and the embedding client.
"""
from __future__ import annotations

import asyncio
import dataclasses
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from agenticops.auth.actor import Actor
from agenticops.auth.viewer import can_view_settings, read_only_detail
from agenticops.config import settings
from agenticops.llm import catalog, embeddings, presets, probe, registry
from agenticops.web.deps import current_actor, require_authenticated_user
from agenticops.web.routers.upload_settings import _can_edit

router = APIRouter(tags=["model-providers"])
BASE = "/api/model-providers"


def _refused(e: registry.ProviderError) -> JSONResponse:
    return JSONResponse(status_code=e.status, content={"detail": {"detail": e.detail, "code": e.code, **e.extra}})


def _bad_body(detail: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": {"detail": detail, "code": "invalid_body"}})


async def _admin(request: Request) -> None:
    if settings.api_auth_enabled:
        await require_authenticated_user(request, admin=True)


async def _reader(request: Request) -> Optional[JSONResponse]:
    if not settings.api_auth_enabled:
        return None
    user = await require_authenticated_user(request, admin=False)
    request.state.user = user                  # as APIAuthMiddleware sets it: can_edit reads it
    if not can_view_settings(user):            # writers and admins; a read-only account only with settings_read
        return JSONResponse(status_code=403, content=read_only_detail())
    return None


async def _json(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body


def _rebuild_chat_agents() -> None:
    """Drop every model built on the old answer: the web chats' and the IM chats' cached agents, and the knowledge
    base's embedding client (a cached Titan client kept calling Bedrock after it was turned off — final review)."""
    from agenticops.im.session_manager import clear_all_agents
    from agenticops.kb.embeddings import reset_embedding_client
    from agenticops.web.app import _chat_sessions   # import here: app imports this router
    _chat_sessions.clear()
    clear_all_agents()
    reset_embedding_client()


def _view(v: catalog.ProviderModelView) -> dict:
    out = dataclasses.asdict(v)
    if isinstance(out.get("tools_probe_at"), datetime):
        out["tools_probe_at"] = out["tools_probe_at"].isoformat()
    out["tools"] = catalog.effective_tools(v)
    return out


def _listing(request: Request) -> dict:
    from agenticops.credentials.store import get_credential_store
    return {"bedrock": {"enabled": registry.bedrock_enabled(), "region": settings.bedrock_region,
                        "references": registry.bedrock_references()},
            "providers": registry.list_public(), "presets": presets.public(),
            "credential_backend": get_credential_store().backend_name, "can_edit": _can_edit(request)}


async def _write(fn):
    """Run a write in a worker thread; a ProviderError becomes its refusal, anything else clears the chat agents."""
    try:
        result = await asyncio.to_thread(fn)
    except registry.ProviderError as e:
        return _refused(e)
    _rebuild_chat_agents()
    return result


@router.get(BASE)
async def list_providers(request: Request):
    refused = await _reader(request)
    if refused is not None:
        return refused
    return await asyncio.to_thread(_listing, request)


@router.post(BASE, status_code=201)
async def create_provider(request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict):
        return _bad_body("send a JSON object")
    result = await _write(lambda: registry.create(body, actor))
    return result if isinstance(result, JSONResponse) else JSONResponse(status_code=201, content=result)


@router.put(f"{BASE}/bedrock")
async def set_bedrock(request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return _bad_body("send {\"enabled\": true|false}")
    return await _write(lambda: registry.set_bedrock_enabled(body["enabled"], actor))


@router.patch(f"{BASE}/{{name}}")
async def update_provider(name: str, request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict):
        return _bad_body("send a JSON object")
    clear = bool(body.pop("clear_api_key", False))
    return await _write(lambda: registry.update(name, body, actor, clear_api_key=clear))


@router.delete(f"{BASE}/{{name}}")
async def delete_provider(name: str, request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    result = await _write(lambda: registry.delete(name, actor))
    return result if isinstance(result, JSONResponse) else Response(status_code=204)


@router.post(f"{BASE}/{{name}}/test")
async def test_provider(name: str, request: Request):
    await _admin(request)
    body = await _json(request)
    model_id = body.get("model_id") if isinstance(body, dict) else None
    try:
        return await asyncio.to_thread(probe.test, name, model_id if isinstance(model_id, str) and model_id else None)
    except registry.ProviderError as e:
        return _refused(e)


@router.post(f"{BASE}/{{name}}/refresh-models")
async def refresh_models(name: str, request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    return await _write(lambda: catalog.refresh(name, actor))


@router.get(f"{BASE}/{{name}}/models")
async def list_models(name: str, request: Request, purpose: Optional[str] = None):
    refused = await _reader(request)
    if refused is not None:
        return refused
    if registry.get(name) is None:
        return _refused(registry.ProviderError(404, "not_found", f"no provider «{name}»"))
    views = await asyncio.to_thread(catalog.list_models, name, purpose=purpose)
    return [_view(v) for v in views]


@router.post(f"{BASE}/{{name}}/models", status_code=201)
async def add_model(name: str, request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict):
        return _bad_body("send a JSON object")
    result = await _write(lambda: catalog.add_manual(name, body, actor))
    return result if isinstance(result, JSONResponse) else JSONResponse(status_code=201, content=_view(result))


@router.patch(f"{BASE}/{{name}}/models/{{model_id:path}}")
async def patch_model(name: str, model_id: str, request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict):
        return _bad_body("send a JSON object")
    result = await _write(lambda: catalog.patch_model(name, model_id, body, actor))
    return result if isinstance(result, JSONResponse) else _view(result)


# ── the knowledge base's embedding model ──────────────────────────────────────

@router.get("/api/kb/embedding")
async def kb_embedding(request: Request):
    refused = await _reader(request)
    if refused is not None:
        return refused
    return await asyncio.to_thread(embeddings.status)


@router.put("/api/kb/embedding")
async def set_kb_embedding(request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    body = await _json(request)
    if not isinstance(body, dict) or not isinstance(body.get("model_ref", ""), str):
        return _bad_body("send {\"model_ref\": \"<provider>::<model>\" | \"\"}")
    try:
        return await asyncio.to_thread(embeddings.set_model, body.get("model_ref", ""), actor)
    except registry.ProviderError as e:
        return _refused(e)


@router.post("/api/kb/reembed")
async def kb_reembed(request: Request, actor: Actor = Depends(current_actor)):
    await _admin(request)
    try:
        return await asyncio.to_thread(embeddings.reembed, actor)
    except registry.ProviderError as e:
        return _refused(e)
