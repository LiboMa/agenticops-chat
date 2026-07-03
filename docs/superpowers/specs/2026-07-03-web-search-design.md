# web_search (DuckDuckGo) — Design Spec

> Status: approved design (brainstorm complete) · Date: 2026-07-03 · Branch: `MVP-2.0.0-release`

## 1. Context

Agents can open a **known** URL via `web_fetch` (`tools/web_tools.py`, dynamically
registered by the `web-research` skill), but cannot search the open web for an
**unknown** answer (CVE lookups, error-message research, upstream incident reports).
This spec adds a `web_search` tool so agents can search → pick a result → `web_fetch`
it for depth.

Decisions locked during brainstorm:

| Decision | Choice |
|---|---|
| Implementation | httpx direct to DuckDuckGo (zero new dependencies) |
| Engine strategy | DDG dual-endpoint (lite → html fallback). No Google (YAGNI) |
| Return format | Numbered plain-text list (same style as `web_fetch`) |
| Placement | Same `web_tools.py` + declared in `web-research` skill `tools:` |

## 2. Tool interface

```python
@tool
def web_search(query: str, max_results: int = 8) -> str
```

- `query`: non-empty search string (stripped; empty → `"Error: query is empty."`)
- `max_results`: clamped to 1–20, default 8
- Never raises — all failures return `"Error: ..."` text (matches `web_fetch` contract)

Output format:

```
Query: <query>
Engine: duckduckgo

1. <title>
   <url>
   <snippet>
2. ...
```

Truncated via existing `_truncate` (4000 chars). Response body capped at
`MAX_RESPONSE_BYTES` (1 MB) before parsing.

## 3. DDG dual-endpoint fallback

| Order | Endpoint | Notes |
|---|---|---|
| 1 | `POST https://lite.duckduckgo.com/lite/` (`data={"q": query}`) | lightest HTML |
| 2 | `POST https://html.duckduckgo.com/html/` (`data={"q": query}`) | fallback when lite fails |

Fallback triggers: non-200 status, timeout/connect error, or **0 results parsed**.
Both fail → single `"Error: DuckDuckGo search failed (...): <reason>"` text naming
both attempts.

- Per-endpoint timeout 15 s (worst case 30 s total — same ceiling as `web_fetch`)
- HTTP 202/403 → treated as rate-limit: error text says "rate-limited, retry later"
- Parsing via `re` (consistent with `_strip_html` in the same file; no new parser dep)
- Search requests send a full browser-like header set (module constant
  `_SEARCH_HEADERS`) — live probing (2026-07-03) showed DDG answers bare
  clients with an HTTP 202 anomaly challenge; `web_fetch`'s UA is unchanged

### uddg link decoding

DDG result hrefs are redirect links: `//duckduckgo.com/l/?uddg=<url-encoded real URL>`.
Decode with `urllib.parse` (`urlparse` + `parse_qs` + `unquote`) and return the real
URL. Skip ad results (hrefs containing `y.js` or `ad_domain=`). Direct (non-redirect)
hrefs pass through as-is. HTML entities in titles/snippets unescaped, tags stripped,
whitespace collapsed.

## 4. Skill wiring (`skills/web-research/SKILL.md`)

- frontmatter `tools:` gains `agenticops.tools.web_tools.web_search`
- description mentions web_search (keep within the 200-char index cap; respect the
  skills-XML budget pinned by `tests/test_prompt_budget.py`)
- body: decision-tree branch "Don't know the exact URL? → `web_search` first, then
  `web_fetch` a result link"; quick-card example row; security-model note (search
  queries go to DuckDuckGo; GET/POST to DDG only)
- `skill_version: '1.0'` → `'1.1'`, bump `last_improved_at`

## 5. Prompt touches (one line each)

main / sre / detect / scan agent prompts: `activate_skill("web-research") to load
web_fetch` → `to load web_search + web_fetch`. No other prompt changes (protects
Bedrock prompt cache).

## 6. Exports + tests

- `tools/__init__.py`: import `web_search`, add to `__all__`
- Unit tests mock `httpx.Client` (no real network):
  1. lite endpoint parses titles/urls/snippets
  2. uddg redirect decoding + ad filtering
  3. lite failure → html fallback used
  4. both endpoints fail → Error text
  5. 0 results → "No results" text (not an exception)
  6. `max_results` clamping (0→1, 50→20)
  7. empty query → Error text
  8. output truncation at 4000 chars
- Regression: `test_prompt_budget.py` (skills XML budget) + existing web_tools tests

## 7. Explicitly out of scope (YAGNI)

Google (CSE API or scraping), other engines, result caching, region/time-filter
params, settings.yaml config (endpoints/timeouts are module constants, per this
file's existing convention).
