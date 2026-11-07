"""Chat message preprocessor — shared between CLI and Web.

Handles:
- I#N reference resolution (HealthIssue by ID)
- R#N reference resolution (CloudResource by ID)
- C#N reference resolution (ChangeRequest by ID; only when change_management_enabled)
- @file/path attachments (CLI): processed like a Web upload (chat/attachments) and delivered for the CLI's model
- Web attachments: a prepared `attachment_turn` (chat/attachments/delivery.build_turn)

References resolve only from the text the user typed, never from an attached file's content.
"""

import re
import json
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agenticops.chat.attachments.delivery import Turn

logger = logging.getLogger(__name__)

# Patterns
ISSUE_REF_PATTERN = re.compile(r"\bI#(\d+)\b")
RESOURCE_REF_PATTERN = re.compile(r"\bR#(\d+)\b")
CHANGE_REF_PATTERN = re.compile(r"\bC#(\d+)\b")
FILE_REF_PATTERN = re.compile(r"@((?:/|\.\.?/)[^\s]+)")


def _outside(d: dict, bound_account_id: int | None) -> bool:
    """MVP-2.7.0 S5: a record of another account than the chat's bound one is withheld (unbound chats see all)."""
    return bound_account_id is not None and d.get("account_id") is not None and d["account_id"] != bound_account_id


def _withheld(tag: str, ref: str, pk: int) -> str:
    return f'<{tag} id="{pk}">{ref} is not in this chat\'s account; it was not loaded.</{tag}>'


def _resolve_issue_ref(issue_id: int, bound_account_id: int | None = None) -> str | None:
    """Fetch HealthIssue by ID and return context block."""
    from agenticops.chat.reference_resolver import fetch_issue
    d = fetch_issue(issue_id)
    if not d:
        return None
    if _outside(d, bound_account_id):
        return _withheld("referenced_issue", f"I#{issue_id}", issue_id)
    return (
        f'<referenced_issue id="{d["id"]}">\n'
        f"Title: {d['title']}\n"
        f"Severity: {d['severity']}\n"
        f"Status: {d['status']}\n"
        f"Resource: {d['resource_id']}\n"
        f"Source: {d['source']}\n"
        f"Description: {d['description']}\n"
        f"Detected at: {d['detected_at']}\n"
        f"</referenced_issue>"
    )


def _resolve_resource_ref(resource_id: int, bound_account_id: int | None = None) -> str | None:
    """Fetch CloudResource by int PK and return context block."""
    from agenticops.chat.reference_resolver import fetch_resource
    d = fetch_resource(resource_id)
    if not d:
        return None
    if _outside(d, bound_account_id):
        return _withheld("referenced_resource", f"R#{resource_id}", resource_id)
    return (
        f'<referenced_resource id="{d["id"]}">\n'
        f"Resource ID: {d['resource_id']}\n"
        f"Provider: {d['provider']}\n"
        f"Type: {d['resource_type']}\n"
        f"Name: {d['name'] or 'unnamed'}\n"
        f"Region: {d['region']}\n"
        f"Status: {d['status']}\n"
        f"</referenced_resource>"
    )


def _resolve_change_ref(cr_id: int, bound_account_id: int | None = None) -> str | None:
    from agenticops.chat.reference_resolver import fetch_change
    d = fetch_change(cr_id)
    if not d:
        return None
    if _outside(d, bound_account_id):
        return _withheld("referenced_change", f"C#{cr_id}", cr_id)
    return (
        f'<referenced_change id="{d["id"]}">\n'
        f"Title: {d['title']}\nStatus: {d['status']}\nRisk: {d['risk_level'] or 'unassessed'}\n"
        f"Type: {d['requested_change_type']}\nRequested by: {d['requested_by']}\n"
        f"Targets: {', '.join(t for t in d['targets'] if t) or 'none grounded yet'}\n"
        f"Description: {d['description']}\n</referenced_change>"
    )


def resolve_references(text: str, *, change_ref_text: str | None = None,
                       bound_account_id: int | None = None) -> tuple[str, list[str]]:
    """Find I#N, R#N and C#N references, resolve them, return (enriched_text, warnings).

    The original text is preserved. Resolved context blocks are appended at the end.
    C#N references are read from `change_ref_text` when given (the user's typed text), else from `text`.
    """
    context_blocks: list[str] = []
    warnings: list[str] = []

    for match in ISSUE_REF_PATTERN.finditer(text):
        issue_id = int(match.group(1))
        block = _resolve_issue_ref(issue_id, bound_account_id)
        if block:
            context_blocks.append(block)
        else:
            warnings.append(f"HealthIssue I#{issue_id} not found")

    for match in RESOURCE_REF_PATTERN.finditer(text):
        resource_id = int(match.group(1))
        block = _resolve_resource_ref(resource_id, bound_account_id)
        if block:
            context_blocks.append(block)
        else:
            warnings.append(f"Resource R#{resource_id} not found")

    from agenticops.config import settings
    if settings.change_management_enabled:
        change_refs = CHANGE_REF_PATTERN.findall(text if change_ref_text is None else change_ref_text)
        for cr_id in dict.fromkeys(int(m) for m in change_refs):
            block = _resolve_change_ref(cr_id, bound_account_id)
            if block:
                context_blocks.append(block)
            else:
                warnings.append(f"ChangeRequest C#{cr_id} not found")

    if context_blocks:
        enriched = text + "\n\n" + "\n\n".join(context_blocks)
    else:
        enriched = text

    return enriched, warnings


