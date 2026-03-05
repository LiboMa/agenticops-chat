---
name: notification-operator
description: "Send notifications and distribute formatted reports to channels (Feishu, Slack, Email, SES, SNS, DingTalk, WeCom, Webhook). Supports batch multi-channel delivery with format-aware conversion (HTML, PDF, Markdown). Activate to gain send and distribute tools."
metadata:
  author: agenticops
  version: "1.0"
  domain: operations
tools:
  - agenticops.tools.notification_tools.list_notification_channels
  - agenticops.tools.notification_tools.send_to_channel
  - agenticops.tools.notification_tools.distribute_report
---

# Notification Operator Skill

## Overview

Provides tools for sending notifications and distributing formatted reports across
multiple channels. When activated, 3 tools are dynamically registered on the agent:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `list_notification_channels` | Discover channels with format preferences | (none) |
| `send_to_channel` | Send text/report/issue/file to one channel | `target_name`, `content`, `content_type` |
| `distribute_report` | Batch format-aware report distribution | `report_id`, `channel_names`, `severity` |

## Decision Trees

### When to Send a Message vs Distribute a Report

```
Need to notify about something
  |
  +-- Is the content a saved Report (has Report ID)?
  |     |
  |     +-- Send to ONE channel? --> send_to_channel(target_name, report_id, content_type="report")
  |     |
  |     +-- Send to MULTIPLE channels with format conversion?
  |           --> distribute_report(report_id, channel_names="ch1,ch2,ch3")
  |
  +-- Is the content a text message (alert, summary, status)?
  |     --> send_to_channel(target_name, "message text", content_type="text")
  |
  +-- Is the content a HealthIssue?
  |     --> send_to_channel(target_name, issue_id, content_type="issue")
  |
  +-- Is the content a LocalDoc file?
        --> send_to_channel(target_name, doc_id, content_type="file")
```

### Selecting Target Channels

```
Which channels should receive this notification?
  |
  +-- All enabled channels?
  |     --> distribute_report(report_id)  (empty channel_names = all enabled)
  |
  +-- Specific channels by name?
  |     --> distribute_report(report_id, channel_names="slack-alerts,ops-email")
  |
  +-- Filter by severity?
  |     --> distribute_report(report_id, severity="critical")
  |     Channels with severity_filter will only receive if severity matches.
  |
  +-- Don't know which channels exist?
        --> list_notification_channels() first, then decide
```

### Format Selection

Each channel has a `preferred_format` that determines how content is rendered:

| Channel Type | Default Format | Reason |
|---|---|---|
| feishu | markdown | Feishu card renders markdown natively |
| dingtalk | markdown | DingTalk message body supports markdown |
| wecom | markdown | WeCom textcard supports markdown |
| slack | markdown | Slack mrkdwn format |
| email | html | Email clients render HTML |
| sns | text | SNS email protocol = plain text only |
| sns-report | html | SES sends HTML email; S3 stores formatted files |
| webhook | markdown | Generic payload, markdown is portable |

`distribute_report` handles format conversion automatically:
1. Groups channels by preferred_format
2. Generates each unique format ONCE (efficient batch conversion)
3. Dispatches the right format to each channel

## Common Workflows

### Post-RCA Notification

After completing root cause analysis, notify the on-call team:

```
1. list_notification_channels()   -- discover available channels
2. send_to_channel(
     target_name="sre-oncall",
     content="RCA complete for Issue #42: Root cause is memory leak in cartservice. Fix plan L1 ready.",
     content_type="text"
   )
```

### Post-Execution Summary

After executing a fix, send the result:

```
1. send_to_channel(
     target_name="ops-slack",
     content="42",           -- HealthIssue ID
     content_type="issue"    -- sends formatted issue summary with RCA
   )
```

### Report Distribution

After generating a report, distribute to all channels:

```
1. list_notification_channels()   -- check which channels are available
2. distribute_report(
     report_id="15",
     channel_names="",           -- empty = all enabled channels
     severity=""                 -- no severity filter
   )
```

### Targeted Report Distribution

Send a critical incident report only to high-severity channels:

```
1. distribute_report(
     report_id="15",
     channel_names="slack-critical,ops-email,feishu-oncall",
     severity="critical"
   )
```

## Tool Reference Quick Card

| Tool | Example | Returns |
|------|---------|---------|
| `list_notification_channels` | `list_notification_channels()` | JSON: channels with format/severity info |
| `send_to_channel` | `send_to_channel(target_name="slack", content="Alert!", content_type="text")` | JSON: {success, message} |
| `send_to_channel` | `send_to_channel(target_name="email", content="15", content_type="report")` | JSON: {success, message} |
| `distribute_report` | `distribute_report(report_id="15")` | JSON: {success, results per channel} |
| `distribute_report` | `distribute_report(report_id="15", channel_names="a,b", severity="high")` | JSON: {success, results per channel} |
