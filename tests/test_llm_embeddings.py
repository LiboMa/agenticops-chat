"""Knowledge-base vectors from any provider (MVP-2.9.0 N35 task 7).

The case search embeds with, in this order: the embedding model an administrator chose (`embedding_model_ref`, an
OpenAI-compatible provider's embedding model), else Bedrock's Titan while Bedrock is on, else nothing (keyword search
only). Changing the model leaves the stored vectors of the old one: the status says a rebuild is needed until the
rebuild has replaced every vector — all or nothing, and only on the SQLite vector store.
"""
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from starlette.testclient import TestClient

from tests.llm_fake_server import ADMIN, FakeLLMServer, add_model, add_provider, llm_db

REF = "local-llm::fake-embed-1"


def _case(case_id: str, symptom: str) -> str:
    from agenticops.kb.case_study import (CaseStudy, CaseStudyMeta, CaseStudyStatus, EmbeddingInputs,
                                           LessonsLearned, Resolution)
    return CaseStudy(
        case_id=case_id, title=f"Case {case_id}",
        meta=CaseStudyMeta(resource_type="EC2", severity="high", region="us-east-1", created_at="2026-11-25",
                           tags=["ec2"]),
        embedding_inputs=EmbeddingInputs(symptom_vector_text=symptom, root_cause_vector_text=f"cause of {symptom}"),
        resolution=Resolution(immediate_action="restart", long_term_fix="fix", verification_method="watch"),
        lessons_learned=LessonsLearned(what_failed="x", why_missed="y", efficiency_score=0.5),
        status=CaseStudyStatus.PENDING_REVIEW, verified=False, reuse_count=0,
        symptoms=symptom, root_cause="cause", prevention="fix",
    ).to_markdown()


@pytest.fixture
def kb(tmp_path, monkeypatch):
    import agenticops.kb.embeddings as emb
    import agenticops.kb.vector_store as vs
    settings = llm_db(tmp_path, monkeypatch, "n35-kb.db")
    cases = tmp_path / "cases"
    cases.mkdir()
    (cases / "c1.md").write_text(_case("case_1", "disk full on web host"), encoding="utf-8")
    (cases / "c2.md").write_text(_case("case_2", "cpu spike after deploy"), encoding="utf-8")
    monkeypatch.setattr(settings, "cases_dir", cases)
    monkeypatch.setattr(settings, "vector_storage", "sqlite")
    monkeypatch.setattr(settings, "embedding_enabled", True)
    monkeypatch.setattr(emb, "_embedding_client", None)
    monkeypatch.setattr(emb, "_client_initialized", False)
    monkeypatch.setattr(vs, "_vector_store", None)
    with FakeLLMServer() as fake:
        add_provider("local-llm", f"{fake.base}/v1")
        add_model("local-llm", "fake-embed-1", purpose="embedding")
        add_model("local-llm", "fake-chat-1")
        add_provider("relay", fake.base, kind="anthropic_compatible")
        add_model("relay", "embed-x", purpose="embedding")
        yield SimpleNamespace(settings=settings, fake=fake, cases=cases, monkeypatch=monkeypatch)


def _legacy_vectors(n_cases=2, dim=4):
    """What a pre-N35 installation holds: Titan's vectors (here, short ones) for each case."""
    from agenticops.kb.vector_store import VectorRecord, get_vector_store
    store = get_vector_store()
    for i in range(1, n_cases + 1):
        store.upsert(VectorRecord(case_id=f"case_{i}", field_name="symptom", vector=np.ones(dim, dtype=np.float32),
                                  resource_type="EC2", metadata={}))
    return store


def _case_ids(store):
    conn = store._get_conn()
    try:
        return sorted({r[0] for r in conn.execute("SELECT case_id FROM case_vectors")})
    finally:
        conn.close()


