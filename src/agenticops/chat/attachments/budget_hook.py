"""Keep a conversation's media inside one Bedrock request, every model call (2026-11-07).

Attachments stay in the agent's history and Strands resends the whole history on every call, so without this a
session that collected six PDFs and twenty screenshots would be refused forever (5 documents / 20 images per
request), and a session switched to a text-only model would fail on its first image. `AttachmentBudgetHook` runs on
`BeforeModelCallEvent` — before Strands copies `agent.messages` into the request — and rewrites `agent.messages` in
place, so the Web chat, the CLI REPL and media inside tool results are all covered by one rule:

- the current turn = the last user message that is not a tool result; everything before it is history;
- a history document becomes its extracted text (delivery.history_text); one without text (a .doc / .xls, a scanned
  PDF, one this process no longer remembers) stays native within the document budget, else becomes a placeholder;
- `<attachment>` text in history is cut to `history_text_max_chars` per file and `turn_text_max_chars` in all
  (newest first; an older body becomes a one-line placeholder);
- images: the current turn's first, then the newest; history images ≤ `history_images_max`; every image in the
  request ≤ 20; native bytes ≤ `native_media_max_mb`; documents in the request ≤ 5 (oldest become text first);
- a model that cannot read images / documents gets none, current turn included.
A block is replaced by a text block, never removed, so no message is ever left empty.
"""
import logging
import re
from typing import Iterator

from strands.hooks import BeforeModelCallEvent, HookProvider, HookRegistry

from agenticops.chat.attachments.limits import BEDROCK_MAX_DOCUMENTS, BEDROCK_MAX_IMAGES

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER = "[an image from an earlier turn was omitted to stay within the model's limits]"
IMAGE_UNSUPPORTED = "[an image was omitted: this model cannot see images]"
TEXT_OMITTED = "[attachment text from an earlier turn omitted to stay within the model's limits]"
_TRUNC = "\n[… truncated]"
_ATTACHMENT = re.compile(r"(<attachment\b[^>]*>\n)(.*?)(\n</attachment>)", re.DOTALL)
_CLOSING = re.compile(r"</(attachment)", re.IGNORECASE)
_MIB = 1024 * 1024


class _Ref:
    """One media block: where it sits and how much it weighs."""
    __slots__ = ("container", "index", "msg", "kind", "size", "current")

    def __init__(self, container: list, index: int, msg: int, kind: str, size: int, current: bool):
        self.container, self.index, self.msg, self.kind, self.size, self.current = (
            container, index, msg, kind, size, current)

    @property
    def block(self) -> dict:
        return self.container[self.index]

    def replace(self, text: str) -> None:
        self.container[self.index] = {"text": text}


def _is_tool_result(message: dict) -> bool:
    return any("toolResult" in b for b in message.get("content") or [])


def _current_index(messages: list[dict]) -> int:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user" and not _is_tool_result(messages[i]):
            return i
    return -1


def _size(block: dict, kind: str) -> int:
    source = (block.get(kind) or {}).get("source") or {}
    data = source.get("bytes")
    return len(data) if isinstance(data, (bytes, bytearray)) else 0


def _media(messages: list[dict], current: int) -> Iterator[_Ref]:
    for m, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content") or []
        for i, block in enumerate(content):
            containers = [(content, i)]
            if "toolResult" in block:
                inner = block["toolResult"].get("content") or []
                containers = [(inner, j) for j in range(len(inner))]
            for container, j in containers:
                b = container[j]
                for kind in ("image", "document"):
                    if kind in b:
                        yield _Ref(container, j, m, kind, _size(b, kind), m == current and container is content)


def _document_text(block: dict, cfg) -> str:
    from agenticops.chat.attachments.delivery import history_text
    name = (block.get("document") or {}).get("name") or "document"
    text = history_text(name)
    if text is None:
        return f'[document "{name}" from an earlier turn — content no longer available]'
    cap = cfg.history_text_max_chars
    if len(text) > cap:
        text = text[:cap] + _TRUNC
    safe = _CLOSING.sub(r"<\\/\1", text)
    return f'<attachment name="{name}" type="document">\n{safe}\n</attachment>'


