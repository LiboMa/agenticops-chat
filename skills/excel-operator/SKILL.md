---
name: excel-operator
description: Generate and programmatically parse Excel/XLSX files — styled reports,
  multi-sheet workbooks, charts, formulas, conditional formatting, plus advanced parsing
  (cell ranges, merged cells, formula extraction, typed records, large-file streaming).
  For basic 'read this spreadsheet' use document-analysis instead.
metadata:
  author: agenticops
  version: '1.0'
  domain: operations
  tags:
  - excel
  - xlsx
  - openpyxl
  - pandas
  - xlsxwriter
  - reporting
  - generation
  - parsing
created_by: user
status: active
skill_version: '1.0'
created_at: '2026-07-10'
last_used: '2026-07-10'
---

# Excel Operator Skill

## Overview

This skill covers **generating** Excel (.xlsx) files and **advanced/programmatic parsing** of
them — the two things `read_document` cannot do.

**Division of labor with `document-analysis`:**

| Need | Use |
|------|-----|
| "Read/summarize/explain this spreadsheet" | `document-analysis` → `read_document(path)` (dumps all sheets as text) |
| Generate a .xlsx report (styling, charts, formulas, multi-sheet) | **this skill** |
| Parse a specific sheet/range into structured records | **this skill** |
| Extract formulas, handle merged cells, detect types, stream huge files | **this skill** |

Typical ops use cases: cost/usage reports for finance, EC2/RDS inventory exports, health-issue
summaries with severity color scales, patrol trend charts, parsing customer-provided capacity
plans or billing exports.

All snippets run with the project venv (`.venv/bin/python3`). Required libraries:
`openpyxl` (read+write), `pandas` (tabular), `xlsxwriter` (write-only). Write generated files
to a workspace path (e.g. `reports/` or `/tmp`), never over a user's source file.

## Library Decision Tree

```
Task with .xlsx
  |
  +-- WRITING a file?
  |     +-- Need to also READ or edit an existing .xlsx?        --> openpyxl (only lib that edits in place)
  |     +-- Data already in a DataFrame / needs groupby-pivot?  --> pandas.to_excel (engine=openpyxl or xlsxwriter)
  |     +-- Very large output (100k+ rows) or rich charts,
  |     |   write-once, never re-read for editing?              --> xlsxwriter (fast, constant_memory)
  |     +-- Everything else (styled report, formulas, merges)   --> openpyxl
  |
  +-- READING a file?
        +-- Whole sheets into tabular data for analysis?        --> pandas.read_excel
        +-- Specific ranges / formulas / merged cells / styles? --> openpyxl
        +-- Huge file (100k+ rows), bounded memory?             --> openpyxl read_only=True (streaming)
```

Rules of thumb:
- **xlsxwriter cannot read or modify** files — write-only, but the fastest writer and best chart API.
- **pandas** delegates to an engine (`openpyxl` to read/write, optionally `xlsxwriter` to write);
  use it when the unit of work is a table, not a cell.
- **openpyxl** is the only choice for round-trip edit (open → modify → save).

## Generation

### 1. Workbook with styled headers

```python
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment

wb = Workbook()
ws = wb.active
ws.title = "EC2 Inventory"

headers = ["Instance ID", "Type", "Region", "State", "Monthly Cost (USD)"]
rows = [
    ["i-0abc123", "m5.xlarge", "us-east-1", "running", 140.16],
    ["i-0def456", "t3.medium", "ap-southeast-1", "stopped", 0.0],
]

header_fill = PatternFill("solid", start_color="1F4E79")
header_font = Font(bold=True, color="FFFFFF", size=11)
thin = Side(style="thin", color="B0B0B0")
border = Border(left=thin, right=thin, top=thin, bottom=thin)

ws.append(headers)
for cell in ws[1]:
    cell.fill = header_fill
    cell.font = header_font
    cell.alignment = Alignment(horizontal="center")
    cell.border = border

for row in rows:
    ws.append(row)

# Number format on the cost column (E), skipping the header
for cell in ws["E"][1:]:
    cell.number_format = '"$"#,##0.00'

wb.save("/tmp/ec2_inventory.xlsx")
```

Common `number_format` strings: `'#,##0'`, `'#,##0.00'`, `'0.0%'`, `'"$"#,##0.00'`,
`'yyyy-mm-dd'`, `'yyyy-mm-dd hh:mm:ss'`.

### 2. DataFrame → Excel with formatting

Use `pd.ExcelWriter` with the xlsxwriter engine when you want formats applied per-column in one pass:

