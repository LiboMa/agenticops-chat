---
agent: detect
confidence: 2
created_at: '2026-07-08'
created_by: user
last_confirmed: '2026-07-08'
last_used: '2026-07-09'
related_issue_id: 418
resource_pattern: arn:aws:s3:::unknown/*
source: auto
status: active
type: feedback
---

GuardDuty: Anomalous S3 Write Behavior by IAM Entity (3 Findings, Severity 5.0)

Three GuardDuty findings (severity 5.0, Type: Impact:S3/AnomalousBehavior.Write) detected an IAM entity writing to S3 in an unusual way. Finding IDs: d2cf5b4f85d55229fdca32b497ee593b (updated 2026-06-11), e6cf57ad675c4932c9f8fc703155ef03 (2026-06-10), 78cf344e6dfcd02b6cf09f76efa914e2 (2026-05-27). Region: us-east-1. Repeated pattern over 6+ weeks suggests persistent anomalous access. Recommend: identify the IAM entity, review S3 bucket policies, and audit the written objects for unauthorized data staging.

Auto-learned: issue I#418 was dismissed by user.
