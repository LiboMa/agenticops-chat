---
agent: detect
confidence: 2
created_at: '2026-07-08'
created_by: user
last_confirmed: '2026-07-08'
last_used: '2026-07-13'
related_issue_id: 419
resource_pattern: arn:aws:ecr:us-east-1:533267047935:repository/*
source: auto
status: active
type: feedback
---

Inspector: 6 Critical CVEs in ECR Image mcp-aws (glibc, openssl, go, perl)

Security Hub returned CRITICAL-severity findings surfacing Inspector CVEs from ECR image mcp-aws and EC2 instance i-0f07b14e8a09636e8 (us-east-1). These align with the Inspector findings already created. Key CVEs: CVE-2026-5450 (glibc), CVE-2026-34182 (openssl), CVE-2025-22871 / CVE-2025-68121 (go/stdlib), CVE-2026-12087 (perl), CVE-2026-39821 (golang.org/x/net). All are ACTIVE and updated 2026-07-07. Immediate patching required for both the ECR image and the EC2 instance kernel. If workloads are internet-facing, escalate to CRITICAL.

Auto-learned: issue I#419 was dismissed by user.
