"""Shared agent prompt preamble blocks, system prompt builder, and agent call utilities.

Provides composable prompt fragments that are shared across multiple agents,
eliminating duplication of account instructions, skill protocols, and output
format rules. Centralises the output-rules and skill-usage-protocol that
were previously in skills/loader.py.
"""

from __future__ import annotations

import logging
import time

from agenticops.config import get_detail_level, settings

# ── Account Preamble ─────────────────────────────────────────────────

ACCOUNT_PREAMBLE = (
    "Call get_active_account and assume_role before any AWS operation. "
    "If no account is configured, inform the user."
)

# ── Skills Usage Protocol ────────────────────────────────────────────

SKILLS_USAGE_PROTOCOL = """
AGENT SKILLS PROTOCOL:
- You have access to domain knowledge skills. Use list_skills to see them, or check <available_skills> above.
- When you need deep domain knowledge for troubleshooting, call activate_skill(skill_name) to load the skill's
  decision trees, command references, and diagnostic procedures.
- For detailed reference material, call read_skill_reference(skill_name, reference_path).
- Skills are READ-ONLY knowledge — they guide your tool usage but don't replace your tools.
- Activate skills BEFORE starting investigation when the domain is clear (e.g., activate 'linux-admin'
  before running host diagnostics, activate 'kubernetes-admin' before debugging pods).
"""

# ── Output Format Rule Templates ────────────────────────────────────

OUTPUT_RULES: dict[str, str] = {
    "concise": """\
OUTPUT FORMAT RULES (concise mode — target ~500 tokens):
- Lead with root cause / answer in 1-2 sentences.
- Bullet points only — no tables, no headings, no paragraphs.
- Do NOT echo back skill content, tool results, or protocol steps.
- Do NOT repeat the user's question.
- Cite resource IDs inline (e.g., "i-0abc123 is running").
- Omit recommendations and fix plans unless explicitly requested.""",

    "medium": """\
OUTPUT FORMAT RULES (medium mode — target ~1500 tokens):
- Keep responses CONCISE. Aim for 500-1500 tokens of output text.
- Use bullet points and short sentences — not paragraphs.
- Lead with a 2-3 sentence summary, then key findings as bullets.
- Include brief recommendations section when relevant.
- Do NOT echo back full skill content or tool results verbatim. Summarize key findings.
- Do NOT repeat the user's question or restate the protocol steps.
- When citing resource IDs, use inline format (e.g., "i-0abc123 is running") not tables.""",

    "detailed": """\
OUTPUT FORMAT RULES (detailed mode — target ~4000 tokens):
- Provide a thorough narrative with full evidence chain.
- Use headings (##) to organize: Summary → Evidence → Analysis → Recommendations.
- Include resource details with IDs, states, and relevant attributes.
- Tables are allowed for comparing resources or metrics.
- Include complete recommendations with specific CLI commands.
- Still do NOT echo raw tool output or repeat the protocol — synthesize and explain.""",
}

RCA_ADDENDA: dict[str, str] = {
    "concise": """\
- Structure: Root Cause (1 sentence) → top 3 evidence bullets → confidence score.""",
    "medium": """\
- Structure: Root Cause → Evidence → Contributing Factors → Recommendations → Fix Plan (if applicable).""",
    "detailed": """\
- Structure: Root Cause → Full Evidence Chain (with timestamps) → Contributing Factors → Detailed Recommendations → Fix Plan → Risk Assessment.
- Include CloudTrail event names, metric data points, and KB matches when available.""",
}

SRE_ADDENDA: dict[str, str] = {
    "concise": """\
- For Mode A (fix plans): numbered steps, one line per step, no prose.
- For Mode B (investigation): 1-sentence answer + key findings bullets.""",
    "medium": """\
- For Mode A (fix plans): use numbered steps, one line per step.
- For Mode B (investigation): lead with a 2-3 sentence summary, then key findings as bullets.""",
    "detailed": """\
- For Mode A (fix plans): numbered steps with full CLI commands, pre/post checks, rollback plan, and estimated impact.
- For Mode B (investigation): comprehensive findings organized by resource, with topology context and capacity data.""",
}


def get_output_rules(agent_type: str = "generic") -> str:
    """Return the OUTPUT FORMAT RULES block for the current detail level.

    Reads the detail level from the ContextVar set by config.get_detail_level().

    Args:
        agent_type: One of 'rca', 'sre', or 'generic'.

    Returns:
        Formatted rules string ready to inject into a system prompt.
    """
    level = get_detail_level()
    rules = OUTPUT_RULES.get(level, OUTPUT_RULES["medium"])

    addenda = ""
    if agent_type == "rca":
        addenda = RCA_ADDENDA.get(level, "")
    elif agent_type == "sre":
        addenda = SRE_ADDENDA.get(level, "")

    if addenda:
        return f"{rules}\n{addenda}"
    return rules


def build_system_prompt(
    base: str,
    *,
    include_account: bool = True,
    include_skills: bool = True,
    agent_type: str = "generic",
) -> str:
    """Compose a final system prompt from a base prompt + selected preamble blocks.

    Args:
        base: The agent's base system prompt text.
        include_account: Prepend the account preamble instruction.
        include_skills: Append skills XML + usage protocol (requires skills_enabled).
        agent_type: Agent type for output rule selection ('rca', 'sre', or 'generic').

    Returns:
        Assembled system prompt string.
    """
    parts: list[str] = []

    if include_account:
        parts.append(ACCOUNT_PREAMBLE)

    parts.append(base)

    # Always inject output rules
    parts.append(get_output_rules(agent_type))

    if include_skills and settings.skills_enabled:
        from agenticops.skills.loader import get_available_skills_xml

        xml = get_available_skills_xml()
        if xml:
            parts.append(xml)
            parts.append(SKILLS_USAGE_PROTOCOL)

    return "\n\n".join(parts)


# ── Agent Retry Helper ─────────────────────────────────────────────

_retry_logger = logging.getLogger(__name__)

_TRANSIENT_MARKERS = ("timed out", "read timeout", "connection reset", "throttling")


def invoke_with_retry(agent, prompt: str, *, max_retries: int = 2, backoff: float = 3.0):
    """Invoke a Strands agent with retry on transient Bedrock errors.

    Args:
        agent: A Strands Agent instance.
        prompt: The user message to send.
        max_retries: Total attempts (default 2 = 1 original + 1 retry).
        backoff: Seconds to wait between retries.

    Returns:
        The agent result object.

    Raises:
        The original exception if all retries are exhausted or error is non-transient.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return agent(prompt)
        except Exception as e:
            err_lower = str(e).lower()
            is_transient = any(m in err_lower for m in _TRANSIENT_MARKERS)
            if attempt < max_retries and is_transient:
                _retry_logger.warning(
                    "Bedrock transient error (attempt %d/%d), retrying in %.0fs: %s",
                    attempt, max_retries, backoff, e,
                )
                time.sleep(backoff)
                continue
            raise
