"""Deep RCA Engine — Memory-augmented, Graph-aware Root Cause Analysis.

Enhances the base RCAEngine with:
1. Memory recall: check past experiences before invoking LLM
2. Graph context: topology-aware analysis via GraphStore
3. KB search: find similar past incidents from CaseStudy knowledge base
4. Auto-remember: store RCA results as episodic memory (WAL principle)
5. CaseStudy capture: auto-generate KB entries from successful RCAs
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from agenticops.analyze.rca import BedrockLLM, RCAAnalysis, RCAEngine
from agenticops.memory import AgentMemory, MemoryType, get_agent_memory

logger = logging.getLogger(__name__)


@dataclass
class DeepRCAResult:
    """Extended RCA result with memory + graph enrichments."""

    analysis: RCAAnalysis
    memory_hits: list[dict] = field(default_factory=list)
    graph_context: dict | None = None
    kb_matches: list[dict] = field(default_factory=list)
    confidence_boost: float = 0.0  # Added confidence from memory/KB
    memory_id: int | None = None  # ID of stored memory entry
    is_known_pattern: bool = False  # True if matched from memory/KB


class DeepRCAEngine:
    """Memory-augmented RCA Engine.

    Flow:
    1. Recall: search agent memory for similar issues
    2. Enrich: get graph topology context for the resource
    3. Search KB: find past CaseStudies matching symptoms
    4. Analyze: invoke LLM with enriched context (or skip if high-confidence memory match)
    5. Remember: store result in agent memory (WAL)
    6. Capture: auto-generate CaseStudy for KB
    """

    KNOWN_PATTERN_THRESHOLD = 0.85  # Skip LLM if memory confidence above this
    AGENT_NAME = "rca_agent"

    def __init__(
        self,
        base_engine: RCAEngine | None = None,
        memory: AgentMemory | None = None,
    ):
        self.base_engine = base_engine or RCAEngine()
        self.memory = memory or get_agent_memory(self.AGENT_NAME)
        self._llm = self.base_engine.llm

    async def analyze(
        self,
        anomaly_title: str,
        anomaly_description: str,
        resource_id: str = "",
        resource_type: str = "",
        severity: str = "medium",
        context: dict | None = None,
        save_to_kb: bool = True,
    ) -> DeepRCAResult:
        """Perform deep RCA with memory + graph + KB enrichment.

        This is the main entry point. Implements the 6-step flow.
        """
        context = context or {}
        result = DeepRCAResult(
            analysis=RCAAnalysis(root_cause="", confidence_score=0.0)
        )

        # ── Step 1: Recall from memory ────────────────────────
        query = f"{anomaly_title} {anomaly_description} {resource_type}"
        memory_hits = await self.memory.recall(query, top_k=3)

        if memory_hits:
            result.memory_hits = [
                {
                    "content": m.content[:300],
                    "confidence": m.confidence,
                    "type": m.memory_type.value,
                    "source": m.source,
                    "recall_count": m.recall_count,
                }
                for m in memory_hits
            ]

            # Check if this is a known pattern
            best = memory_hits[0]
            if best.confidence >= self.KNOWN_PATTERN_THRESHOLD:
                result.is_known_pattern = True
                result.analysis = RCAAnalysis(
                    root_cause=f"[Known Pattern] {best.content}",
                    confidence_score=min(1.0, best.confidence + 0.1),
                    recommendations=[
                        "Apply previously successful resolution",
                        f"Matched from memory (source: {best.source})",
                    ],
                )
                result.confidence_boost = 0.1
                logger.info(
                    "Deep RCA: known pattern matched (confidence=%.2f)",
                    best.confidence,
                )

        # ── Step 2: Graph context enrichment ──────────────────
        if resource_id:
            try:
                from agenticops.graph.context import get_alert_context

                graph_ctx = get_alert_context(resource_id)
                if graph_ctx:
                    result.graph_context = graph_ctx
                    context["topology"] = graph_ctx.get("topology_summary", "")
                    context["blast_radius"] = graph_ctx.get("blast_radius", {})
                    context["dependencies"] = graph_ctx.get("dependencies", {})
                    logger.info(
                        "Deep RCA: graph context enriched (%d neighbors)",
                        len(graph_ctx.get("neighbors", [])),
                    )
            except Exception as e:
                logger.warning("Graph context unavailable: %s", e)

        # ── Step 3: KB search ─────────────────────────────────
        try:
            from agenticops.kb.search import hybrid_search

            kb_results = hybrid_search(
                query=query,
                limit=3,
            )
            if kb_results:
                result.kb_matches = [
                    {
                        "title": r.get("title", ""),
                        "score": r.get("score", 0),
                        "root_cause": r.get("root_cause", "")[:200],
                    }
                    for r in kb_results
                ]
                # Add KB context to LLM prompt
                context["past_incidents"] = [
                    f"- {r.get('title', '')}: {r.get('root_cause', '')[:150]}"
                    for r in kb_results[:3]
                ]
                logger.info("Deep RCA: %d KB matches found", len(kb_results))
        except Exception as e:
            logger.warning("KB search unavailable: %s", e)

        # ── Step 4: LLM analysis (skip if known pattern) ─────
        if not result.is_known_pattern:
            try:
                prompt = self._build_deep_prompt(
                    title=anomaly_title,
                    description=anomaly_description,
                    resource_id=resource_id,
                    resource_type=resource_type,
                    severity=severity,
                    context=context,
                    memory_hints=result.memory_hits,
                )
                response = self._llm.invoke(prompt)
                result.analysis = self._parse_response(response)
                result.analysis.llm_response = response

                # Boost confidence from memory/KB correlation
                if result.memory_hits:
                    result.confidence_boost = 0.05 * len(result.memory_hits)
                    result.analysis.confidence_score = min(
                        1.0,
                        result.analysis.confidence_score + result.confidence_boost,
                    )
            except Exception as e:
                logger.error("LLM analysis failed: %s", e)
                if result.memory_hits:
                    # Fallback to memory
                    best = result.memory_hits[0]
                    result.analysis = RCAAnalysis(
                        root_cause=f"[Memory Fallback] {best['content']}",
                        confidence_score=best["confidence"] * 0.8,
                    )
                else:
                    result.analysis = RCAAnalysis(
                        root_cause=f"Analysis failed: {e}",
                        confidence_score=0.0,
                    )

        # ── Step 5: Remember (WAL — write before respond) ────
        memory_content = (
            f"RCA for {anomaly_title}: {result.analysis.root_cause[:200]}"
        )
        if result.analysis.recommendations:
            memory_content += f" | Fix: {result.analysis.recommendations[0][:100]}"

        entry = await self.memory.remember(
            content=memory_content,
            memory_type=MemoryType.EPISODIC,
            context={
                "resource_id": resource_id,
                "resource_type": resource_type,
                "severity": severity,
                "confidence": result.analysis.confidence_score,
                "is_known_pattern": result.is_known_pattern,
            },
            source=f"deep_rca:{resource_id or 'unknown'}",
            confidence=result.analysis.confidence_score,
        )
        result.memory_id = entry.id

        # ── Step 6: CaseStudy capture ─────────────────────────
        if save_to_kb and result.analysis.confidence_score >= 0.6:
            try:
                await self._save_case_study(
                    title=anomaly_title,
                    description=anomaly_description,
                    result=result,
                    resource_type=resource_type,
                    severity=severity,
                )
            except Exception as e:
                logger.warning("CaseStudy capture failed: %s", e)

        return result

    def _build_deep_prompt(
        self,
        title: str,
        description: str,
        resource_id: str,
        resource_type: str,
        severity: str,
        context: dict,
        memory_hints: list[dict],
    ) -> str:
        """Build enriched RCA prompt with memory + graph + KB context."""
        sections = [
            "You are an expert SRE performing Deep Root Cause Analysis.",
            "",
            "## Incident",
            f"- **Title**: {title}",
            f"- **Description**: {description}",
            f"- **Resource**: {resource_id} ({resource_type})",
            f"- **Severity**: {severity}",
        ]

        # Memory context
        if memory_hints:
            sections.append("\n## Past Experience (Agent Memory)")
            for i, hint in enumerate(memory_hints, 1):
                sections.append(
                    f"{i}. [{hint['type']}] {hint['content'][:200]} "
                    f"(confidence: {hint['confidence']:.2f})"
                )

        # Topology context
        if context.get("topology"):
            sections.append(f"\n## Topology\n{context['topology']}")

        if context.get("blast_radius"):
            br = context["blast_radius"]
            sections.append(
                f"**Blast Radius**: {br.get('total_affected', 0)} resources affected"
            )

        if context.get("dependencies"):
            deps = context["dependencies"]
            up = len(deps.get("upstream", []))
            down = len(deps.get("downstream", []))
            sections.append(f"**Dependencies**: {up} upstream, {down} downstream")

        # Past incidents from KB
        if context.get("past_incidents"):
            sections.append("\n## Similar Past Incidents (Knowledge Base)")
            sections.extend(context["past_incidents"])

        # Additional context
        extra = {
            k: v
            for k, v in context.items()
            if k not in ("topology", "blast_radius", "dependencies", "past_incidents")
        }
        if extra:
            sections.append(
                f"\n## Additional Context\n{json.dumps(extra, indent=2, default=str)}"
            )

        sections.append("""
