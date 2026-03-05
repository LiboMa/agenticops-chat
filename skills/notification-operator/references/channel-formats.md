# Channel Format Reference

## Format Capabilities by Channel Type

### Feishu (Lark)

- **Default format**: markdown
- **Supported**: Feishu Interactive Cards support rich markdown with headers, tables, code blocks, bold, italic, links
- **Limitations**: No inline HTML, no embedded images via notification API
- **Config keys**: `app_name`, `chat_id`

### DingTalk

- **Default format**: markdown
- **Supported**: Markdown messages with headers (h1-h6), bold, italic, links, ordered/unordered lists
- **Limitations**: No tables in markdown mode, no code blocks, no embedded images
- **Config keys**: `webhook_url`, `secret` (optional sign key)

### WeCom (WeChat Work)

- **Default format**: markdown
- **Supported**: Markdown with headers, bold, links, quoted text, code blocks
- **Limitations**: Limited markdown subset compared to standard, no tables
- **Config keys**: `webhook_url`

### Slack

- **Default format**: markdown
- **Supported**: Slack mrkdwn format — bold (*text*), italic (_text_), code, links, lists, block quotes
- **Limitations**: Non-standard markdown (uses mrkdwn), limited table support
- **Config keys**: `webhook_url`, `channel`, `username`, `icon_emoji`

### Email (SMTP)

- **Default format**: html
- **Supported**: Full HTML with inline CSS, tables, images, rich formatting
- **Limitations**: External CSS not supported by most email clients
- **Config keys**: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `from_email`, `to_emails`

### SNS (Simple Notification Service)

- **Default format**: text
- **Supported**: Plain text only via SNS email protocol
- **Limitations**: SNS email subscriptions cannot render HTML
- **Config keys**: `topic_arn`, `region`

### SNS-Report (S3 + SES/SNS)

- **Default format**: html
- **Full pipeline**: Converts reports to multiple formats (HTML, PDF, Markdown), uploads to S3, sends presigned download links
- **SES path**: When `ses_sender` and `ses_recipients` are configured, HTML report is rendered inline in email via SES
- **SNS fallback**: Without SES config, sends plain text with download links via SNS
- **Config keys**: `topic_arn`, `region`, `s3_bucket`, `s3_prefix`, `s3_region`, `url_expiry`, `formats`, `report_types`, `ses_sender`, `ses_recipients`

### Webhook

- **Default format**: markdown
- **Supported**: Sends JSON payload with subject/body to arbitrary HTTP endpoints
- **Config keys**: `url`, `method` (default: POST), `headers` (optional)

## SNS vs SES Path Explanation

```
Report Distribution
  |
  +-- sns-report channel type
        |
        +-- Has ses_sender + ses_recipients?
        |     YES --> SES HTML email (rendered in email clients)
        |             + S3 upload with presigned download links
        |
        +-- NO ses config?
              --> SNS plain text email with download links
              (SNS email protocol does not render HTML)
```

## Example Channel Configurations

```yaml
channels:
  # Feishu — markdown notifications
  sre-oncall:
    type: feishu
    enabled: true
    preferred_format: markdown
    app_name: default
    chat_id: "oc_abc123"

  # Slack — markdown alerts for critical/high severity only
  slack-critical:
    type: slack
    enabled: true
    preferred_format: markdown
    severity_filter: [critical, high]
    webhook_url: "https://hooks.slack.com/services/T.../B.../xxx"
    channel: "#critical-alerts"

  # Email — HTML reports via SMTP
  ops-email:
    type: email
    enabled: true
    preferred_format: html
    smtp_host: "smtp.example.com"
    smtp_port: 587
    smtp_user: "aiops@example.com"
    smtp_password: "${SMTP_PASSWORD}"
    from_email: "aiops@example.com"
    to_emails: ["ops@example.com", "sre@example.com"]

  # Full report pipeline with SES HTML email
  weekly-reports:
    type: sns-report
    enabled: true
    preferred_format: html
    topic_arn: "arn:aws:sns:us-east-1:123456:reports"
    region: "us-east-1"
    s3_bucket: "my-reports-bucket"
    s3_prefix: "reports/"
    formats: [html, pdf, markdown]
    report_types: [daily, incident]
    ses_sender: "reports@example.com"
    ses_recipients: ["team@example.com"]
```

## Format Conversion Matrix

| Source | Target: markdown | Target: html | Target: pdf | Target: text |
|--------|:---:|:---:|:---:|:---:|
| Report (DB) | Direct (content_markdown) | report_formatter | report_formatter | Direct (content_markdown) |
| HealthIssue | Formatted summary | N/A | N/A | Formatted summary |
| Free text | As-is | N/A | N/A | As-is |

Notes:
- `distribute_report` generates each unique format once, then dispatches to all channels needing that format
- For non-report content (text, issues, files), `send_to_channel` sends as-is without format conversion
- PDF generation requires `weasyprint` (optional dependency)
