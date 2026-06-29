from unittest.mock import patch, MagicMock
from agenticops.services import agent_log_service as svc


def test_log_agent_call_snapshots_cost_and_actor():
    captured = {}
    class FakeDB:
        def add(self, obj): captured["obj"] = obj
    from contextlib import contextmanager
    @contextmanager
    def fake_session():
        yield FakeDB()
    with patch("agenticops.models.get_db_session", fake_session):
        svc.log_agent_call(
            agent_name="rca", action="rca", input_summary="x",
            input_tokens=1_000_000, output_tokens=0,
            model_id="global.anthropic.claude-sonnet-4-6",
            actor_type="user", actor_id="malibo",
        )
    obj = captured["obj"]
    assert obj.cost_usd == 3.0          # 1M input @ $3/1M sonnet
    assert obj.actor_type == "user"
    assert obj.actor_id == "malibo"
    assert obj.cache_write_tokens == 0