```python
import pandas as pd

df = pd.DataFrame({
    "service": ["EC2", "RDS", "S3"],
    "cost_usd": [1234.56, 890.12, 45.03],
    "delta_pct": [0.12, -0.05, 0.31],
})

with pd.ExcelWriter("/tmp/cost_report.xlsx", engine="xlsxwriter") as writer:
    df.to_excel(writer, sheet_name="Costs", index=False, startrow=1, header=False)
    wb, ws = writer.book, writer.sheets["Costs"]

    header_fmt = wb.add_format({"bold": True, "bg_color": "#1F4E79",
                                "font_color": "white", "border": 1})
    money_fmt = wb.add_format({"num_format": "$#,##0.00"})
    pct_fmt = wb.add_format({"num_format": "0.0%"})

    for col, name in enumerate(df.columns):
        ws.write(0, col, name, header_fmt)
    ws.set_column("A:A", 14)              # width only
    ws.set_column("B:B", 12, money_fmt)   # width + format
    ws.set_column("C:C", 10, pct_fmt)
```

### 3. Multi-sheet report

```python
with pd.ExcelWriter("/tmp/monthly_report.xlsx", engine="openpyxl") as writer:
    summary_df.to_excel(writer, sheet_name="Summary", index=False)
    by_service_df.to_excel(writer, sheet_name="By Service", index=False)
    by_account_df.to_excel(writer, sheet_name="By Account", index=False)
```

To append a sheet to an **existing** file: `pd.ExcelWriter(path, engine="openpyxl", mode="a", if_sheet_exists="replace")`.

### 4. Formulas, merged cells, frozen panes, column widths

```python
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active

ws.merge_cells("A1:C1")                       # title banner across 3 columns
ws["A1"] = "AWS Cost Summary — 2026-07"

ws.append(["Service", "Jun", "Jul"])
ws.append(["EC2", 1200, 1350])
ws.append(["RDS", 800, 790])

ws["B5"] = "=SUM(B3:B4)"                      # plain string starting with '=' is a formula
ws["C5"] = "=SUM(C3:C4)"
ws["A5"] = "Total"

ws.freeze_panes = "A3"                        # rows 1-2 stay visible when scrolling

for i, width in enumerate([16, 12, 12], start=1):
    ws.column_dimensions[get_column_letter(i)].width = width

wb.save("/tmp/summary.xlsx")
```

Notes on merges: write the value to the **top-left** cell only; writing to any other cell in
the merged range raises. openpyxl never *computes* formulas — Excel will on open.

### 5. Conditional formatting

```python
from openpyxl.formatting.rule import ColorScaleRule, CellIsRule

# 3-color scale on utilization (green → yellow → red)
ws.conditional_formatting.add(
    "B2:B100",
    ColorScaleRule(start_type="num", start_value=0,   start_color="63BE7B",
                   mid_type="num",   mid_value=70,    mid_color="FFEB84",
                   end_type="num",   end_value=100,   end_color="F8696B"),
)

# Red fill when cost > 1000
from openpyxl.styles import PatternFill
red = PatternFill("solid", start_color="FFC7CE")
ws.conditional_formatting.add(
    "C2:C100",
    CellIsRule(operator="greaterThan", formula=["1000"], fill=red),
)
```

xlsxwriter equivalent: `ws.conditional_format("B2:B100", {"type": "3_color_scale"})`.

### 6. Embedded charts (bar / line / pie)

```python
from openpyxl.chart import BarChart, LineChart, PieChart, Reference

# Data laid out as: A=labels, B..=series, row 1 = headers
data = Reference(ws, min_col=2, min_row=1, max_col=3, max_row=5)   # includes header row
cats = Reference(ws, min_col=1, min_row=2, max_row=5)              # labels, no header

bar = BarChart()
bar.title = "Cost by Service"
bar.add_data(data, titles_from_data=True)   # header row becomes series names
bar.set_categories(cats)
ws.add_chart(bar, "E2")                     # anchor = top-left cell of the chart

line = LineChart(); line.add_data(data, titles_from_data=True); line.set_categories(cats)
ws.add_chart(line, "E18")

pie = PieChart()
pie.add_data(Reference(ws, min_col=2, min_row=1, max_row=5), titles_from_data=True)
pie.set_categories(cats)
ws.add_chart(pie, "E34")
```

For polished dashboards with many charts prefer xlsxwriter (`wb.add_chart({"type": "column"})`)
— richer options (trendlines, secondary axes, combined charts).

### 7. Streaming large files (write)

```python
# openpyxl write_only: constant memory, append-only, style via WriteOnlyCell
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Font

wb = Workbook(write_only=True)
ws = wb.create_sheet("Data")            # write_only has NO default active sheet

header = [WriteOnlyCell(ws, value=h) for h in ("timestamp", "instance", "cpu_pct")]
for c in header:
    c.font = Font(bold=True)
ws.append(header)

for rec in generate_records():          # any iterator — nothing is held in memory
    ws.append([rec["ts"], rec["id"], rec["cpu"]])

wb.save("/tmp/metrics_dump.xlsx")       # save() exactly once; file can't be reopened for append
```

