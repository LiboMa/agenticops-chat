---
name: document-analysis
description: "Read and analyze documents — PDF, DOCX, Markdown, HTML, CSV, XLSX, JSON, YAML. Provides read_document tool with no output truncation and page-range support for PDFs. Use when the user shares a document or asks to explain, summarize, or extract information from files."
metadata:
  author: agenticops
  version: "1.0"
  domain: operations
tools:
  - agenticops.tools.file_tools.read_document
---

# Document Analysis Skill

## Overview

When this skill is activated, the `read_document` tool is dynamically registered on the agent:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `read_document` | Read full document content (no truncation) | `path`, `pages` |

Unlike `read_local_file` (which truncates at 4K chars for operational safety), `read_document`
returns the **complete content** so you can fully understand and explain the document.

## Supported Formats

| Format | Library | Notes |
|--------|---------|-------|
| PDF | pymupdf or pypdf | Page-range support (`pages="1-5"`) |
| DOCX | python-docx | Full paragraph extraction |
| Markdown | built-in | Full content, no truncation |
| HTML | built-in | Full content, no truncation |
| CSV | built-in | Full content, no truncation |
| JSON/YAML | built-in | Full content, no truncation |
| XLSX | openpyxl | Multi-sheet, all rows |

## Quick Decision Trees

### User Shares a Document

```
User provides a document (via @path or upload)
  |
  +-- Already injected as context?
  |     +-- Yes (attached via @path or web upload) → analyze directly
  |     +-- No (user mentions a file path) → read_document(path="...")
  |
  +-- Document too large?
  |     +-- PDF: use pages="1-5" to read in chunks
  |     +-- Other: summarize what you can, note truncation
  |
  +-- What does the user want?
        +-- "Explain this" → structured summary
        +-- "Summarize" → executive summary (key points + conclusions)
        +-- "Find X in this" → targeted extraction
        +-- "Compare with Y" → side-by-side analysis
```

### Analyzing PDF Reports

```
PDF document received
  |
  +-- Large (>10 pages)?
  |     +-- Start with read_document(path, pages="1-3") for overview
  |     +-- Then read specific sections as needed
  |
  +-- What type of document?
  |     +-- Architecture/design doc → focus on components, data flow, decisions
  |     +-- Incident report → focus on timeline, root cause, remediation
  |     +-- Compliance/audit → focus on findings, risk level, recommendations
  |     +-- Cost report → focus on top spenders, trends, anomalies
  |     +-- Runbook/SOP → focus on steps, prerequisites, rollback
  |
  +-- Output format?
        +-- Brief: 3-5 bullet points
        +-- Detailed: section-by-section breakdown
        +-- Actionable: extract TODOs and next steps
```

### Analyzing Spreadsheets

```
CSV or XLSX received
  |
  +-- Understand structure first
  |     +-- Column headers, row count, data types
  |
  +-- What does the user want?
        +-- "What's in this?" → schema + sample rows + summary stats
        +-- "Find anomalies" → look for outliers, missing data, spikes
        +-- "Trends" → time-series patterns if date column exists
        +-- "Top N" → sort/rank by a metric column
```

## Analysis Workflow

### Step 1: Read the Document
```
read_document(path="/path/to/report.pdf")
# or with page range for large PDFs:
read_document(path="/path/to/report.pdf", pages="1-5")
```

### Step 2: Identify Structure
- Document type (report, spec, spreadsheet, log dump)
- Key sections / headings
- Tables, figures, or data present

### Step 3: Analyze Based on User Intent
- **Explain**: Walk through each section, clarify technical terms
- **Summarize**: Extract key findings, conclusions, action items
- **Extract**: Pull specific data points the user asked about
- **Compare**: Side-by-side with another document or known state

### Step 4: Present Findings
- Lead with the answer, not the process
- Use structured format (headers, bullets, tables)
- Quote specific passages when relevant
- Note any limitations (scanned PDF with no text, truncated content)

## Tool Reference Quick Card

| Example | Description |
|---------|-------------|
| `read_document(path="report.pdf")` | Read entire PDF |
| `read_document(path="report.pdf", pages="1-3")` | Read pages 1-3 only |
| `read_document(path="report.pdf", pages="5")` | Read page 5 only |
| `read_document(path="spec.docx")` | Read Word document |
| `read_document(path="data.csv")` | Read CSV file |
| `read_document(path="metrics.xlsx")` | Read Excel workbook |

## Edge Cases

- **Scanned PDFs** (image-only): text extraction will return empty — inform the user that OCR is needed
- **Password-protected PDFs**: will fail — ask user to provide an unprotected copy
- **Very large spreadsheets**: output is truncated to 6000 chars — suggest filtering or specifying columns of interest
- **Mixed content PDFs** (text + images): only text is extracted — note that charts/diagrams are not visible
