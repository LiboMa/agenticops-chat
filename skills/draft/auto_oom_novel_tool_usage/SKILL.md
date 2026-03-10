---
name: auto_oom_novel_tool_usage
description: "Auto-generated skill for oom (novel_tool_usage)"
---

# oom Troubleshooting

## Root Cause Pattern
Memory leak in checkout-service caused OOM kills

## Evidence
- Memory usage 95% before OOM
- Deployment v2.3 at 14:00

## Recommendations
- Set memory limits to 512Mi
- Fix leak in v2.4