xlsxwriter equivalent: `xlsxwriter.Workbook(path, {"constant_memory": True})` — rows must then
be written in order, and only `ws.write(row, col, ...)` style access works.

## Parsing

### 1. Specific sheet + cell range → records

```python
from openpyxl import load_workbook

wb = load_workbook("/tmp/ec2_inventory.xlsx", data_only=True)
ws = wb["EC2 Inventory"]                # by name; wb.sheetnames lists all

cells = ws["A1:D20"]                    # tuple of row-tuples of Cell objects
header = [c.value for c in cells[0]]
records = [
    dict(zip(header, (c.value for c in row)))
    for row in cells[1:]
    if any(c.value is not None for c in row)   # skip fully-empty rows
]
wb.close()
```

pandas equivalent for a rectangular block:
`pd.read_excel(path, sheet_name="EC2 Inventory", usecols="A:D", skiprows=0, nrows=19)`.

### 2. Merged cells

Only the **top-left** cell of a merged range holds the value; the rest read as `None`.
To flatten for tabular processing, back-fill each range:

```python
wb = load_workbook(path)                          # merges need a normal (non read_only) load
ws = wb.active
for rng in list(ws.merged_cells.ranges):          # copy — unmerge mutates the set
    value = ws.cell(rng.min_row, rng.min_col).value
    ws.unmerge_cells(str(rng))
    for row in ws[rng.coord]:
        for cell in row:
            cell.value = value
```

### 3. Formulas vs computed values

```python
wb_f = load_workbook(path)                  # data_only=False (default): cell.value == "=SUM(B2:B9)"
wb_v = load_workbook(path, data_only=True)  # cell.value == cached RESULT of the formula
```

Caveats:
- `data_only=True` returns the value **cached by Excel at last save**. If the file was created
  programmatically and never opened in Excel, formula cells read as `None`. openpyxl never evaluates.
- To detect a formula: `cell.data_type == "f"` (or `isinstance(cell.value, str) and cell.value.startswith("=")`).
- Saving a workbook loaded with `data_only=True` **discards all formulas** (values replace them).

### 4. Iterating with type detection

```python
import datetime as dt

wb = load_workbook(path, data_only=True)
ws = wb.active
for row in ws.iter_rows(min_row=2):                 # Cell objects (need .number_format etc.)
    for cell in row:
        v = cell.value
        if v is None:                       kind = "empty"
        elif isinstance(v, bool):           kind = "bool"      # check BEFORE int (bool ⊂ int)
        elif isinstance(v, (int, float)):   kind = "number"
        elif isinstance(v, dt.datetime):    kind = "datetime"  # openpyxl converts date cells
        else:                               kind = "text"
```

Use `ws.iter_rows(values_only=True)` when you only need values (much faster, yields tuples).
Column-wise: `ws.iter_cols(...)` (unavailable in `read_only` mode).

### 5. Convert to JSON / CSV / dict-of-records

```python
import pandas as pd

df = pd.read_excel(path, sheet_name="Costs")          # engine=openpyxl automatically
records = df.to_dict(orient="records")                # list[dict] — feed to the agent/API
df.to_json("/tmp/out.json", orient="records", date_format="iso")
df.to_csv("/tmp/out.csv", index=False)

all_sheets = pd.read_excel(path, sheet_name=None)     # dict {sheet_name: DataFrame}
```

### 6. Large files (read)

`pd.read_excel` has **no `chunksize`** — pick one of:

```python
# A) openpyxl read_only: true streaming, constant memory
wb = load_workbook(big_path, read_only=True, data_only=True)
ws = wb["Data"]
rows = ws.iter_rows(values_only=True)
header = next(rows)
for row in rows:
    process(dict(zip(header, row)))
wb.close()                                # REQUIRED in read_only mode (releases the file handle)

# B) pandas batching via skiprows/nrows (re-opens the file each batch — fine for a few passes)
CHUNK, start = 10_000, 1
header = pd.read_excel(big_path, nrows=0).columns
while True:
    chunk = pd.read_excel(big_path, skiprows=range(1, start), nrows=CHUNK, header=0)
    if chunk.empty:
        break
    chunk.columns = header
    process(chunk)
    start += CHUNK
```

