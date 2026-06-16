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
    "Call get_active_account to see all enabled cloud accounts. Tools are "
    "account-addressed: pass account='<name>' when the target account is known; "
    "run_on_host/run_kubectl auto-resolve the account from inventory by host/cluster "
    "id; single-account deployments resolve automatically. On ambiguity a tool "
    "returns the enabled account list — pick one and retry. Host access ladder: "
    "SSM → SSH → actionable report. If no account is configured, inform the user."
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
- SKILL CREATION: If no existing skill covers the current problem domain, ask the user for confirmation,
  then call create_skill(name, description, publish=True) to generate and immediately activate a new skill.
  Never create a skill without user confirmation.
"""

# ── Shared Investigation Prompt Fragments (RCA + SRE) ───────────────

_SKILL_ROUTES_COMMON = """\
     - EC2/host issues → activate_skill("linux-admin") + activate_skill("aws-compute")
     - Network/connectivity → activate_skill("network-engineer")
     - Kubernetes/EKS/pods → activate_skill("kubernetes-admin")
     - RDS/DynamoDB/Redis → activate_skill("database-admin")
     - CloudWatch/metrics → activate_skill("monitoring")
     - Log analysis → activate_skill("log-analysis")
     - S3/EBS/EFS → activate_skill("aws-storage")"""


def skills_activation_block(extra_routes: list[str], outro: str) -> str:
    """Build the shared ACTIVATE DOMAIN SKILLS routing table (RCA + SRE).

    Args:
        extra_routes: Agent-specific route lines appended after the common set
            (e.g. RCA adds distributed-tracing, SRE adds security-engineer).
        outro: Agent-specific closing sentence.
    """
    routes = _SKILL_ROUTES_COMMON
    for r in extra_routes:
        routes += f"\n     - {r}"
    return (
        "ACTIVATE DOMAIN SKILLS: Based on the issue type, call activate_skill to load\n"
        "     domain-specific troubleshooting knowledge BEFORE investigating:\n"
        f"{routes}\n"
        f"     {outro}"
    )


LOCAL_FILE_INSPECTION_BLOCK = """\
LOCAL FILE INSPECTION (when you need to read configs, logs, or templates):
     a. First call activate_skill("local-os-operator") to load file operation tools and decision trees.
     b. Then use read_local_file, tail_local_file, search_local_file, list_local_directory, file_stat
        — these tools are dynamically registered when you activate the skill.
     c. Sensitive files (.env, credentials, private keys, etc.) are automatically blocked."""


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
    agent_name: str = "",
) -> str:
    """Compose a final system prompt from a base prompt + selected preamble blocks.

    Args:
        base: The agent's base system prompt text.
        include_account: Prepend the account preamble instruction.
        include_skills: Append skills XML + usage protocol (requires skills_enabled).
        agent_type: Agent type for output rule selection ('rca', 'sre', or 'generic').
        agent_name: Agent name for memory injection (e.g. "detect"). Empty = no memory.

    Returns:
        Assembled system prompt string.
    """
    # Stability-ordered assembly (Bedrock prompt-cache friendly): the prefix
    # is ordered by change frequency — base prompt (static) → skills XML
    # (changes on SKILL.md edits) → output rules (changes on detail-level
    # switch) → memory LAST (changes on every build via touch_last_used).
    # A memory change then invalidates only the prompt tail, not the whole
    # cached prefix. Do not "tidy" this order.
    parts: list[str] = []

    if include_account:
        parts.append(ACCOUNT_PREAMBLE)

    parts.append(base)

    if include_skills and settings.skills_enabled:
        from agenticops.skills.loader import get_available_skills_xml

        xml = get_available_skills_xml()
        if xml:
            parts.append(xml)
            parts.append(SKILLS_USAGE_PROTOCOL)

    # Always inject output rules
    parts.append(get_output_rules(agent_type))

    # Inject agent memory (behavioral constraints learned from feedback) —
    # kept last: most volatile block (see stability note above).
    if agent_name:
        _log = logging.getLogger(__name__)
        try:
            from agenticops.memory.agent_memory import load_agent_memory

            memory_block = load_agent_memory(agent_name)
            if memory_block:
                parts.append(memory_block)
        except (FileNotFoundError, IsADirectoryError):
            # Expected when an agent has no memory yet — recover quietly.
            _log.debug("No agent memory file for %s", agent_name)
        except Exception:
            # Unexpected (permission, parse, etc.) — surface at error level but
            # never block agent construction.
            _log.error("Failed to load agent memory for %s", agent_name, exc_info=True)

    return "\n\n".join(parts)


# ── Agent Retry Helper ─────────────────────────────────────────────

_retry_logger = logging.getLogger(__name__)

# botocore error codes considered transient (retry-worthy)
_TRANSIENT_ERROR_CODES = frozenset({
    "ThrottlingException", "Throttling", "TooManyRequestsException",
    "ServiceUnavailable", "ServiceUnavailableException",
    "RequestTimeout", "RequestTimeoutException", "ModelTimeoutException",
    "InternalServerException", "ModelNotReadyException",
})

# substring fallback (lowercased) when no structured error code is present
_TRANSIENT_MARKERS = (
    "timed out", "timeout", "read timeout", "connection reset",
    "throttl", "service unavailable", "too many requests",
    "internal server error", "503", "429",
)


def _is_transient_error(e: Exception) -> bool:
    """True if the exception looks retry-worthy (structured code first, then substring)."""
    code = None
    response = getattr(e, "response", None)
    if isinstance(response, dict):
        error_dict = response.get("Error")
        if isinstance(error_dict, dict):
            code = error_dict.get("Code")
    if code and code in _TRANSIENT_ERROR_CODES:
        return True
    err_lower = str(e).lower()
    return any(m in err_lower for m in _TRANSIENT_MARKERS)


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
            is_transient = _is_transient_error(e)
            if not is_transient:
                _retry_logger.debug("Non-transient agent error (no retry): %s", e)
            if attempt < max_retries and is_transient:
                _retry_logger.warning(
                    "Bedrock transient error (attempt %d/%d), retrying in %.0fs: %s",
                    attempt, max_retries, backoff, e,
                )
                time.sleep(backoff)
                continue
            raise