## Instructions
Analyze this incident using ALL available context (memory, topology, past incidents).

Provide your response as JSON:
```json
{
    "root_cause": "Specific root cause explanation",
    "confidence_score": 0.85,
    "contributing_factors": ["factor1", "factor2"],
    "recommendations": ["actionable rec 1", "actionable rec 2"],
    "related_resources": ["resource1"]
}
```
""")
        return "\n".join(sections)

    def _parse_response(self, response: str) -> RCAAnalysis:
        """Parse LLM JSON response."""
        try:
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response[json_start:json_end])
                return RCAAnalysis(
                    root_cause=data.get("root_cause", "Unknown"),
                    confidence_score=float(data.get("confidence_score", 0.5)),
                    contributing_factors=data.get("contributing_factors", []),
                    recommendations=data.get("recommendations", []),
                    related_resources=data.get("related_resources", []),
                )
        except (json.JSONDecodeError, ValueError):
            pass
        return RCAAnalysis(root_cause=response[:500], confidence_score=0.5)

    async def _save_case_study(
        self,
        title: str,
        description: str,
        result: DeepRCAResult,
        resource_type: str,
        severity: str,
    ) -> None:
        """Auto-generate CaseStudy from RCA result."""
        from agenticops.kb.case_study import (
            CaseStudy,
            CaseStudyMeta,
            EmbeddingInputs,
            LessonsLearned,
            Resolution,
        )

        case = CaseStudy(
            case_id=f"auto-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            title=title,
            symptoms=description,
            root_cause=result.analysis.root_cause,
            meta=CaseStudyMeta(
                resource_type=resource_type,
                severity=severity,
                created_at=datetime.utcnow().strftime("%Y-%m-%d"),
                tags=["auto-generated", "deep-rca"],
            ),
            embedding_inputs=EmbeddingInputs(
                symptom_vector_text=description,
                root_cause_vector_text=result.analysis.root_cause,
            ),
            resolution=Resolution(
                immediate_action=(
                    result.analysis.recommendations[0]
                    if result.analysis.recommendations
                    else ""
                ),
            ),
            lessons_learned=LessonsLearned(
                efficiency_score=result.analysis.confidence_score,
            ),
        )

        # Store as procedural memory too
        await self.memory.remember(
            content=f"Resolution for {title}: {case.resolution.immediate_action}",
            memory_type=MemoryType.PROCEDURAL,
            source=f"case_study:{case.case_id}",
            confidence=result.analysis.confidence_score,
        )

        logger.info("CaseStudy auto-captured: %s", case.case_id)
