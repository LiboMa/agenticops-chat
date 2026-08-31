---
name: web-research
description: Search the open web (DuckDuckGo) and fetch public URLs — status pages,
  docs, CVE data, changelogs. Provides web_search + web_fetch tools with security
  controls (private-IP blocking, size limits, timeouts). Use when investigation needs
  external internet information and you may not know the exact URL.
metadata:
  author: agenticops
  version: '1.1'
  domain: operations
tools:
- agenticops.tools.web_tools.web_search
- agenticops.tools.web_tools.web_fetch
created_by: user
status: active
skill_version: '1.1'
created_at: '2026-06-01'
last_improved_at: '2026-07-03'
last_used: '2026-08-12'
---

# Web Research Skill

## Overview

When this skill is activated, the `web_search` and `web_fetch` tools are dynamically registered on the agent:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `web_search` | Search the web (DuckDuckGo), get titles/URLs/snippets | `query`, `max_results` (1-20, default 8) |
| `web_fetch` | Fetch public URL content | `url`, `method`, `headers` |

## Security Model

- **Allowed**: Public HTTP/HTTPS URLs only
- **Blocked**: Private IPs (10.x, 172.16.x, 192.168.x, 127.x), cloud metadata (169.254.169.254), IPv6 loopback
- **Methods**: GET and HEAD only (no POST/PUT/DELETE)
- **Limits**: 30s timeout, 1MB response, 4000 char output
- **Redirects**: Not auto-followed — agent decides whether to follow
- **Search**: queries go to DuckDuckGo only (lite/html endpoints, POST); result URLs are just text — fetching them still goes through web_fetch's private-IP blocking
- **Search limits**: 15s per endpoint (lite → html fallback), results truncated to 4000 chars

## Quick Decision Trees

### Need External Data?

```
Need information from the internet
  |
  +-- Don't know the exact URL?
  |     +-- web_search(query="<error message or topic>")
  |     +-- Then web_fetch a promising result URL for depth
  |
  +-- Cloud service status page?
  |     +-- activate_skill("web-research")
  |     +-- web_fetch(url="https://health.aws.amazon.com/health/status")
  |     +-- See references/status-pages.md for provider URLs
  |
  +-- Documentation / changelog?
  |     +-- activate_skill("web-research")
  |     +-- web_fetch(url="https://docs.aws.amazon.com/...")
  |
  +-- CVE / vulnerability info?
  |     +-- web_fetch(url="https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-XXXX")
  |     +-- Returns JSON — parse for severity, description, affected versions
  |
  +-- Public API data?
  |     +-- web_fetch(url="https://api.example.com/endpoint",
  |     |            headers='{"Accept": "application/json"}')
  |
  +-- Internal / private URL?
        +-- BLOCKED — web_fetch only works with public URLs
        +-- Use run_on_host or run_kubectl for internal data
```

### Investigating Service-Wide Issues

```
Multiple resources showing same symptoms
  |
  +-- Could be upstream provider issue?
  |     +-- Check provider status page first
  |     +-- Compare symptom timing with status page updates
  |
  +-- Need to verify a fix from upstream docs?
  |     +-- Fetch the relevant documentation page
  |     +-- Include doc reference in fix plan
  |
  +-- Need CVE details for security finding?
        +-- Fetch NVD API for CVE severity and patch info
        +-- Cross-reference with Inspector/SecurityHub findings
```

## Tool Reference Quick Card

| Example | Description |
|---------|-------------|
| `web_search(query="EKS node NotReady kubelet PLEG")` | Research an error message |
| `web_search(query="CVE-2024-3094 affected versions", max_results=5)` | Find CVE sources, then web_fetch one |
| `web_fetch(url="https://health.aws.amazon.com/health/status")` | AWS status page |
| `web_fetch(url="https://status.azure.com/en-us/status")` | Azure status |
| `web_fetch(url="https://api.github.com/repos/org/repo/releases/latest", headers='{"Accept":"application/json"}')` | GitHub latest release |
| `web_fetch(url="https://services.nvd.nist.gov/rest/json/cves/2.0?cveId=CVE-2024-1234")` | NVD CVE lookup |
| `web_fetch(url="https://example.com", method="HEAD")` | Check URL availability (headers only) |

## Output Format

- **Search results**: numbered plain-text list (title / URL / snippet) — chain into web_fetch
- **HTML pages**: Auto-converted to readable plain text (scripts/styles removed)
- **JSON APIs**: Returned as-is
- **Redirects**: Returns target URL — call again to follow
- **Errors**: Descriptive message with status code
- **All output**: Truncated to 4000 characters








