"""Knowledge-base vectors from a model provider (MVP-2.9.0 N35).

`OpenAICompatibleEmbedding(ref)` embeds with an OpenAI-compatible provider's embedding model (`POST {base}/embeddings`
— LiteLLM proxy, OpenRouter, vLLM, Ollama, LM Studio); its dimension is what the first call returns. An
Anthropic-compatible server has no embeddings endpoint, so its models are never offered or accepted here.

The model in use is `embedding_model_ref` — an administrator's choice in runtime_settings (key `embedding`), else the
yaml default — and kb/embeddings.get_embedding_client picks it before Titan. The stored vectors remember which model
made them (`indexed_with`; vectors stored before N35 are Titan's): a store holding another model's vectors needs a
rebuild, which `reembed` does on the SQLite vector store — every case embedded first, then all vectors replaced in one
transaction, so a failure keeps the old ones.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

import numpy as np

from agenticops.kb.embeddings import EmbeddingClient
from agenticops.llm import registry
from agenticops.llm.presets import OPENAI

logger = logging.getLogger(__name__)

RUNTIME_KEY = "embedding"
FIELD = registry.EMBEDDING_FIELD
_reembed_lock = threading.Lock()


class OpenAICompatibleEmbedding(EmbeddingClient):
    MAX_INPUT_CHARS = 8000

    def __init__(self, ref: str):
        from agenticops.llm.refs import parse_ref
        r = parse_ref(ref)
        self._ref, self._provider, self._model_id = ref, r.provider, r.model_id
        self._dim = 0
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai
            from agenticops.llm.factory import client_args
            cfg = registry.get(self._provider)
            if cfg is None or not cfg.enabled:
                raise RuntimeError(f"the provider «{self._provider}» is not available")
            self._client = openai.OpenAI(**client_args(cfg, timeout=cfg.timeout_seconds, max_retries=1))
        return self._client

    def embed(self, text: str) -> Optional[np.ndarray]:
        if not text or not text.strip():
            return None
        try:
            resp = self._get_client().embeddings.create(model=self._model_id, input=text[: self.MAX_INPUT_CHARS])
            vector = np.array(resp.data[0].embedding, dtype=np.float32)
        except Exception as e:
            logger.warning("Embedding with %s failed: %s", self._ref, type(e).__name__)
            return None
        self._dim = int(vector.shape[0])
        return vector

    @property
    def dimension(self) -> int:
        return self._dim


# ── which model, and what the stored vectors were made with ──────────────────

def _stored() -> dict:
    from agenticops.services import runtime_settings
    value = runtime_settings.get(RUNTIME_KEY)
    return dict(value) if isinstance(value, dict) else {}


def model_ref() -> str:
    """The embedding model reference in use ("" = Titan on Bedrock, while Bedrock is on)."""
    return registry.raw_value(FIELD)


def current_model() -> str:
    """What new vectors are made with: the reference, Titan's id while Bedrock is on, or "" (no vectors)."""
    from agenticops.config import settings
    if not getattr(settings, "embedding_enabled", True):
        return ""
    ref = model_ref()
    if ref:
        return ref
    return settings.embedding_model_id if registry.bedrock_enabled() else ""


def vectors_current() -> bool:
    """Whether the stored vectors are the model in use's — vectors of two models are not comparable, even when their
    dimensions match (Titan's 1024 is also bge-m3's), so until a rebuild the case search answers from keywords."""
    current = current_model()
    return bool(current) and _indexed_with() == current


def _indexed_with() -> str:
    from agenticops.config import settings
    return _stored().get("indexed_with") or settings.embedding_model_id     # before N35 only Titan made vectors


def _sqlite_store():
    from agenticops.config import settings
    from agenticops.kb.vector_store import SQLiteVectorStore, get_vector_store
    if settings.vector_storage in ("rds", "s3"):
        return None
    store = get_vector_store()
    return store if isinstance(store, SQLiteVectorStore) else None


def serves_embeddings(cfg) -> bool:
    """Only an OpenAI-compatible provider serves embeddings (the Messages API has no embeddings endpoint)."""
    return cfg is not None and cfg.kind == OPENAI


def presets() -> list[dict]:
    """The embedding models that can be chosen: enabled ones of enabled OpenAI-compatible providers."""
    from agenticops.llm import catalog
    out = []
    for p in catalog.all_presets(purpose="embedding"):
        cfg = registry.get(p["provider"])
        if serves_embeddings(cfg):
            out.append(p)
    return out


def status() -> dict:
    from agenticops.config import settings
    from agenticops.kb.vector_store import get_vector_store
    try:
        vectors = get_vector_store().count()
    except Exception:
        logger.warning("Could not count the stored vectors", exc_info=True)
        vectors = None
    store = _sqlite_store()
    current, indexed = current_model(), _indexed_with()
    ref = model_ref()
    return {"model_ref": ref, "model": current,
            "source": "provider" if ref else "bedrock" if current else "none",
            "dimension": store.stored_dimension() if store else None,
            "vectors": vectors, "indexed_with": indexed,
            "needs_reembed": bool(vectors) and bool(current) and indexed != current,
            "store": settings.vector_storage, "can_reembed": store is not None, "presets": presets()}