def _extract_file_refs(text: str) -> tuple[str, list[str]]:
    """Extract @/path/to/file references from text.

    Returns (text_with_refs_removed, list_of_file_paths).
    """
    paths: list[str] = []

    def replacer(m: re.Match) -> str:
        paths.append(m.group(1))
        return ""

    cleaned = FILE_REF_PATTERN.sub(replacer, text).strip()
    return cleaned, paths


def preprocess_message(
    text: str,
    file_contents: Optional[list[tuple[str, str]]] = None,
    file_images: Optional[list[tuple[str, bytes, str]]] = None,
    file_documents: Optional[list[tuple[str, bytes, str, str]]] = None,
    resolve_file_refs: bool = False,
    bound_account_id: int | None = None,
    *,
    attachment_turn: "Turn | None" = None,
    model_id: str = "",
) -> tuple[str | list[dict], list[str]]:
    """Full preprocessing pipeline: attachments + reference resolution.

    Args:
        text: Raw user message.
        file_contents / file_images / file_documents: the pre-2026-11-07 Web upload shapes (removed with the old
            multipart reader).
        resolve_file_refs: If True, extract @file/path from text and attach those files (CLI).
        bound_account_id: refs outside this account are withheld (S5).
        attachment_turn: the Web attachments, already delivered for the answering model.
        model_id: the model that will answer (CLI @path delivery); empty = Main's configured model.

    Returns:
        (enriched_message_or_content_blocks, warnings).
        Returns str for text-only messages, list[ContentBlock] when images/documents are present.
    """
    text_parts: list[str] = []
    warnings: list[str] = []
    media_blocks: list[dict] = []

    if attachment_turn is not None and attachment_turn.text:
        text_parts.append(attachment_turn.text)
        media_blocks.extend(attachment_turn.blocks)

    for filename, raw, fmt in file_images or []:
        media_blocks.append({"image": {"format": fmt, "source": {"bytes": raw}}})
    for filename, raw, fmt, name in file_documents or []:
        media_blocks.append({"document": {"format": fmt, "name": name, "source": {"bytes": raw}}})

    # 1. @file references (CLI): processed and delivered exactly like a Web upload
    if resolve_file_refs:
        cleaned_text, file_paths = _extract_file_refs(text)
        if file_paths:
            cli_turn, cli_warnings = _attach_local_files(file_paths, model_id)
            warnings.extend(cli_warnings)
            if cli_turn.text:
                text_parts.append(cli_turn.text)
            media_blocks.extend(cli_turn.blocks)
        text = cleaned_text if cleaned_text else text

    # 2. Pre-read text file contents (the old web upload shape)
    for filename, content in file_contents or []:
        text_parts.append(f'<attached_file path="{filename}">\n{content}\n</attached_file>')

    # 3. Resolve I#/R#/C# references in what the user typed — never in an attached file
    enriched_text, ref_warnings = resolve_references(text, change_ref_text=text, bound_account_id=bound_account_id)
    warnings.extend(ref_warnings)
    combined = "\n\n".join([*text_parts, enriched_text])

    if not media_blocks:
        return combined, warnings
    return [{"text": combined}, *media_blocks], warnings


def _attach_local_files(paths: list[str], model_id: str) -> tuple["Turn", list[str]]:
    """CLI `@path` files → one delivered Turn (the worker runs in a temp dir that is gone afterwards)."""
    import tempfile
    from pathlib import Path

    from agenticops.chat import upload_config
    from agenticops.chat.attachments.delivery import build_turn, prepare_local, reason_text
    if not model_id:
        from agenticops.config import get_agent_model_config
        model_id = get_agent_model_config("main")[0]
    cfg = upload_config.effective()
    with tempfile.TemporaryDirectory(prefix="aiops-cli-att-") as workdir:
        items = [prepare_local(Path(p), cfg, Path(workdir)) for p in paths]
        warnings = [f"{p}: {reason_text(it.reason)}" for p, it in zip(paths, items) if it.status != "ready"]
        turn = build_turn(items, model_id, cfg)
    for d in turn.deliveries:
        if d["delivery"] == "notice":
            warnings.append(f"{d['filename']}: not given to the model — {reason_text(d['reason'])}")
    return turn, warnings
