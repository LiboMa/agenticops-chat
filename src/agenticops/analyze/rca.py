"""Root Cause Analysis Engine - LLM-powered analysis using AWS Bedrock."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from agenticops.config import settings
from agenticops.models import Anomaly, AWSAccount, AWSResource, RCAResult, get_session
from agenticops.monitor.cloudwatch import CloudWatchMonitor

logger = logging.getLogger(__name__)


@dataclass
class RCAAnalysis:
    """RCA analysis result."""

    root_cause: str
    confidence_score: float
    contributing_factors: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    related_resources: list[str] = field(default_factory=list)
    llm_response: str = ""


class BedrockLLM:
    """AWS Bedrock LLM client."""

    def __init__(self, region: str = None, model_id: str = None):
        """Initialize Bedrock client."""
        self.region = region or settings.bedrock_region
        self.model_id = model_id or settings.bedrock_model_id
        self._client = None

    @property
    def client(self):
        """Get Bedrock runtime client."""
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )
        return self._client

    def invoke(self, prompt: str, max_tokens: int = 4096) -> str:
        """
        Invoke Bedrock model with a prompt.

        Args:
            prompt: The prompt to send to the model
            max_tokens: Maximum tokens in response

        Returns:
            Model response text
        """
        try:
            # Format for Claude on Bedrock
            body = json.dumps(
                {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                }
            )

            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())
            return response_body["content"][0]["text"]

        except ClientError as e:
            logger.error(f"Bedrock invocation failed: {e}")
            raise


class RCAEngine:
    """Root Cause Analysis Engine."""

    def __init__(self, account: Optional[AWSAccount] = None):
        """Initialize RCA engine."""
        self.account = account
        self.llm = BedrockLLM()
        self.monitor = CloudWatchMonitor(account) if account else None

    def analyze_anomaly(
        self,
        anomaly: Anomaly,
        context: dict = None,
        save: bool = True,
    ) -> RCAAnalysis:
        """
        Perform RCA on a detected anomaly.

        Args:
            anomaly: The anomaly to analyze
            context: Additional context (metrics, logs, etc.)
            save: Whether to save result to database

        Returns:
            RCAAnalysis with root cause and recommendations
        """
        context = context or {}

        # Build prompt with anomaly details and context
        prompt = self._build_rca_prompt(anomaly, context)
        logger.info(f"Running RCA for anomaly: {anomaly.title}")

        # Invoke LLM
        try:
            response = self.llm.invoke(prompt)
            analysis = self._parse_rca_response(response)
            analysis.llm_response = response

            # Save to database
            if save:
                self._save_rca_result(anomaly, analysis, prompt)

            return analysis

        except Exception as e:
            logger.exception(f"RCA failed for anomaly {anomaly.id}")
            return RCAAnalysis(
                root_cause=f"Analysis failed: {str(e)}",
                confidence_score=0.0,
            )

    def _build_rca_prompt(self, anomaly: Anomaly, context: dict) -> str:
        """Build RCA prompt for the LLM."""
        prompt = f"""You are an expert AWS cloud operations engineer performing Root Cause Analysis (RCA).

## Anomaly Details
- **Title**: {anomaly.title}
- **Description**: {anomaly.description}
- **Resource ID**: {anomaly.resource_id}
- **Resource Type**: {anomaly.resource_type}
- **Region**: {anomaly.region}
- **Severity**: {anomaly.severity}
- **Detected At**: {anomaly.detected_at}
- **Anomaly Type**: {anomaly.anomaly_type}

## Metrics Information
- **Metric Name**: {anomaly.metric_name or 'N/A'}
- **Expected Value**: {anomaly.expected_value or 'N/A'}
- **Actual Value**: {anomaly.actual_value or 'N/A'}
- **Deviation**: {anomaly.deviation_percent:.2f}% if anomaly.deviation_percent else 'N/A'

## Additional Context
{json.dumps(context, indent=2, default=str) if context else 'No additional context provided.'}

## Raw Data
{json.dumps(anomaly.raw_data, indent=2) if anomaly.raw_data else 'No raw data.'}

---

Please analyze this anomaly and provide:

1. **Root Cause**: What is the most likely root cause of this anomaly? Be specific.

2. **Confidence Score**: How confident are you in this analysis? (0.0 to 1.0)

3. **Contributing Factors**: List 2-5 factors that may have contributed to this issue.

4. **Recommendations**: Provide 3-5 actionable recommendations to resolve and prevent this issue.

5. **Related Resources**: List any other AWS resources that might be affected or related.

