"""Chat attachments: media in earlier turns is trimmed before every model call, so a session never outgrows
Bedrock's per-request limits (2026-11-07)."""
import copy
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings as hsettings, strategies as st
from strands import Agent
from strands.models.model import Model

from agenticops.agents.preamble import MediaCaps
from agenticops.chat.attachments import delivery
from agenticops.chat.attachments.budget_hook import AttachmentBudgetHook, enforce_history_budget
from agenticops.config import ChatUploadSettings

CFG = ChatUploadSettings()
FULL = MediaCaps(images=True, documents=True)
IMG_PLACEHOLDER = "[an image from an earlier turn was omitted to stay within the model's limits]"


def img(tag: bytes = b"i", size: int = 10) -> dict:
    return {"image": {"format": "png", "source": {"bytes": tag * size}}}


def doc(name: str, size: int = 10) -> dict:
    return {"document": {"format": "pdf", "name": name, "source": {"bytes": b"%PDF" + b"\0" * size}}}


def user(*blocks) -> dict:
    return {"role": "user", "content": list(blocks)}


def assistant(text="ok") -> dict:
    return {"role": "assistant", "content": [{"text": text}]}


def tool_result(*blocks) -> dict:
    return {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "status": "success",
                                                        "content": list(blocks)}}]}


def media(messages) -> tuple[int, int, int]:
    images = docs = size = 0
    for m in messages:
        for b in m["content"]:
            for inner in [b] + list(b.get("toolResult", {}).get("content", [])):
                if "image" in inner:
                    images += 1
                    size += len(inner["image"]["source"]["bytes"])
                if "document" in inner:
                    docs += 1
                    size += len(inner["document"]["source"]["bytes"])
    return images, docs, size


def test_history_documents_become_text():
    delivery.remember_history_text("att-0000aaaa-report-pdf", "Quarterly revenue grew 12 percent.")
    msgs = [user({"text": "read"}, doc("att-0000aaaa-report-pdf")), assistant(), user({"text": "and now?"})]
    changed = enforce_history_budget(msgs, FULL, CFG)
    assert changed == 1
    block = msgs[0]["content"][1]
    assert "document" not in block
    assert "Quarterly revenue grew 12 percent." in block["text"] and block["text"].startswith("<attachment")


def test_registry_miss_placeholder():
    msgs = [user({"text": "read"}, doc("att-ffffffff-gone-pdf")), assistant(), user({"text": "and now?"})]
    enforce_history_budget(msgs, FULL, CFG)
    assert msgs[0]["content"][1] == {
        "text": '[document "att-ffffffff-gone-pdf" from an earlier turn — content no longer available]'}


def test_history_attachment_text_is_cut():
    cfg = ChatUploadSettings(history_text_max_chars=100)
    body = '<attachment n="1" name="a.txt" type="txt">\n' + "x" * 500 + "\n</attachment>"
    msgs = [user({"text": body + "\n\nsummarize"}), assistant(), user({"text": "next"})]
    enforce_history_budget(msgs, FULL, cfg)
    text = msgs[0]["content"][0]["text"]
    assert "x" * 100 + "\n[… truncated]\n</attachment>" in text and "x" * 101 not in text
    assert text.endswith("summarize")
    again = copy.deepcopy(msgs)
    assert enforce_history_budget(again, FULL, cfg) == 0 and again == msgs   # idempotent


def test_history_images_capped_newest_kept():
    msgs = []
    for i in range(8):
        msgs += [user({"text": f"pic {i}"}, img(bytes([65 + i]))), assistant()]
    msgs.append(user({"text": "now"}))
    enforce_history_budget(msgs, FULL, CFG)
    kept = [i for i in range(8) if "image" in msgs[2 * i]["content"][1]]
    assert kept == [2, 3, 4, 5, 6, 7]
    assert msgs[0]["content"][1] == {"text": IMG_PLACEHOLDER}


def test_current_turn_untouched_on_claude():
    current = user({"text": "look"}, *[img(bytes([i])) for i in range(1, 5)], doc("att-11111111-a-pdf"))
    msgs = [user({"text": "old"}, img()), assistant(), current]
    before = copy.deepcopy(current)
    enforce_history_budget(msgs, FULL, CFG)
    assert msgs[-1] == before


def test_request_total_images_counts_current_turn_first():
    msgs = [user({"text": "old"}, img(b"o")), user({"text": "old2"}, img(b"p")), assistant(),
            user({"text": "many"}, *[img(bytes([i])) for i in range(1, 20)])]   # 19 current
    enforce_history_budget(msgs, FULL, CFG)
    assert media(msgs)[0] == 20
    assert "image" not in msgs[0]["content"][1] and "image" in msgs[1]["content"][1]


def test_tool_result_images_counted():
    msgs = [user({"text": "q"}, *[img(bytes([i])) for i in range(1, 6)]), assistant(),
            tool_result(*[img(bytes([100 + i])) for i in range(16)])]
    # the user message with no toolResult is the current turn; the 16 tool images come after it
    enforce_history_budget(msgs, FULL, CFG)
    assert media(msgs)[0] == 20
    assert media([msgs[0]])[0] == 5   # the user's own images stay


