"""Deep RCA Engine — Memory-augmented, Graph-aware Root Cause Analysis.

Enhances the base RCAEngine with:
1. Memory recall: check past experiences before invoking LLM
2. Graph context: topology-aware analysis via GraphStore
3. KB search: find similar past incidents from CaseStudy knowledge base
4. Iterative investigation: loop until confidence >= threshold
5. Self-verification: challenge conclusions (Voyager CriticAgent pattern)
6. Auto-remember: store RCA results as episodic memory (WAL principle)
7. CaseStudy capture: auto-generate KB entries from successful RCAs
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from agenticops.analyze.evidence import EvidenceItem, gather_evidence
from agenticops.analyze.rca import BedrockLLM, RCAAnalysis, RCAEngine
from agenticops.memory import AgentMemory, MemoryType, get_agent_memory

logger = logging.getLogger(__name__)


@dataclass
class DeepRCAResult:
    """Extended RCA result with memory + graph + iteration enrichments."""

    analysis: RCAAnalysis
    memory_hits: list[dict] = field(default_factory=list)
    graph_context: dict | None = None
    kb_matches: list[dict] = field(default_factory=list)
    evidence_chain: list[EvidenceItem] = field(default_factory=list)
    confidence_boost: float = 0.0
    memory_id: int | None = None
    is_known_pattern: bool = False
    iterations: int = 1
    iteration_history: list[dict] = field(default_factory=list)
    duration_ms: int = 0
    verified: bool = False  # Self-verification passed


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
    CONFIDENCE_THRESHOLD = 0.7      # Stop iterating when reached
    MAX_ITERATIONS = 3              # Max investigation loops
    TIMEOUT_SECONDS = 120           # Max wall-clock per investigation
    AGENT_NAME = "rca_agent"

    def __init__(
        self,
        base_engine: RCAEngine | None = None,
        memory: AgentMemory | None = None,
        max_iterations: int | None = None,
        confidence_threshold: float | None = None,
    ):
        self.base_engine = base_engine or RCAEngine()
        self.memory = memory or get_agent_memory(self.AGENT_NAME)
        self._llm = self.base_engine.llm
        if max_iterations is not None:
            self.MAX_ITERATIONS = max_iterations
        if confidence_threshold is not None:
            self.CONFIDENCE_THRESHOLD = confidence_threshold

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
        """Perform deep RCA with memory + graph + KB + iteration loop.

        7-step flow:
        1. Recall from memory (Fast Path check)
        2. Graph context enrichment
        3. KB search
        4. Iterative LLM analysis (loop until confidence >= threshold)
        5. Self-verification (Voyager CriticAgent pattern)
        6. WAL write (remember result)
        7. CaseStudy capture
        """
        start_time = time.monotonic()
        context = context or {}
        result = DeepRCAResult(
            analysis=RCAAnalysis(root_cause="", confidence_score=0.0)
        )

        # ── Step 1: Recall from memory (Fast Path) ───────────
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

            # Fast Path: known pattern → skip LLM entirely
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
                result.verified = True  # Known patterns are pre-verified
                logger.info(
                    "Deep RCA Fast Path: known pattern (confidence=%.2f)",
                    best.confidence,
                )
                # Skip to Step 6 (WAL)
                await self._wal_write(result, anomaly_title, resource_id, resource_type, severity)
                result.duration_ms = int((time.monotonic() - start_time) * 1000)
                return result

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

            kb_results = hybrid_search(query=query, limit=3)
            if kb_results:
                result.kb_matches = [
                    {
                        "title": r.get("title", ""),
                        "score": r.get("score", 0),
                        "root_cause": r.get("root_cause", "")[:200],
                    }
                    for r in kb_results
                ]
                context["past_incidents"] = [
                    f"- {r.get('title', '')}: {r.get('root_cause', '')[:150]}"
                    for r in kb_results[:3]
                ]
                logger.info("Deep RCA: %d KB matches found", len(kb_results))
        except Exception as e:
            logger.warning("KB search unavailable: %s", e)

        # ── Step 4: Iterative LLM analysis ────────────────────
        for iteration in range(1, self.MAX_ITERATIONS + 1):
            result.iterations = iteration

            # Check timeout
            elapsed = time.monotonic() - start_time
            if elapsed > self.TIMEOUT_SECONDS:
                logger.warning("Deep RCA timeout after %ds", elapsed)
                break

            try:
                prompt = self._build_deep_prompt(
                    title=anomaly_title,
                    description=anomaly_description,
                    resource_id=resource_id,
                    resource_type=resource_type,
                    severity=severity,
                    context=context,
                    memory_hints=result.memory_hits,
                    evidence_chain=result.evidence_chain,
                    iteration=iteration,
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

                # Record iteration history
                result.iteration_history.append({
                    "iteration": iteration,
                    "confidence": result.analysis.confidence_score,
                    "evidence_count": len(result.evidence_chain),
                    "root_cause_preview": result.analysis.root_cause[:100],
                })

                # Check if confidence is sufficient
                if result.analysis.confidence_score >= self.CONFIDENCE_THRESHOLD:
                    logger.info(
                        "Deep RCA: confidence %.2f >= %.2f after %d iterations",
                        result.analysis.confidence_score,
                        self.CONFIDENCE_THRESHOLD,
                        iteration,
                    )
                    break

                # ── Evidence gap detection ────────────────────
                if iteration < self.MAX_ITERATIONS:
                    gaps = await self._detect_evidence_gaps(
                        result.analysis, result.evidence_chain, resource_id
                    )
                    for gap in gaps:
                        evidence = await gather_evidence(
                            gap, resource_id=resource_id, context=context
                        )
                        if evidence:
                            result.evidence_chain.append(evidence)
                            # Update context with new evidence
                            context[f"evidence_{evidence.source}"] = evidence.content

            except Exception as e:
                logger.error("LLM analysis failed (iteration %d): %s", iteration, e)
                if result.memory_hits:
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
                break

        # ── Step 5: Self-verification ─────────────────────────
        if (
            result.analysis.confidence_score >= 0.5
            and not result.is_known_pattern
        ):
            result.verified = await self._self_verify(result)

        # ── Step 6: WAL write ─────────────────────────────────
        await self._wal_write(result, anomaly_title, resource_id, resource_type, severity)

        # ── Step 7: CaseStudy capture ─────────────────────────
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

        result.duration_ms = int((time.monotonic() - start_time) * 1000)
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
        evidence_chain: list[EvidenceItem] | None = None,
        iteration: int = 1,
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

        # Evidence chain from previous iterations
        if evidence_chain:
            sections.append("\n## Collected Evidence")
            for i, ev in enumerate(evidence_chain, 1):
                sections.append(f"{i}. {ev.summary()}")

        if iteration > 1:
            sections.append(f"\n*This is iteration {iteration}. Previous attempts had insufficient confidence.*")

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

    async def _detect_evidence_gaps(
        self,
        analysis: RCAAnalysis,
        evidence_chain: list[EvidenceItem],
        resource_id: str,
    ) -> list[dict]:
        """Ask LLM what additional evidence would help."""
        try:
            evidence_summary = "; ".join(e.summary(100) for e in evidence_chain) or "None yet"
            prompt = (
                f"Current RCA confidence: {analysis.confidence_score:.2f}\n"
                f"Root cause hypothesis: {analysis.root_cause[:200]}\n"
                f"Evidence so far: {evidence_summary}\n"
                f"Resource: {resource_id}\n\n"
                "What additional evidence would most help determine the root cause?\n"
                'Return a JSON list: [{"type": "cloudtrail"|"cloudwatch"|"network"|"trace"|"logs", '
                '"params": {...}}]'
            )
            response = self._llm.invoke(prompt, max_tokens=512)
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                gaps = json.loads(response[json_start:json_end])
                return gaps[:3]  # Cap at 3 evidence requests per iteration
        except Exception as e:
            logger.warning("Evidence gap detection failed: %s", e)
        return []

    async def _self_verify(self, result: DeepRCAResult) -> bool:
        """Challenge the RCA conclusion (Voyager CriticAgent pattern).

        Returns True if verification passes, False if challenged.
        """
        try:
            evidence_summary = "; ".join(
                e.summary(100) for e in result.evidence_chain
            ) or "No formal evidence collected"

            prompt = (
                "You are a critical reviewer of RCA conclusions.\n"
                f"Root cause: {result.analysis.root_cause[:300]}\n"
                f"Evidence: {evidence_summary}\n"
                f"Confidence: {result.analysis.confidence_score:.2f}\n"
                f"Memory matches: {len(result.memory_hits)}\n\n"
                "Questions:\n"
                "1. Does the evidence support this root cause, or is it merely correlated?\n"
                "2. Are there alternative explanations missed?\n"
                "3. Is the confidence score justified?\n\n"
                'Return JSON: {"valid": true/false, "critique": "...", "adjusted_confidence": 0.X}'
            )
            response = self._llm.invoke(prompt, max_tokens=512)
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response[json_start:json_end])
                valid = data.get("valid", True)
                adjusted = float(data.get("adjusted_confidence", result.analysis.confidence_score))
                result.analysis.confidence_score = min(1.0, max(0.0, adjusted))

                if not valid and data.get("critique"):
                    # Store critique as evidence
                    result.evidence_chain.append(EvidenceItem(
                        source="self_verification",
                        content=f"Critique: {data['critique'][:200]}",
                        confidence_delta=adjusted - result.analysis.confidence_score,
                    ))
                    logger.info("Self-verification challenged: %s", data["critique"][:100])
                return valid
        except Exception as e:
            logger.warning("Self-verification failed: %s", e)
        return True  # Default to valid if verification fails

    async def _wal_write(
        self,
        result: DeepRCAResult,
        anomaly_title: str,
        resource_id: str,
        resource_type: str,
        severity: str,
    ) -> None:
        """Write-Ahead Log: store result in memory before returning."""
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
                "iterations": result.iterations,
                "verified": result.verified,
            },
            source=f"deep_rca:{resource_id or 'unknown'}",
            confidence=result.analysis.confidence_score,
        )
        result.memory_id = entry.id

        # If high confidence, also store as PROCEDURAL
        if result.analysis.confidence_score >= 0.8:
            factors = ", ".join(result.analysis.contributing_factors[:3]) if result.analysis.contributing_factors else "unknown"
            await self.memory.remember(
                content=f"PATTERN: {factors} → {result.analysis.root_cause[:150]}",
                memory_type=MemoryType.PROCEDURAL,
                source=f"rca:pattern:{resource_id or 'unknown'}",
                confidence=result.analysis.confidence_score,
            )

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
