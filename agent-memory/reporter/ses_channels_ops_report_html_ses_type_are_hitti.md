---
agent: reporter
confidence: 4
created_at: '2026-07-05'
created_by: user
last_confirmed: '2026-07-05'
last_used: '2026-07-12'
source: chat
status: active
type: pattern
---

SES channels (ops-report-html, ses type) are hitting 'Daily message quota exceeded' throttling on 2026-07-04. When distributing reports, prefer sns-report channel (ops-reports) as primary; SES may fail on quota. For free-text alerts, share_content fails on sns-report/ses channels because sns-report expects a Report ID not free text — use distribute_report with a saved report ID instead, or send_to_channel with content_type=report/issue.