def test_text_only_model_strips_all_media_from_history():
    delivery.remember_history_text("att-22222222-spec-pdf", "spec text")
    msgs = [user({"text": "a"}, img(), doc("att-22222222-spec-pdf")), assistant(),
            user({"text": "b"}, img(b"z"))]
    enforce_history_budget(msgs, MediaCaps(images=False, documents=False), CFG)
    assert media(msgs) == (0, 0, 0)
    assert all(m["content"] for m in msgs)
    assert "spec text" in msgs[0]["content"][2]["text"]


def test_images_only_model_converts_current_documents():
    msgs = [user({"text": "b"}, doc("att-33333333-x-pdf"), img())]
    enforce_history_budget(msgs, MediaCaps(images=True, documents=False), CFG)
    assert media(msgs)[:2] == (1, 0)


def test_media_byte_budget():
    cfg = ChatUploadSettings(native_media_max_mb=1)
    msgs = [user({"text": "a"}, img(b"a", 700_000)), assistant(), user({"text": "b"}, img(b"b", 700_000))]
    enforce_history_budget(msgs, FULL, cfg)
    assert media(msgs)[0] == 1 and "image" in msgs[2]["content"][1]


def test_documents_at_most_five_oldest_converted():
    msgs = [user({"text": "q"}, *[doc(f"att-4444444{i}-d-pdf") for i in range(3)]), assistant(),
            tool_result(*[doc(f"att-5555555{i}-t-pdf") for i in range(4)])]
    enforce_history_budget(msgs, FULL, CFG)
    assert media(msgs)[1] == 5
    assert media([msgs[0]])[1] == 3


_block = st.one_of(
    st.just({"text": "t"}),
    st.builds(lambda n: img(b"x", n), st.integers(1, 400_000)),
    st.builds(lambda i, n: doc(f"att-{i:08x}-p-pdf", n), st.integers(0, 50), st.integers(1, 400_000)),
)
_message = st.one_of(
    st.builds(lambda bs: user({"text": "u"}, *bs), st.lists(_block, max_size=8)),
    st.builds(lambda bs: tool_result({"text": "r"}, *bs), st.lists(_block, max_size=8)),
    st.just(assistant()),
)


@hsettings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_message, max_size=30), st.sampled_from([FULL, MediaCaps(True, False), MediaCaps(False, False)]))
def test_request_never_over_bedrock_limits(messages, caps):
    cfg = ChatUploadSettings(native_media_max_mb=4)
    enforce_history_budget(messages, caps, cfg)
    images, docs, size = media(messages)
    assert images <= 20 and docs <= 5 and size <= 4 * 1024 * 1024
    if not caps.images:
        assert images == 0
    if not caps.documents:
        assert docs == 0
    assert all(m["content"] for m in messages)


class RecordingModel(Model):
    def __init__(self, model_id: str):
        self.config = {"model_id": model_id}
        self.seen: list[list] = []

    def update_config(self, **kw):
        self.config.update(kw)

    def get_config(self):
        return self.config

    async def structured_output(self, *a, **k):  # pragma: no cover
        raise NotImplementedError
        yield

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.seen.append(copy.deepcopy(messages))
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": "ok"}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}


def test_hook_runs_before_model_sees_messages(monkeypatch):
    from agenticops.chat import upload_config
    monkeypatch.setattr(upload_config, "effective", lambda: CFG)
    history = []
    for i in range(8):
        history += [user({"text": f"pic {i}"}, img(bytes([65 + i]))), assistant()]
    model = RecordingModel("global.anthropic.claude-opus-5-5")
    agent = Agent(model=model, messages=history, hooks=[AttachmentBudgetHook()], callback_handler=None)
    agent("what changed?")
    assert media(model.seen[0])[0] == 6


def test_hook_follows_the_agents_model(monkeypatch):
    from agenticops.chat import upload_config
    monkeypatch.setattr(upload_config, "effective", lambda: CFG)
    model = RecordingModel("openai.gpt-oss-120b-1:0")
    agent = Agent(model=model, messages=[user({"text": "a"}, img()), assistant()], hooks=[AttachmentBudgetHook()],
                  callback_handler=None)
    agent("next")
    assert media(model.seen[0])[0] == 0


def _hook_kwargs(read_only: bool) -> list:
    from agenticops.agents.main_agent import create_main_agent
    with patch("agenticops.agents.main_agent.Agent") as MockAgent, \
         patch("agenticops.agents.main_agent.BedrockModel"), \
         patch("agenticops.agents.main_agent.build_system_prompt", side_effect=lambda p, **kw: p), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=MagicMock()), \
         patch("agenticops.agents.main_agent._safe_mcp_clients", return_value=[]), \
         patch("agenticops.memory.curator.maybe_run_curator"), \
         patch("agenticops.skills.curator.maybe_run_skills_curator"):
        MockAgent.return_value = MagicMock()
        create_main_agent(read_only=read_only)
    return MockAgent.call_args.kwargs.get("hooks") or []


def test_main_agent_registers_hook():
    for read_only in (False, True):
        assert any(isinstance(h, AttachmentBudgetHook) for h in _hook_kwargs(read_only)), read_only
