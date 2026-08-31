---
agent: detect
confidence: 2
created_at: '2026-07-08'
created_by: user
last_confirmed: '2026-07-08'
last_used: '2026-08-26'
related_issue_id: 416
resource_pattern: i-0f07b14e8a09636e8/*
source: auto
status: active
type: feedback
---

Inspector: 50+ Critical CVEs on EC2 Instance i-0f07b14e8a09636e8 (linux-image-aws)

AWS Inspector detected more than 50 active CRITICAL severity CVEs on EC2 instance i-0f07b14e8a09636e8 (us-east-1a). The vast majority affect the linux-image-aws kernel package (examples: CVE-2026-46325, CVE-2026-43083, CVE-2026-31607, CVE-2026-43037, CVE-2026-31669, etc.). Additional CRITICAL CVEs affect the ECR image mcp-aws (glibc, go/stdlib, openssl, perl, golang.org/x/net). The instance uses SG sg-086fbb35757538f12 (litellm-ec2), which only exposes port 4000 — not directly internet-facing on sensitive ports, so keeping at medium. Recommend: apply all pending OS and package updates immediately via SSM Patch Manager or AMI replacement, and rebuild/update the ECR mcp-aws image.

Auto-learned: issue I#416 was dismissed by user.