def _cut_attachment_text(text: str, cap: int, left: list[int]) -> str:
    """Cut each body to `cap`; then spend `left[0]` (the history-wide allowance, walked newest first by the caller,
    bodies here newest last) — a body that no longer fits becomes TEXT_OMITTED."""
    matches = list(_ATTACHMENT.finditer(text))
    out, pos = [], 0
    for m in reversed(matches):
        body = m.group(2)
        if body != TEXT_OMITTED:
            if len(body) > cap and not (body.endswith(_TRUNC) and len(body) == cap + len(_TRUNC)):
                body = body[:cap] + _TRUNC
            if len(body) > left[0]:
                body = TEXT_OMITTED
            else:
                left[0] -= len(body)
        out.append((m, body))
    pieces = []
    for m, body in reversed(out):
        pieces.append(text[pos:m.start()])
        pieces.append(m.group(1) + body + m.group(3))
        pos = m.end()
    pieces.append(text[pos:])
    return "".join(pieces)


def enforce_history_budget(messages: list[dict], caps, cfg) -> int:
    """Rewrite `messages` in place to fit one request (see the module docstring); → blocks changed."""
    changed = 0
    current = _current_index(messages)

    refs = list(_media(messages, current))
    # what the model cannot read at all; history documents become their text when this process still has it — one
    # without text stays native, within the budget below
    from agenticops.chat.attachments.delivery import history_text
    keep: list[_Ref] = []
    for ref in refs:
        if ref.kind == "image" and not caps.images:
            ref.replace(IMAGE_UNSUPPORTED if ref.current else IMAGE_PLACEHOLDER)
            changed += 1
        elif ref.kind == "document" and (not caps.documents or (
                ref.msg < current and history_text((ref.block.get("document") or {}).get("name") or "") is not None)):
            ref.replace(_document_text(ref.block, cfg))
            changed += 1
        else:
            keep.append(ref)

    # the request budget: the current turn's own media first, then the newest
    ordered = [r for r in keep if r.current] + sorted((r for r in keep if not r.current),
                                                      key=lambda r: r.msg, reverse=True)
    images = docs = history_images = 0
    left = cfg.native_media_max_mb * _MIB
    for ref in ordered:
        if ref.kind == "image":
            history = ref.msg < current
            fits = (images < BEDROCK_MAX_IMAGES and ref.size <= left
                    and (not history or history_images < cfg.history_images_max))
            if fits:
                images += 1
                history_images += history
                left -= ref.size
                continue
            ref.replace(IMAGE_PLACEHOLDER)
        else:
            if docs < BEDROCK_MAX_DOCUMENTS and ref.size <= left:
                docs += 1
                left -= ref.size
                continue
            ref.replace(_document_text(ref.block, cfg))
        changed += 1

    # history text: each <attachment> body ≤ history_text_max_chars, all of them ≤ turn_text_max_chars, newest first
    allowance = [cfg.turn_text_max_chars]
    for m in range(max(current, 0) - 1, -1, -1):
        if messages[m].get("role") != "user":
            continue
        for block in reversed(messages[m].get("content") or []):
            if isinstance(block.get("text"), str) and "<attachment" in block["text"]:
                cut = _cut_attachment_text(block["text"], cfg.history_text_max_chars, allowance)
                if cut != block["text"]:
                    block["text"] = cut
                    changed += 1
    return changed


class AttachmentBudgetHook(HookProvider):
    """Registers `enforce_history_budget` on every model call of the agent it is given to."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model_call)

    def _before_model_call(self, event: BeforeModelCallEvent) -> None:
        from agenticops.agents.preamble import media_capabilities
        from agenticops.chat import upload_config
        try:
            model_id = (getattr(event.agent.model, "config", None) or {}).get("model_id", "")
            changed = enforce_history_budget(event.agent.messages, media_capabilities(model_id),
                                             upload_config.effective())
            if changed:
                logger.info("attachment budget: %d media/text blocks trimmed before the model call", changed)
        except Exception:  # never fail a turn here; Bedrock would then refuse an oversized request on its own
            logger.exception("attachment budget hook failed")
