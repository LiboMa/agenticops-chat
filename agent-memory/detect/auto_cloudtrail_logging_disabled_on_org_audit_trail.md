---
agent: detect
confidence: 2
created_at: '2026-04-02'
created_by: user
last_confirmed: '2026-04-02'
last_used: '2026-05-31'
related_issue_id: 324
resource_pattern: org-audit-trail/*
source: auto
status: active
type: feedback
---

CloudTrail Logging Disabled on org-audit-trail

The multi-region CloudTrail trail 'org-audit-trail' (home region: cn-north-1, S3 bucket: cloudtrail-logs-113506788061) has IsLogging=false. No API activity is being recorded, creating a full audit gap. This violates compliance requirements and prevents incident investigation via CloudTrail.

Auto-learned: issue I#324 was dismissed by user.