Prefer (A) for one linear pass; convert to CSV/Parquet first if you need many passes.
In `read_only` mode, `ws.max_row`/`max_column` may be `None` or stale — iterate instead of indexing.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `zipfile.BadZipFile: File is not a zip file` | Not a real .xlsx (old .xls binary, CSV/HTML renamed to .xlsx, truncated download) | `head -c 8 file` — `PK` = real xlsx; `\xd0\xcf\x11\xe0` = old .xls → `pip install xlrd`, `pd.read_excel(engine="xlrd")`; `<html`/plain text → parse as HTML/CSV |
| `InvalidFileException: openpyxl does not support .xls` | Legacy BIFF format | Same as above — xlrd for .xls, or ask for a re-export |
| Garbled text (mojibake) in values | File is actually CSV with non-UTF-8 encoding, mislabeled | `pd.read_csv(path, encoding="gbk")` (or `cp1252`, `shift_jis`); true .xlsx is always UTF-8 internally — mojibake there was baked in at creation |
| `MemoryError` / OOM on load | Full DOM load of a huge sheet | `read_only=True` streaming (Parsing §6); for writes use `write_only=True` or xlsxwriter `constant_memory` |
| Formula cells read as `None` with `data_only=True` | File never opened/saved by Excel, so no cached values | Read with `data_only=False` and get the formula strings, compute in Python, or open once in Excel/LibreOffice (`soffice --headless --convert-to xlsx`) to populate the cache |
| Dates come back as `44927` (a number) | Cell stored as number without a date format | `from openpyxl.utils.datetime import from_excel; from_excel(44927)`; watch the rare 1904 epoch (`wb.epoch`) on Mac-authored files |
| Dates come back as strings `"2026-07-01"` | Cell is text, not a date | `pd.to_datetime(df[col])` after load |
| Numbers come back as strings `"1,234.56"` | Text cells with locale separators | `df[col].str.replace(",", "").astype(float)` |
| Values missing under merged headers | Only top-left of a merge has the value | Back-fill pattern (Parsing §2), or `df.ffill()` after `read_excel` for merged row-label columns |
| `AttributeError: 'MergedCell' object attribute 'value' is read-only` | Writing into a merged region | Write to the range's top-left cell, or unmerge first |
| Saved file drops formulas | Workbook was loaded with `data_only=True` then saved | Reload with `data_only=False` for edits |
| Sheet appears empty in `read_only` mode | Stale dimensions metadata | `ws.reset_dimensions()` then iterate, or `ws.calculate_dimension(force=True)` |

## Cheat Sheet

```python
# --- write ---
from openpyxl import Workbook, load_workbook
wb = Workbook(); ws = wb.active                         # new
wb = load_workbook(p)                                   # edit existing (round-trip)
wb = Workbook(write_only=True)                          # stream-write big files
ws.append([...]); ws["A1"] = v; ws.cell(r, c, v)
ws.merge_cells("A1:C1"); ws.freeze_panes = "A2"
ws.column_dimensions["A"].width = 18
cell.number_format = '"$"#,##0.00'
wb.save(p)

# --- read ---
wb = load_workbook(p, data_only=True)                   # computed values
wb = load_workbook(p, read_only=True)                   # stream big files; wb.close() after
wb.sheetnames; ws = wb["Sheet1"]
ws["A1:D20"]                                            # range of Cell tuples
ws.iter_rows(min_row=2, values_only=True)               # fast tuples
ws.merged_cells.ranges                                  # merge map

# --- pandas ---
pd.read_excel(p, sheet_name="S", usecols="A:D", nrows=100)
pd.read_excel(p, sheet_name=None)                       # all sheets → dict
df.to_excel(p, sheet_name="S", index=False)
with pd.ExcelWriter(p, engine="xlsxwriter") as w: ...   # formatted export
with pd.ExcelWriter(p, engine="openpyxl", mode="a", if_sheet_exists="replace") as w: ...
df.to_dict(orient="records"); df.to_json(orient="records"); df.to_csv(index=False)

# --- xlsxwriter ---
import xlsxwriter
wb = xlsxwriter.Workbook(p, {"constant_memory": True})  # write-only, huge files
fmt = wb.add_format({"bold": True, "num_format": "$#,##0.00", "bg_color": "#1F4E79"})
ws = wb.add_worksheet("S"); ws.write(0, 0, "x", fmt); ws.set_column("A:A", 18, fmt)
chart = wb.add_chart({"type": "column"})                # or "line", "pie"
chart.add_series({"categories": "=S!$A$2:$A$9", "values": "=S!$B$2:$B$9"})
ws.insert_chart("E2", chart); wb.close()

# --- sanity checks ---
head -c 8 file.xlsx        # PK.. = real xlsx ; \xd0\xcf.. = legacy .xls ; <htm = fake
python3 -c "import openpyxl, pandas, xlsxwriter"        # deps present?
```