def test_a_provider_model_embeds(kb):
    from agenticops.kb.embeddings import get_embedding_client
    from agenticops.llm import embeddings
    from agenticops.llm.embeddings import OpenAICompatibleEmbedding
    embeddings.set_model(REF, ADMIN)
    with patch("agenticops.config.get_bedrock_boto_session", side_effect=AssertionError("Bedrock was asked")):
        client = get_embedding_client()
        assert isinstance(client, OpenAICompatibleEmbedding)
        vec = client.embed("disk full")
    assert isinstance(vec, np.ndarray) and vec.dtype == np.float32 and vec.shape == (8,) and client.dimension == 8
    sent = [r for r in kb.fake.requests if r["path"] == "/v1/embeddings"]
    assert sent and sent[-1]["body"]["model"] == "fake-embed-1"


def test_switching_needs_a_reembed_and_the_reembed_replaces_every_vector(kb):
    from agenticops.llm import embeddings
    store = _legacy_vectors()
    before = embeddings.status()
    assert before["model_ref"] == "" and before["vectors"] == 2 and before["needs_reembed"] is False
    assert before["dimension"] == 4 and before["can_reembed"] is True
    embeddings.set_model(REF, ADMIN)
    after = embeddings.status()
    assert after["model_ref"] == REF and after["source"] == "provider" and after["needs_reembed"] is True
    out = embeddings.reembed(ADMIN)
    assert out == {"cases": 2, "vectors": 4, "failed": 0}
    done = embeddings.status()
    assert done["needs_reembed"] is False and done["dimension"] == 8 and done["indexed_with"] == REF
    assert _case_ids(store) == ["case_1", "case_2"]                   # one entry per case, both fields


def test_a_failing_service_keeps_the_old_vectors_and_keyword_search(kb, caplog):
    from agenticops.kb.embeddings import NullEmbeddingClient, get_embedding_client
    from agenticops.kb.search import hybrid_search
    from agenticops.llm import embeddings, registry
    store = _legacy_vectors()
    embeddings.set_model(REF, ADMIN)
    kb.fake.require_key = "sk-not-ours"                                 # every call is refused now
    with pytest.raises(registry.ProviderError) as e:
        embeddings.reembed(ADMIN)
    assert e.value.code == "embedding_failed"
    assert store.count() == 2 and embeddings.status()["needs_reembed"] is True      # nothing was replaced
    assert isinstance(get_embedding_client(), NullEmbeddingClient)
    assert any(r.levelname == "WARNING" for r in caplog.records)
    results = hybrid_search(query_text="disk full web host", resource_type="EC2", search_dir=kb.cases, top_k=3)
    assert results and all(r.source == "keyword" for r in results)


def test_one_text_that_cannot_be_embedded_keeps_every_old_vector(kb):
    from agenticops.llm import embeddings, registry
    store = _legacy_vectors()
    embeddings.set_model(REF, ADMIN)
    kb.fake.embed_fail_on = "cpu spike"                                 # one of the two cases' texts
    with pytest.raises(registry.ProviderError) as e:
        embeddings.reembed(ADMIN)
    assert e.value.code == "embedding_failed" and store.count() == 2 and store.stored_dimension() == 4


def test_vectors_from_before_are_titans(kb):
    """An installation whose yaml names a provider's model from the start still holds Titan's vectors from before."""
    from agenticops.llm import embeddings
    _legacy_vectors()
    kb.monkeypatch.setattr(kb.settings, "embedding_model_ref", REF)
    st = embeddings.status()
    assert st["model_ref"] == REF and st["indexed_with"] == kb.settings.embedding_model_id and st["needs_reembed"]


def test_bedrock_off_and_no_ref_is_null(kb):
    from agenticops.kb import embeddings as kb_emb
    from agenticops.llm import registry
    registry.set_bedrock_enabled(False, ADMIN)
    with patch("agenticops.config.get_bedrock_boto_session") as session:
        assert isinstance(kb_emb.get_embedding_client(), kb_emb.NullEmbeddingClient)
    assert not session.called                                   # not even a connectivity test on Bedrock
    from agenticops.llm import embeddings
    assert embeddings.status()["source"] == "none"