Format your response as JSON:
```json
{{
    "root_cause": "...",
    "confidence_score": 0.85,
    "contributing_factors": ["factor1", "factor2"],
    "recommendations": ["rec1", "rec2", "rec3"],
    "related_resources": ["resource1", "resource2"]
}}
```
"""
        return prompt

    def _parse_rca_response(self, response: str) -> RCAAnalysis:
        """Parse LLM response into RCAAnalysis."""
        try:
            # Extract JSON from response
            json_start = response.find("{")
            json_end = response.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = response[json_start:json_end]
                data = json.loads(json_str)

                return RCAAnalysis(
                    root_cause=data.get("root_cause", "Unable to determine root cause"),
                    confidence_score=float(data.get("confidence_score", 0.5)),
                    contributing_factors=data.get("contributing_factors", []),
                    recommendations=data.get("recommendations", []),
                    related_resources=data.get("related_resources", []),
                )
            else:
                # Fallback: use raw response as root cause
                return RCAAnalysis(
                    root_cause=response[:1000],
                    confidence_score=0.5,
                )

        except json.JSONDecodeError:
            logger.warning("Failed to parse JSON from LLM response")
            return RCAAnalysis(
                root_cause=response[:1000],
                confidence_score=0.5,
            )

    def _save_rca_result(
        self,
        anomaly: Anomaly,
        analysis: RCAAnalysis,
        prompt: str,
    ):
        """Save RCA result to database."""
        session = get_session()

        try:
            result = RCAResult(
                anomaly_id=anomaly.id,
                analysis_type="auto",
                root_cause=analysis.root_cause,
                confidence_score=analysis.confidence_score,
                contributing_factors=analysis.contributing_factors,
                recommendations=analysis.recommendations,
                related_resources=analysis.related_resources,
                llm_model=self.llm.model_id,
                llm_prompt=prompt,
                llm_response=analysis.llm_response,
            )
            session.add(result)
            session.commit()
            logger.info(f"Saved RCA result for anomaly {anomaly.id}")

        except Exception as e:
            session.rollback()
            logger.exception("Failed to save RCA result")
        finally:
            session.close()

    def analyze_with_metrics(
        self,
        anomaly: Anomaly,
        hours: int = 24,
        save: bool = True,
    ) -> RCAAnalysis:
        """Analyze anomaly with additional metrics context."""
        if not self.monitor:
            return self.analyze_anomaly(anomaly, save=save)

        # Gather additional metrics
        try:
            session = get_session()
            resource = (
                session.query(AWSResource)
                .filter_by(resource_id=anomaly.resource_id)
                .first()
            )
            session.close()

            if resource:
                metrics = self.monitor.get_service_metrics(
                    service_type=resource.resource_type,
                    resource_id=resource.resource_id,
                    region=resource.region,
                    hours=hours,
                )

                # Summarize metrics for context
                context = {
                    "resource_metadata": resource.resource_metadata,
                    "resource_tags": resource.tags,
                    "recent_metrics": {
                        name: {
                            "count": len(points),
                            "min": min(p["value"] for p in points) if points else None,
                            "max": max(p["value"] for p in points) if points else None,
                            "avg": sum(p["value"] for p in points) / len(points)
                            if points
                            else None,
                        }
                        for name, points in metrics.items()
                    },
                }

                return self.analyze_anomaly(anomaly, context=context, save=save)

        except Exception as e:
            logger.warning(f"Failed to gather metrics context: {e}")

        return self.analyze_anomaly(anomaly, save=save)

    def batch_analyze(
        self,
        anomalies: list[Anomaly],
        save: bool = True,
    ) -> dict[int, RCAAnalysis]:
        """Analyze multiple anomalies."""
        results = {}

        for anomaly in anomalies:
            try:
                analysis = self.analyze_with_metrics(anomaly, save=save)
                results[anomaly.id] = analysis
            except Exception as e:
                logger.error(f"Analysis failed for anomaly {anomaly.id}: {e}")
                results[anomaly.id] = RCAAnalysis(
                    root_cause=f"Analysis failed: {str(e)}",
                    confidence_score=0.0,
                )

        return results

    def get_analysis_history(
        self,
        anomaly_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[RCAResult]:
        """Get historical RCA results."""
        session = get_session()

        try:
            query = session.query(RCAResult).order_by(RCAResult.created_at.desc())

            if anomaly_id:
                query = query.filter_by(anomaly_id=anomaly_id)

            return query.limit(limit).all()

        finally:
            session.close()
