"""Chat message preprocessor — shared between CLI and Web.

Handles:
- I#N reference resolution (HealthIssue by ID)
- R#N reference resolution (AWSResource by ID)
- @file/path extraction and content injection (CLI)
- Pre-read file content injection (Web upload)
"""

import re
import json
import logging
from typing import Optional

from agenticops.chat.file_reader import (
    read_file_as_text,
    is_image_file,
    is_document_file,
    read_file_as_image_bytes,
    read_file_as_document_bytes,
)

logger = logging.getLogger(__name__)

# Patterns
ISSUE_REF_PATTERN = re.compile(r"\bI#(\d+)\b")
RESOURCE_REF_PATTERN = re.compile(r"\bR#(\d+)\b")
FILE_REF_PATTERN = re.compile(r"@((?:/|\.\.?/)[^\s]+)")


def _resolve_issue_ref(issue_id: int) -> str | None:
    """Fetch HealthIssue by ID and return context block."""
    from agenticops.models import HealthIssue, get_db_session

    with get_db_session() as session:
        issue = session.query(HealthIssue).filter_by(id=issue_id).first()
        if not issue:
            return None
        return (
            f'<referenced_issue id="{issue.id}">\n'
            f"Title: {issue.title}\n"
            f"Severity: {issue.severity}\n"
            f"Status: {issue.status}\n"
            f"Resource: {issue.resource_id}\n"
            f"Source: {issue.source}\n"
            f"Description: {issue.description}\n"
            f"Detected at: {issue.detected_at}\n"
            f"</referenced_issue>"
        )


def _resolve_resource_ref(resource_id: int) -> str | None:
    """Fetch AWSResource by int PK and return context block."""
    from agenticops.models import AWSResource, get_db_session

    with get_db_session() as session:
        resource = session.query(AWSResource).filter_by(id=resource_id).first()
        if not resource:
            return None
        return (
            f'<referenced_resource id="{resource.id}">\n'
            f"AWS ID: {resource.resource_id}\n"
            f"ARN: {resource.resource_arn or 'N/A'}\n"
            f"Type: {resource.resource_type}\n"
            f"Name: {resource.resource_name or 'unnamed'}\n"
            f"Region: {resource.region}\n"
            f"Status: {resource.status}\n"
            f"</referenced_resource>"
        )


def resolve_references(text: str) -> tuple[str, list[str]]:
    """Find I#N and R#N references, resolve them, return (enriched_text, warnings).

    The original text is preserved. Resolved context blocks are appended at the end.
    """
    context_blocks: list[str] = []
    warnings: list[str] = []

    for match in ISSUE_REF_PATTERN.finditer(text):
        issue_id = int(match.group(1))
        block = _resolve_issue_ref(issue_id)
        if block:
            context_blocks.append(block)
        else:
            warnings.append(f"HealthIssue I#{issue_id} not found")

    for match in RESOURCE_REF_PATTERN.finditer(text):
        resource_id = int(match.group(1))
        block = _resolve_resource_ref(resource_id)
        if block:
            context_blocks.append(block)
        else:
            warnings.append(f"Resource R#{resource_id} not found")

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
) -> tuple[str | list[dict], list[str]]:
    """Full preprocessing pipeline: file injection + reference resolution.

    Args:
        text: Raw user message.
        file_contents: Optional list of (filename, content) tuples — text extracts (web uploads).
        file_images: Optional list of (filename, bytes, format) tuples — native image blocks.
        file_documents: Optional list of (filename, bytes, format, name) tuples — native document blocks.
        resolve_file_refs: If True, extract @file/path from text and read them (CLI).

    Returns:
        (enriched_message_or_content_blocks, warnings).
        Returns str for text-only messages, list[ContentBlock] when images/documents are present.
    """
    text_parts: list[str] = []
    warnings: list[str] = []
    image_blocks: list[dict] = []
    document_blocks: list[dict] = []

    # Collect pre-supplied media blocks (from web uploads)
    if file_images:
        for filename, raw, fmt in file_images:
            image_blocks.append({"image": {"format": fmt, "source": {"bytes": raw}}})
    if file_documents:
        for filename, raw, fmt, name in file_documents:
            document_blocks.append({"document": {"format": fmt, "name": name, "source": {"bytes": raw}}})

    # 1. Extract @file references from text (CLI mode)
    if resolve_file_refs:
        cleaned_text, file_paths = _extract_file_refs(text)
        for fpath in file_paths:
            if is_image_file(fpath):
                raw, fmt, error = read_file_as_image_bytes(fpath)
                if error:
                    warnings.append(error)
                elif raw and fmt:
                    image_blocks.append({"image": {"format": fmt, "source": {"bytes": raw}}})
            elif is_document_file(fpath):
                raw, fmt, name, error = read_file_as_document_bytes(fpath)
                if error:
                    warnings.append(error)
                elif raw and fmt and name:
                    document_blocks.append({"document": {"format": fmt, "name": name, "source": {"bytes": raw}}})
            else:
                content, error = read_file_as_text(fpath)
                if error:
                    warnings.append(error)
                elif content:
                    text_parts.append(f'<attached_file path="{fpath}">\n{content}\n</attached_file>')
        text = cleaned_text if cleaned_text else text

    # 2. Prepend any pre-read text file contents (web upload mode)
    if file_contents:
        for filename, content in file_contents:
            text_parts.append(f'<attached_file path="{filename}">\n{content}\n</attached_file>')

    # 3. Append the user message
    text_parts.append(text)
    combined = "\n\n".join(text_parts)

    # 4. Resolve I#/R# references
    enriched_text, ref_warnings = resolve_references(combined)
    warnings.extend(ref_warnings)

    # 5. If no media blocks, return plain string (100% backward compatible)
    if not image_blocks and not document_blocks:
        return enriched_text, warnings

    # 6. Build list[ContentBlock] with text + media
    content_blocks: list[dict] = [{"text": enriched_text}]
    content_blocks.extend(image_blocks)
    content_blocks.extend(document_blocks)
    return content_blocks, warnings
