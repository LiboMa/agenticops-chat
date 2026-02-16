"""CaseStudy dataclass for structured KB case records.

Matches the schema from 06-Reporter-Agent-Design.md.
Supports serialization to/from dict, markdown (YAML frontmatter).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional


class CaseStudyStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


@dataclass
class CaseStudyMeta:
    resource_type: str = ""
    severity: str = "medium"
    region: str = ""
    source_issue_id: Optional[int] = None
    source_rca_id: Optional[int] = None
    created_at: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class EmbeddingInputs:
    symptom_vector_text: str = ""
    root_cause_vector_text: str = ""


@dataclass
class Resolution:
    immediate_action: str = ""
    long_term_fix: str = ""
    verification_method: str = ""


@dataclass
class LessonsLearned:
    what_failed: str = ""
    why_missed: str = ""
    efficiency_score: float = 0.5  # 0.0–1.0


@dataclass
class CaseStudy:
    case_id: str = ""
    title: str = ""
    meta: CaseStudyMeta = field(default_factory=CaseStudyMeta)
    embedding_inputs: EmbeddingInputs = field(default_factory=EmbeddingInputs)
    resolution: Resolution = field(default_factory=Resolution)
    lessons_learned: LessonsLearned = field(default_factory=LessonsLearned)
    status: CaseStudyStatus = CaseStudyStatus.PENDING_REVIEW
    verified: bool = False
    reuse_count: int = 0

    # Full symptom/root-cause text for the markdown body
    symptoms: str = ""
    root_cause: str = ""
    prevention: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CaseStudy:
        status_val = data.pop("status", CaseStudyStatus.PENDING_REVIEW.value)
        if isinstance(status_val, str):
            try:
                status_val = CaseStudyStatus(status_val)
            except ValueError:
                status_val = CaseStudyStatus.PENDING_REVIEW
        elif isinstance(status_val, CaseStudyStatus):
            pass
        else:
            status_val = CaseStudyStatus.PENDING_REVIEW

        meta = CaseStudyMeta(**data.pop("meta", {}))
        embedding_inputs = EmbeddingInputs(**data.pop("embedding_inputs", {}))
        resolution = Resolution(**data.pop("resolution", {}))
        lessons_learned = LessonsLearned(**data.pop("lessons_learned", {}))

        return cls(
            meta=meta,
            embedding_inputs=embedding_inputs,
            resolution=resolution,
            lessons_learned=lessons_learned,
            status=status_val,
            **data,
        )

    def to_markdown(self) -> str:
        """Render as markdown with YAML frontmatter compatible with _parse_frontmatter()."""
        tags_str = ", ".join(self.meta.tags) if self.meta.tags else ""
        lines = [
            "---",
            f'title: "{self.title}"',
            f"case_id: {self.case_id}",
            f"resource_type: {self.meta.resource_type}",
            f"severity: {self.meta.severity}",
            f"region: {self.meta.region}",
            f"status: {self.status.value}",
            f"verified: {str(self.verified).lower()}",
            f"efficiency_score: {self.lessons_learned.efficiency_score}",
            f"reuse_count: {self.reuse_count}",
            f"date: {self.meta.created_at or datetime.utcnow().strftime('%Y-%m-%d')}",
            f"tags: [{tags_str}]",
            "---",
            "",
            f"# {self.title}",
            "",
            "## Symptoms",
            self.symptoms or self.embedding_inputs.symptom_vector_text,
            "",
            "## Root Cause",
            self.root_cause or self.embedding_inputs.root_cause_vector_text,
            "",
            "## Resolution",
            f"**Immediate Action:** {self.resolution.immediate_action}",
            "",
            f"**Long-term Fix:** {self.resolution.long_term_fix}",
            "",
            f"**Verification:** {self.resolution.verification_method}",
            "",
            "## Lessons Learned",
            f"- **What failed:** {self.lessons_learned.what_failed}",
            f"- **Why missed:** {self.lessons_learned.why_missed}",
            f"- **Efficiency score:** {self.lessons_learned.efficiency_score}",
            "",
            "## Prevention",
            self.prevention,
        ]
        return "\n".join(lines) + "\n"

    @classmethod
    def from_markdown(cls, text: str) -> CaseStudy:
        """Parse a markdown case study with YAML frontmatter."""
        metadata: dict = {}
        body = text

        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                frontmatter = parts[1].strip()
                body = parts[2].strip()
                for line in frontmatter.split("\n"):
                    line = line.strip()
                    if ":" in line:
                        key, _, value = line.partition(":")
                        key = key.strip()
                        value = value.strip()
                        if value.startswith("[") and value.endswith("]"):
                            value = [
                                v.strip().strip("'\"")
                                for v in value[1:-1].split(",")
                                if v.strip()
                            ]
                        elif value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        metadata[key] = value

        # Extract sections from body
        sections: dict[str, str] = {}
        current_section = ""
        for line in body.split("\n"):
            if line.startswith("## "):
                current_section = line[3:].strip().lower()
                sections[current_section] = ""
            elif current_section:
                sections[current_section] = (
                    sections[current_section] + "\n" + line
                ).strip()

        tags = metadata.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        efficiency = 0.5
        try:
            efficiency = float(metadata.get("efficiency_score", 0.5))
        except (ValueError, TypeError):
            pass

        verified = str(metadata.get("verified", "false")).lower() == "true"
        reuse_count = 0
        try:
            reuse_count = int(metadata.get("reuse_count", 0))
        except (ValueError, TypeError):
            pass

        meta = CaseStudyMeta(
            resource_type=str(metadata.get("resource_type", "")),
            severity=str(metadata.get("severity", "medium")),
            region=str(metadata.get("region", "")),
            created_at=str(metadata.get("date", "")),
            tags=tags,
        )

        symptoms_text = sections.get("symptoms", "")
        root_cause_text = sections.get("root cause", "")

        embedding_inputs = EmbeddingInputs(
            symptom_vector_text=symptoms_text,
            root_cause_vector_text=root_cause_text,
        )

        # Parse resolution section
        resolution_text = sections.get("resolution", "")
        immediate = ""
        long_term = ""
        verification = ""
        for rline in resolution_text.split("\n"):
            if "immediate action" in rline.lower():
                immediate = rline.split(":", 1)[-1].strip().strip("*")
            elif "long-term fix" in rline.lower():
                long_term = rline.split(":", 1)[-1].strip().strip("*")
            elif "verification" in rline.lower():
                verification = rline.split(":", 1)[-1].strip().strip("*")
        resolution = Resolution(
            immediate_action=immediate,
            long_term_fix=long_term,
            verification_method=verification,
        )

        # Parse lessons learned
        lessons_text = sections.get("lessons learned", "")
        what_failed = ""
        why_missed = ""
        for lline in lessons_text.split("\n"):
            if "what failed" in lline.lower():
                what_failed = lline.split(":", 1)[-1].strip().strip("*")
            elif "why missed" in lline.lower():
                why_missed = lline.split(":", 1)[-1].strip().strip("*")
        lessons = LessonsLearned(
            what_failed=what_failed,
            why_missed=why_missed,
            efficiency_score=efficiency,
        )

        status_str = str(metadata.get("status", CaseStudyStatus.PENDING_REVIEW.value))
        try:
            status = CaseStudyStatus(status_str)
        except ValueError:
            status = CaseStudyStatus.PENDING_REVIEW

        return cls(
            case_id=str(metadata.get("case_id", "")),
            title=str(metadata.get("title", "")),
            meta=meta,
            embedding_inputs=embedding_inputs,
            resolution=resolution,
            lessons_learned=lessons,
            status=status,
            verified=verified,
            reuse_count=reuse_count,
            symptoms=symptoms_text,
            root_cause=root_cause_text,
            prevention=sections.get("prevention", ""),
        )
