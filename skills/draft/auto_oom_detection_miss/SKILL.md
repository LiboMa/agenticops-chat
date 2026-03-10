---
name: auto_oom_detection_miss
description: "Auto-generated skill for oom (detection_miss)"
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