def test_titan_goes_through_the_bedrock_session(kb):
    import json
    from agenticops.kb import embeddings as kb_emb
    with patch("agenticops.config.get_bedrock_boto_session") as session, \
            patch("boto3.client", side_effect=AssertionError("a bare boto3 client")):
        body = SimpleNamespace(read=lambda: json.dumps({"embedding": [0.5] * 1024}).encode())
        session.return_value.client.return_value.invoke_model.return_value = {"body": body}
        client = kb_emb.get_embedding_client()
        assert isinstance(client, kb_emb.BedrockTitanEmbedding)
    assert session.return_value.client.call_args.args[0] == "bedrock-runtime"


def test_reembed_refuses_other_stores(kb):
    from agenticops.llm import embeddings, registry
    kb.monkeypatch.setattr(kb.settings, "vector_storage", "rds")
    with pytest.raises(registry.ProviderError) as e:
        embeddings.reembed(ADMIN)
    assert e.value.status == 409 and e.value.code == "unsupported_store"


def test_set_model_refuses_what_cannot_embed(kb):
    from agenticops.audit.models import AuditLog
    from agenticops.llm import embeddings, registry
    from agenticops.models import get_db_session
    for ref, code in (("local-llm::fake-chat-1", "unknown_model"),      # a chat model
                      ("relay::embed-x", "unsupported_kind"),            # an Anthropic-compatible server has no vectors
                      ("local-llm::not-listed", "unknown_model"), ("bad::", "unknown_model")):
        with pytest.raises(registry.ProviderError) as e:
            embeddings.set_model(ref, ADMIN)
        assert e.value.code == code, ref
    embeddings.set_model(REF, ADMIN)
    embeddings.set_model("", ADMIN)                                     # back to the default
    with get_db_session() as s:
        rows = [(r.old_values, r.new_values) for r in s.query(AuditLog).filter_by(entity_id="embedding_model_ref")]
    assert rows == [({"embedding_model_ref": ""}, {"embedding_model_ref": REF}),
                    ({"embedding_model_ref": REF}, {"embedding_model_ref": ""})]
    assert registry.references("local-llm") == []


def test_a_provider_in_use_for_vectors_cannot_go(kb):
    from agenticops.llm import embeddings, registry
    embeddings.set_model(REF, ADMIN)
    with pytest.raises(registry.ProviderError) as e:
        registry.delete("local-llm", ADMIN)
    assert e.value.code == "in_use" and e.value.extra == {"refs": ["embedding_model_ref"]}


def test_the_api(kb, monkeypatch):
    import agenticops.audit.models  # noqa: F401
    import agenticops.auth.models  # noqa: F401
    from agenticops.auth.roles import grants
    from agenticops.auth.service import AuthService
    from agenticops.web.app import app
    monkeypatch.setattr(kb.settings, "api_auth_enabled", True)
    client = TestClient(app)

    def tok(email, role, settings_view=False):
        is_admin, perms = grants(role, settings_view)
        user = AuthService.create_user(email=email, password=f"pw-{email}-0", is_admin=is_admin, permissions=perms)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}
    admin, writer, auditor = tok("root", "admin"), tok("ops", "writer"), tok("aud", "viewer", True)
    _legacy_vectors()
    body = client.get("/api/kb/embedding", headers=auditor).json()
    assert body["vectors"] == 2 and [p["value"] for p in body["presets"]] == [REF]   # relay's model cannot embed
    assert client.put("/api/kb/embedding", headers=writer, json={"model_ref": REF}).status_code == 403
    assert client.post("/api/kb/reembed", headers=writer).status_code == 403
    r = client.put("/api/kb/embedding", headers=admin, json={"model_ref": "local-llm::fake-chat-1"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unknown_model"
    r = client.put("/api/kb/embedding", headers=admin, json={"model_ref": REF})
    assert r.status_code == 200 and r.json()["needs_reembed"] is True
    r = client.post("/api/kb/reembed", headers=admin)
    assert r.status_code == 200 and r.json() == {"cases": 2, "vectors": 4, "failed": 0}
    assert client.get("/api/kb/embedding", headers=admin).json()["needs_reembed"] is False
