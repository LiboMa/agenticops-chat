"""Conversation summary service using Haiku model for lightweight summarization."""

import json
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from agenticops.config import settings
from agenticops.models import SessionSummary, get_db_session

logger = logging.getLogger(__name__)


class SummaryService:
    """Generates and retrieves conversation summaries using a lightweight LLM (Haiku)."""

    SUMMARY_MAX_TOKENS = 500

    SUMMARY_PROMPT_TEMPLATE = (
        "You are a concise conversation summarizer. "
        "Summarize the following conversation in a compact paragraph. "
        "Focus on key topics discussed, decisions made, and action items. "
        "Keep the summary under 500 tokens.\n\n"
        "Conversation:\n{conversation}\n\n"
        "Summary:"
    )

    def __init__(self, region: str | None = None, model_id: str | None = None):
        self.region = region or settings.bedrock_region
        self.model_id = model_id or settings.bedrock_model_id_cheap
        self._client = None

    @property
    def client(self):
        """Lazy-init Bedrock runtime client."""
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
        return self._client

    def _format_messages(self, messages: list[dict]) -> str:
        """Format Strands-format messages into a readable conversation string."""
        lines: list[str] = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Strands format: content is a list of blocks
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        if "text" in block:
                            text_parts.append(block["text"])
                        elif "toolUse" in block:
                            tool = block["toolUse"]
                            text_parts.append(f"[Tool: {tool.get('name', '?')}]")
                        elif "toolResult" in block:
                            text_parts.append("[Tool Result]")
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = " ".join(text_parts)
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def generate_summary(
        self, messages: list[dict], session_id: int
    ) -> str | None:
        """Generate a summary for the given messages and store it in the DB.

        Args:
            messages: List of Strands-format message dicts to summarize.
            session_id: The ChatSession.id (DB primary key).

        Returns:
            The summary text, or None if generation failed.
        """
        if not messages:
            return None

        try:
            conversation_text = self._format_messages(messages)
            prompt = self.SUMMARY_PROMPT_TEMPLATE.format(conversation=conversation_text)

            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.SUMMARY_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            })

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            summary_text = response_body["content"][0]["text"]

            # Determine message range from the input messages
            # Use first and last message positions as range markers
            msg_ids = [m.get("_db_id", 0) for m in messages]
            range_start = min(msg_ids) if msg_ids else 0
            range_end = max(msg_ids) if msg_ids else 0

            # Persist to DB
            with get_db_session() as db:
                summary = SessionSummary(
                    session_id=session_id,
                    summary_text=summary_text,
                    message_range_start=range_start,
                    message_range_end=range_end,
                )
                db.add(summary)

            return summary_text

        except (ClientError, KeyError, IndexError, Exception) as exc:
            logger.error("Failed to generate summary for session %s: %s", session_id, exc)
            return None

    def get_summaries(self, session_id: int) -> list[SessionSummary]:
        """Retrieve all summaries for a session, ordered by creation time ascending.

        Args:
            session_id: The ChatSession.id (DB primary key).

        Returns:
            List of SessionSummary objects ordered by created_at ASC.
        """
        with get_db_session() as db:
            summaries = (
                db.query(SessionSummary)
                .filter(SessionSummary.session_id == session_id)
                .order_by(SessionSummary.created_at.asc())
                .all()
            )
            # Detach from session so they can be used after the DB session closes
            db.expunge_all()
            return summaries