def set_model(ref: str, actor) -> dict:
    """Choose the embedding model ("" = the default). Refused (422): not an enabled embedding model of an enabled
    provider (unknown_model), or a provider that is not OpenAI-compatible (unsupported_kind). An empty choice means
    Titan while Bedrock is on and no vectors while it is off. One audit row per change; the client is rebuilt on
    next use."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.kb.embeddings import reset_embedding_client
    from agenticops.llm.model_settings import problem
    from agenticops.models import get_db_session
    from agenticops.services import runtime_settings
    ref = (ref or "").strip()
    if ref:
        found = problem(ref, purpose="embedding")
        if found:
            raise registry.ProviderError(422, "unknown_model", f"«{ref}» cannot embed: {found[1]}",
                                         extra={"reason": found[0]})
        from agenticops.llm.refs import parse_ref
        cfg = registry.get(parse_ref(ref).provider)
        if not serves_embeddings(cfg):
            raise registry.ProviderError(422, "unsupported_kind",
                                         f"«{ref}»: only an OpenAI-compatible provider serves embeddings")
    before = model_ref()
    if ref != before:
        value = {**_stored(), "model_ref": ref}
        value.setdefault("indexed_with", _indexed_with())   # the vectors stored so far keep their model's name
        with get_db_session() as s:
            runtime_settings.put(RUNTIME_KEY, value, getattr(actor, "key", str(actor)), session=s)
            AuditService.log(Actions.UPDATE, EntityTypes.SYSTEM, FIELD, entity_name="settings",
                             actor=getattr(actor, "key", str(actor)), user_id=getattr(actor, "user_id", None),
                             old_values={FIELD: before}, new_values={FIELD: ref}, session=s)
        reset_embedding_client()
    return status()


def reembed(actor) -> dict:
    """Embed every case and SOP of the knowledge base with the model in use and replace all stored vectors with them.
    All or nothing: a case that cannot be embedded leaves every old vector in place (502 embedding_failed).
    SQLite vector store only (409 unsupported_store); one at a time (409 reembed_running)."""
    from pathlib import Path

    from agenticops.audit.service import AuditService
    from agenticops.config import settings
    from agenticops.kb.case_study import CaseStudy
    from agenticops.kb.embeddings import get_embedding_client, reset_embedding_client
    from agenticops.kb.vector_store import VectorRecord
    from agenticops.models import get_db_session
    from agenticops.services import runtime_settings
    store = _sqlite_store()
    if store is None:
        raise registry.ProviderError(409, "unsupported_store",
                                     f"rebuilding is done on the SQLite vector store only (this one: {settings.vector_storage})")
    current = current_model()
    if not current:
        raise registry.ProviderError(409, "no_model", "no embedding model is in use (Bedrock is off and none is chosen)")
    if not _reembed_lock.acquire(blocking=False):
        raise registry.ProviderError(409, "reembed_running", "a rebuild is already running")
    try:
        reset_embedding_client()                         # a fresh connectivity test of the model in use
        client = get_embedding_client()
        records: list[VectorRecord] = []
        cases = failed = 0
        for path in sorted(Path(settings.cases_dir).glob("*.md")):
            try:
                case = CaseStudy.from_markdown(path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("Skipping %s: not a case study", path.name)
                continue
            cases += 1
            meta = {"efficiency_score": case.lessons_learned.efficiency_score, "verified": str(case.verified).lower()}
            for field, text in (("symptom", case.embedding_inputs.symptom_vector_text),
                                ("root_cause", case.embedding_inputs.root_cause_vector_text)):
                if not text:
                    continue
                vec = client.embed(text)
                if vec is None:
                    failed += 1
                    continue
                records.append(VectorRecord(case_id=case.case_id or path.stem, field_name=field, vector=vec,
                                            resource_type=case.meta.resource_type.upper(), metadata=meta))
        # the SOPs' vectors are in the same table (pipeline/rag_pipeline._embed_sop): they are rebuilt too, never dropped
        from agenticops.pipeline.rag_pipeline import sop_vector_records
        sops = 0
        for path in sorted(Path(settings.sops_dir).glob("*.md")):
            sops += 1
            sop_records, sop_failed = sop_vector_records(path.read_text(encoding="utf-8"), path.name, client)
            records += sop_records
            failed += sop_failed
        if failed or ((cases or sops) and not records):
            raise registry.ProviderError(502, "embedding_failed",
                                         f"{failed or 'every'} text(s) could not be embedded with {current}; "
                                         "the stored vectors were kept")
        store.replace_all(records)
        with get_db_session() as s:
            runtime_settings.put(RUNTIME_KEY, {**_stored(), "indexed_with": current},
                                 getattr(actor, "key", str(actor)), session=s)
            AuditService.log("reembed", "kb_vectors", "case_vectors", entity_name=current,
                             actor=getattr(actor, "key", str(actor)), user_id=getattr(actor, "user_id", None),
                             new_values={"cases": cases, "sops": sops, "vectors": len(records)}, session=s)
        return {"cases": cases, "sops": sops, "vectors": len(records), "failed": 0}
    finally:
        _reembed_lock.release()
