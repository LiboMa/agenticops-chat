# web_search (DuckDuckGo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `web_search` tool (DuckDuckGo, zero new dependencies) to `web_tools.py`, wired into the `web-research` skill, so agents can search the open web and chain into `web_fetch`.

**Architecture:** One new `@tool web_search(query, max_results=8)` in the existing `src/agenticops/tools/web_tools.py`, POSTing to DDG's `lite` endpoint with `html` endpoint fallback, regex-parsed (no new parser dep), returning a numbered plain-text list in the same never-raise style as `web_fetch`. Registered dynamically via the `web-research` skill's frontmatter `tools:` list.

**Tech Stack:** Python 3.12, httpx (already a dependency), `re` + `urllib.parse` + `html.unescape` (stdlib), pytest with `unittest.mock` (no real network in tests), Strands `@tool` decorator.

**Spec:** `docs/superpowers/specs/2026-07-03-web-search-design.md`

## Global Constraints

- Zero new dependencies — httpx/stdlib only.
- `web_search` NEVER raises — every failure returns a `"Error: ..."` (or `"No results found for: ..."`) string, matching `web_fetch`'s contract.
- Output truncated via the existing `_truncate` (4000 chars); response body capped at existing `MAX_RESPONSE_BYTES` (1 MB).
- `max_results` clamped to 1–20, default 8.
- DDG endpoints, timeout (15 s/endpoint), and headers are module constants — NO settings.yaml config (YAGNI, per spec §7).
- **Empirical fact (probed 2026-07-03):** DDG answers bare clients with HTTP 202 + anomaly/bot-challenge page; a full browser-like header set gets HTTP 200 with results. The search POST must send `_SEARCH_HEADERS` (full set below), NOT just a User-Agent. `web_fetch`'s `AgenticOps/1.0` UA is unchanged.
- Real lite-endpoint markup (from probe): `<a rel="nofollow" href="https://..." class='result-link'>Title</a>` — note SINGLE quotes on class; snippets in `<td class='result-snippet'>...</td>` spanning lines with nested `<b>` tags. html endpoint uses `class="result__a"` / `class="result__snippet"` and uddg redirect hrefs. Parser must accept both quote styles and both class families.
- Don't touch unrelated code (existing `_strip_html`, `web_fetch`, its UA, etc.).
- Tests mock `httpx.Client` — no real network. Follow the existing mock pattern in `tests/test_web_tools.py` (patch `agenticops.tools.web_tools.httpx.Client`, wire `__enter__`/`__exit__`).
- Commit after each task (tests green first). **NO `git push`** — owner confirms after final E2E (per project rule).
- All commits end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Parsing layer — `_clean_text`, `_decode_ddg_href`, `_parse_ddg_results`

**Files:**
- Modify: `src/agenticops/tools/web_tools.py` (imports + new helpers after `_strip_html`, before `@tool web_fetch`)
- Test: `tests/test_web_tools.py` (append new test classes)

**Interfaces:**
- Consumes: nothing new (stdlib + existing module constants).
- Produces (Task 2 relies on these exact signatures):
  - `_clean_text(fragment: str) -> str` — strip tags, unescape ALL HTML entities, collapse whitespace.
  - `_decode_ddg_href(href: str) -> str | None` — resolve a DDG result href to the real target URL; `None` for ads/internal/invalid links.
  - `_parse_ddg_results(html_text: str, limit: int) -> list[dict]` — dicts with keys `title`, `url`, `snippet` (all str), at most `limit` items.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_tools.py`:

```python
# ── web_search parsing layer ──────────────────────────────────────────

from agenticops.tools.web_tools import (  # noqa: E402
    _clean_text,
    _decode_ddg_href,
    _parse_ddg_results,
)

# Modeled on REAL lite-endpoint markup probed 2026-07-03:
# single-quoted class='result-link', entities in titles, multiline
# snippets with nested <b> tags, direct + uddg + ad hrefs mixed.
LITE_HTML = """
<html><body><table>
<tr><td>1.</td><td>
<a rel="nofollow" href="https://www.shellhacks.com/kubernetes-node-notready/" class='result-link'>Kubernetes: Node &#x27;NotReady&#x27; [SOLVED]</a>
</td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>
How to troubleshoot the <b>Kubernetes</b> node
NotReady state.
</td></tr>
<tr><td>2.</td><td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.aws.amazon.com%2Feks%2Ftroubleshooting&rut=abc123" class='result-link'>EKS troubleshooting - AWS Docs</a>
</td></tr>
<tr><td>&nbsp;</td><td class='result-snippet'>Official AWS guidance.</td></tr>
<tr><td>3.</td><td>
<a rel="nofollow" href="https://duckduckgo.com/y.js?ad_domain=ads.example.com&u3=xyz" class='result-link'>Sponsored result</a>
</td></tr>
</table></body></html>
"""

# html.duckduckgo.com/html markup: double-quoted result__a + uddg hrefs.
HTML_ENDPOINT_HTML = """
<div class="result">
<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=x">Example Page</a>
<a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=x">Snippet <b>text</b> here.</a>
</div>
"""


class TestCleanText:
    def test_strips_tags_entities_whitespace(self):
        assert _clean_text("  <b>Node</b> &#x27;NotReady&#x27;\n   fix ") == "Node 'NotReady' fix"


class TestDecodeDdgHref:
    def test_direct_url_passthrough(self):
        assert _decode_ddg_href("https://example.com/a") == "https://example.com/a"

    def test_uddg_redirect_decoded(self):
        href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.aws.amazon.com%2Feks&rut=abc"
        assert _decode_ddg_href(href) == "https://docs.aws.amazon.com/eks"

    def test_ad_link_skipped(self):
        assert _decode_ddg_href("https://duckduckgo.com/y.js?ad_domain=ads.example.com") is None

    def test_internal_relative_link_skipped(self):
        assert _decode_ddg_href("/lite/?q=next+page") is None

    def test_ddg_non_redirect_internal_skipped(self):
        assert _decode_ddg_href("https://duckduckgo.com/about") is None

    def test_non_http_scheme_skipped(self):
        assert _decode_ddg_href("javascript:void(0)") is None


class TestParseDdgResults:
    def test_lite_markup_parsed(self):
        results = _parse_ddg_results(LITE_HTML, limit=10)
        assert len(results) == 2  # ad filtered out
        assert results[0]["title"] == "Kubernetes: Node 'NotReady' [SOLVED]"
        assert results[0]["url"] == "https://www.shellhacks.com/kubernetes-node-notready/"
        assert results[0]["snippet"] == "How to troubleshoot the Kubernetes node NotReady state."
        assert results[1]["url"] == "https://docs.aws.amazon.com/eks/troubleshooting"

    def test_html_endpoint_markup_parsed(self):
        results = _parse_ddg_results(HTML_ENDPOINT_HTML, limit=10)
        assert len(results) == 1
        assert results[0]["title"] == "Example Page"
        assert results[0]["url"] == "https://example.com/page"
        assert results[0]["snippet"] == "Snippet text here."

    def test_limit_respected(self):
        many = "".join(
            f'<a href="https://ex.com/{i}" class="result-link">R{i}</a>' for i in range(25)
        )
        assert len(_parse_ddg_results(many, limit=20)) == 20

    def test_no_results_empty_list(self):
        assert _parse_ddg_results("<html><body>challenge</body></html>", limit=5) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/malibo/MyDev/AgenticOps && .venv/bin/python -m pytest tests/test_web_tools.py -q 2>&1 | tail -5`
Expected: ImportError — `cannot import name '_clean_text'`.

- [ ] **Step 3: Implement the parsing layer**

In `src/agenticops/tools/web_tools.py`:

(a) Change the imports line `from urllib.parse import urlparse` to:

```python
from html import unescape
from urllib.parse import parse_qs, urlparse
```

(keep import order/grouping: `from html import unescape` goes with stdlib imports, alphabetical — after `import socket`, before `from urllib.parse ...`.)

(b) After the `_strip_html` function (line ~97) and before `@tool web_fetch`, add:

```python
# ── DuckDuckGo search ─────────────────────────────────────────────────
SEARCH_TIMEOUT_SECONDS = 15
MAX_SEARCH_RESULTS = 20
DEFAULT_SEARCH_RESULTS = 8

_DDG_ENDPOINTS = (
    "https://lite.duckduckgo.com/lite/",
    "https://html.duckduckgo.com/html/",
)

# DDG answers bare clients with an anomaly/bot challenge (HTTP 202), so the
# search POST must look like a real browser form submit — full header set,
# not just a User-Agent. (web_fetch keeps its own AgenticOps/1.0 UA.)
_SEARCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/x-www-form-urlencoded",
}

_NO_RESULTS = "no results parsed"

# Result anchors: lite uses class='result-link', html uses class="result__a"
# (quote style varies). Group 1 = full attribute string, group 2 = title HTML.
_RESULT_A_RE = re.compile(
    r"<a\s+([^>]*class=['\"]result(?:-link|__a)['\"][^>]*)>(.*?)</a>",
    re.DOTALL | re.IGNORECASE,
)
_HREF_RE = re.compile(r"href=['\"]([^'\"]+)['\"]", re.IGNORECASE)
_SNIPPET_RE = re.compile(
    r"<(?:td|a|div)[^>]*class=['\"]result(?:-snippet|__snippet)['\"][^>]*>(.*?)</(?:td|a|div)>",
    re.DOTALL | re.IGNORECASE,
)


def _clean_text(fragment: str) -> str:
    """Strip tags, decode HTML entities, and collapse whitespace."""
    text = re.sub(r"<[^>]+>", "", fragment)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_ddg_href(href: str) -> str | None:
    """Resolve a DDG result href to the real target URL.

    DDG wraps results in redirect links (//duckduckgo.com/l/?uddg=<encoded>).
    Returns None for ad links (y.js / ad_domain), DDG-internal links, and
    anything that isn't a plain http(s) URL.
    """
    href = href.strip()
    if "y.js" in href or "ad_domain=" in href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        return None  # relative DDG-internal link (pagination etc.)
    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if parsed.hostname.endswith("duckduckgo.com"):
        if parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [None])[0]
            if target and target.startswith(("http://", "https://")):
                return target
        return None
    return href


def _parse_ddg_results(html_text: str, limit: int) -> list[dict]:
    """Extract [{title, url, snippet}] from DDG lite/html result markup."""
    results: list[dict] = []
    matches = list(_RESULT_A_RE.finditer(html_text))
    for i, match in enumerate(matches):
        href_match = _HREF_RE.search(match.group(1))
        if not href_match:
            continue
        url = _decode_ddg_href(href_match.group(1))
        if not url:
            continue
        # Snippet lives between this anchor and the next result anchor.
        seg_end = matches[i + 1].start() if i + 1 < len(matches) else len(html_text)
        snippet_match = _SNIPPET_RE.search(html_text, match.end(), seg_end)
        results.append({
            "title": _clean_text(match.group(2)),
            "url": url,
            "snippet": _clean_text(snippet_match.group(1)) if snippet_match else "",
        })
        if len(results) >= limit:
            break
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_tools.py -q 2>&1 | tail -3`
Expected: all pass (existing + 12 new).

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/tools/web_tools.py tests/test_web_tools.py
git commit --no-verify -m "feat(web): DDG result parsing layer for web_search

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `web_search` tool + endpoint fallback + exports

**Files:**
- Modify: `src/agenticops/tools/web_tools.py` (after `_parse_ddg_results`)
- Modify: `src/agenticops/tools/__init__.py` (line ~66 import, `__all__` "Web tools" section)
- Modify: `docs/superpowers/specs/2026-07-03-web-search-design.md` (one line — spec said single UA constant; probe showed full header set required)
- Test: `tests/test_web_tools.py`

**Interfaces:**
- Consumes: Task 1's `_parse_ddg_results`, existing `_truncate`, `MAX_RESPONSE_BYTES`.
- Produces: `web_search(query: str, max_results: int = 8) -> str` (Strands `@tool`), importable as `from agenticops.tools import web_search`. Skill wiring (Task 3) references dotted path `agenticops.tools.web_tools.web_search`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web_tools.py`:

```python
from agenticops.tools.web_tools import web_search  # noqa: E402


def _search_resp(status=200, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.content = text.encode()
    return resp


def _wire_client(mock_client_cls, side_effect):
    """Wire mocked httpx.Client context manager; side_effect drives .post()."""
    inst = MagicMock()
    inst.post = MagicMock(side_effect=side_effect)
    mock_client_cls.return_value.__enter__ = MagicMock(return_value=inst)
    mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
    return inst


class TestWebSearch:
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_lite_success(self, mock_client_cls):
        inst = _wire_client(mock_client_cls, [_search_resp(200, LITE_HTML)])
        out = web_search(query="kubernetes node notready")
        assert "Engine: duckduckgo" in out
        assert "1. Kubernetes: Node 'NotReady' [SOLVED]" in out
        assert "https://www.shellhacks.com/kubernetes-node-notready/" in out
        assert "https://docs.aws.amazon.com/eks/troubleshooting" in out
        assert "Sponsored" not in out  # ad filtered
        assert inst.post.call_count == 1  # lite sufficed, no fallback

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_lite_challenge_falls_back_to_html(self, mock_client_cls):
        inst = _wire_client(mock_client_cls, [
            _search_resp(202, "challenge"),
            _search_resp(200, HTML_ENDPOINT_HTML),
        ])
        out = web_search(query="anything")
        assert "Example Page" in out
        assert inst.post.call_count == 2

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_both_endpoints_fail(self, mock_client_cls):
        _wire_client(mock_client_cls, [
            _search_resp(202, "challenge"),
            httpx.ConnectTimeout("boom"),
        ])
        out = web_search(query="anything")
        assert out.startswith("Error: DuckDuckGo search failed")
        assert "lite.duckduckgo.com" in out and "html.duckduckgo.com" in out
        assert "retry" in out.lower()

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_no_results_is_not_an_error(self, mock_client_cls):
        empty = "<html><body>nothing here</body></html>"
        _wire_client(mock_client_cls, [_search_resp(200, empty), _search_resp(200, empty)])
        out = web_search(query="qzxv nonexistent")
        assert out == "No results found for: qzxv nonexistent"

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_max_results_clamped(self, mock_client_cls):
        many = "".join(
            f'<a href="https://ex.com/{i}" class="result-link">R{i}</a>' for i in range(30)
        )
        _wire_client(mock_client_cls, [_search_resp(200, many)])
        out = web_search(query="q", max_results=50)  # clamps to 20
        assert "20. R19" in out
        assert "21." not in out

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_max_results_floor(self, mock_client_cls):
        many = "".join(
            f'<a href="https://ex.com/{i}" class="result-link">R{i}</a>' for i in range(5)
        )
        _wire_client(mock_client_cls, [_search_resp(200, many)])
        out = web_search(query="q", max_results=0)  # clamps to 1
        assert "1. R0" in out
        assert "2." not in out

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_empty_query_no_network(self, mock_client_cls):
        out = web_search(query="   ")
        assert out == "Error: query is empty."
        mock_client_cls.assert_not_called()

    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_output_truncated(self, mock_client_cls):
        long_snip = "x" * 900
        many = "".join(
            f'<a href="https://ex.com/{i}" class="result-link">R{i}</a>'
            f'<td class="result-snippet">{long_snip}</td>'
            for i in range(10)
        )
        _wire_client(mock_client_cls, [_search_resp(200, many)])
        out = web_search(query="q", max_results=10)
        assert out.endswith("(output truncated)")

    def test_exported_from_tools_package(self):
        from agenticops.tools import web_search as exported
        assert exported is not None
```

Also add `import httpx` to the test file's imports if not already present (check top of file; `web_fetch` tests may not import it — the fallback test raises `httpx.ConnectTimeout`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_tools.py -q 2>&1 | tail -5`
Expected: ImportError — `cannot import name 'web_search'`.

- [ ] **Step 3: Implement `web_search`**

In `src/agenticops/tools/web_tools.py`, after `_parse_ddg_results`:

```python
def _search_ddg_endpoint(endpoint: str, query: str, limit: int) -> tuple[list[dict], str | None]:
    """POST one DDG endpoint. Returns (results, error); error is None on success."""
    try:
        with httpx.Client(timeout=SEARCH_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(endpoint, data={"q": query}, headers=_SEARCH_HEADERS)
    except httpx.TimeoutException:
        return [], f"timeout after {SEARCH_TIMEOUT_SECONDS}s"
    except httpx.HTTPError as e:
        return [], f"connection error: {e}"

    if response.status_code in (202, 403):
        return [], f"HTTP {response.status_code} (rate-limited / bot challenge)"
    if response.status_code != 200:
        return [], f"HTTP {response.status_code}"
    if len(response.content) > MAX_RESPONSE_BYTES:
        return [], f"response too large ({len(response.content):,} bytes)"

    results = _parse_ddg_results(response.text, limit)
    if not results:
        return [], _NO_RESULTS
    return results, None


@tool
def web_search(query: str, max_results: int = 8) -> str:
    """Search the web via DuckDuckGo and return a numbered result list.

    Use this when you do NOT know the exact URL — search first, then call
    web_fetch on a promising result URL to read the page in depth.

    Args:
        query: Search terms (e.g., "EKS node NotReady kubelet PLEG").
        max_results: Number of results to return, 1-20 (default 8).

    Returns:
        Numbered plain-text list — title, URL, snippet per result — truncated
        to 4000 chars. Failures return text starting with "Error:".

    Examples:
        web_search(query="CVE-2024-3094 xz backdoor affected versions")
        web_search(query="aws alb 502 troubleshooting", max_results=5)
    """
    query = query.strip()
    if not query:
        return "Error: query is empty."
    try:
        limit = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
    except (TypeError, ValueError):
        limit = DEFAULT_SEARCH_RESULTS

    errors = []
    for endpoint in _DDG_ENDPOINTS:
        results, error = _search_ddg_endpoint(endpoint, query, limit)
        if results:
            lines = [f"Query: {query}", "Engine: duckduckgo", ""]
            for idx, item in enumerate(results, 1):
                lines.append(f"{idx}. {item['title']}")
                lines.append(f"   {item['url']}")
                if item["snippet"]:
                    lines.append(f"   {item['snippet']}")
            return _truncate("\n".join(lines))
        errors.append(f"{urlparse(endpoint).hostname}: {error}")

    if all(e.endswith(_NO_RESULTS) for e in errors):
        return f"No results found for: {query}"
    return (
        "Error: DuckDuckGo search failed ("
        + "; ".join(errors)
        + "). If rate-limited, retry after a short wait."
    )
```

- [ ] **Step 4: Export from tools package**

In `src/agenticops/tools/__init__.py`:
- Line ~66: `from agenticops.tools.web_tools import web_fetch` → `from agenticops.tools.web_tools import web_fetch, web_search`
- In `__all__`, after `"web_fetch",` add `"web_search",`

- [ ] **Step 5: Amend spec (implementation detail correction)**

In `docs/superpowers/specs/2026-07-03-web-search-design.md` §3, replace the line:

```
- Search requests send a browser-like User-Agent (module constant `SEARCH_USER_AGENT`)
  to reduce bot blocking; `web_fetch`'s `AgenticOps/1.0` UA is unchanged
```

with:

```
- Search requests send a full browser-like header set (module constant
  `_SEARCH_HEADERS`) — live probing (2026-07-03) showed DDG answers bare
  clients with an HTTP 202 anomaly challenge; `web_fetch`'s UA is unchanged
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_web_tools.py -q 2>&1 | tail -3`
Expected: all pass (existing + Task 1's 12 + these 9).
Also: `.venv/bin/python -m py_compile src/agenticops/tools/web_tools.py src/agenticops/tools/__init__.py`

- [ ] **Step 7: Commit**

```bash
git add src/agenticops/tools/web_tools.py src/agenticops/tools/__init__.py tests/test_web_tools.py docs/superpowers/specs/2026-07-03-web-search-design.md
git commit --no-verify -m "feat(web): web_search tool — DDG lite→html fallback, zero new deps

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Skill wiring — `skills/web-research/SKILL.md`

**Files:**
- Modify: `skills/web-research/SKILL.md`
- Test: existing `tests/test_prompt_budget.py` + a resolution check

**Interfaces:**
- Consumes: Task 2's dotted path `agenticops.tools.web_tools.web_search`.
- Produces: `activate_skill("web-research")` now registers BOTH `web_search` and `web_fetch` on the calling agent.

- [ ] **Step 1: Update frontmatter**

In `skills/web-research/SKILL.md` frontmatter:

Replace the `description:` block (lines 3–6) with (lead with both tools inside the first 200 chars — that's the index cap):

```yaml
description: Search the open web (DuckDuckGo) and fetch public URLs — status pages,
  docs, CVE data, changelogs. Provides web_search + web_fetch tools with security
  controls (private-IP blocking, size limits, timeouts). Use when investigation
  needs external internet information and you may not know the exact URL.
```

Replace the `tools:` list:

```yaml
tools:
- agenticops.tools.web_tools.web_search
- agenticops.tools.web_tools.web_fetch
```

Update version/provenance fields:

```yaml
skill_version: '1.1'
last_improved_at: '2026-07-03'
```

(keep `created_by: user`, `status: active`, `created_at`, `last_used` as-is.)

- [ ] **Step 2: Update body**

(a) Overview table → two rows:

```markdown
When this skill is activated, the `web_search` and `web_fetch` tools are dynamically registered on the agent:

| Tool | Purpose | Key Args |
|------|---------|----------|
| `web_search` | Search the web (DuckDuckGo), get titles/URLs/snippets | `query`, `max_results` (1-20, default 8) |
| `web_fetch` | Fetch public URL content | `url`, `method`, `headers` |
```

(b) Security Model — append two bullets:

```markdown
- **Search**: queries go to DuckDuckGo only (lite/html endpoints, POST); result URLs are just text — fetching them still goes through web_fetch's private-IP blocking
- **Search limits**: 15s per endpoint (lite → html fallback), results truncated to 4000 chars
```

(c) Decision tree "Need External Data?" — add as the FIRST branch:

```
  +-- Don't know the exact URL?
  |     +-- web_search(query="<error message or topic>")
  |     +-- Then web_fetch a promising result URL for depth
  |
```

(d) Quick card — add two rows:

```markdown
| `web_search(query="EKS node NotReady kubelet PLEG")` | Research an error message |
| `web_search(query="CVE-2024-3094 affected versions", max_results=5)` | Find CVE sources, then web_fetch one |
```

(e) Output Format — add:

```markdown
- **Search results**: numbered plain-text list (title / URL / snippet) — chain into web_fetch
```

- [ ] **Step 3: Verify skill resolves + budget holds**

```bash
.venv/bin/python -c "
import warnings, logging
warnings.filterwarnings('ignore'); logging.disable(logging.CRITICAL)
from agenticops.skills.loader import resolve_skill_tools, get_available_skills_xml
tools = resolve_skill_tools('web-research')
names = sorted(getattr(t, 'tool_name', getattr(t, '__name__', '?')) for t in tools)
assert names == ['web_fetch', 'web_search'], names
xml = get_available_skills_xml()
assert len(xml) < 5_000, len(xml)
print('resolved:', names, '| skills XML:', len(xml), 'chars')"
```

Expected: `resolved: ['web_fetch', 'web_search'] | skills XML: <~3700 chars`

Run: `.venv/bin/python -m pytest tests/test_prompt_budget.py tests/test_web_tools.py -q 2>&1 | tail -3`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add skills/web-research/SKILL.md
git commit --no-verify -m "feat(skills): web-research v1.1 — register web_search alongside web_fetch

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Prompt touches — 4 agents, one line each

**Files:**
- Modify: `src/agenticops/agents/main_agent.py:175`
- Modify: `src/agenticops/agents/sre_agent.py:172`
- Modify: `src/agenticops/agents/detect_agent.py:171`
- Modify: `src/agenticops/agents/scan_agent.py:67`
- Test: `tests/test_prompt_budget.py`

**Interfaces:** none new — prose-only edits; do NOT touch any other prompt line (protects Bedrock prompt cache and budget goldens).

- [ ] **Step 1: Apply the four one-line edits**

`main_agent.py` (~line 175):
- Old: `CVE info), call activate_skill("web-research") to load web_fetch, then`
- New: `CVE info), call activate_skill("web-research") to load web_search + web_fetch, then`

`sre_agent.py` (~line 172):
- Old: `3.7. WEB RESEARCH: Call activate_skill("web-research") to load web_fetch,`
- New: `3.7. WEB RESEARCH: Call activate_skill("web-research") to load web_search + web_fetch,`

`detect_agent.py` (~line 171):
- Old: `     activate_skill("web-research") to load web_fetch, then check cloud provider`
- New: `     activate_skill("web-research") to load web_search + web_fetch, then check cloud provider`

`scan_agent.py` (~line 67):
- Old: `- Skills dynamically register tools — after activation, web_fetch becomes available.`
- New: `- Skills dynamically register tools — after activation, web_search + web_fetch become available.`

- [ ] **Step 2: Verify compile + budget**

```bash
.venv/bin/python -m py_compile src/agenticops/agents/{main_agent,sre_agent,detect_agent,scan_agent}.py
.venv/bin/python -m pytest tests/test_prompt_budget.py -q 2>&1 | tail -3
```
Expected: compile clean; budget goldens pass (edits add ~13 chars each — within golden bands; if a band trips, report the numbers — do NOT widen goldens without checking which prompt overflowed).

- [ ] **Step 3: Commit**

```bash
git add src/agenticops/agents/main_agent.py src/agenticops/agents/sre_agent.py src/agenticops/agents/detect_agent.py src/agenticops/agents/scan_agent.py
git commit --no-verify -m "feat(agents): prompts mention web_search alongside web_fetch (4 one-liners)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs + live E2E smoke + full regression — then STOP for owner

**Files:**
- Modify: `docs/MVP-2.0.0-RELEASE.md` (one bullet in the Token/latest-additions area — find the section updated 2026-07-01 and add a sibling bullet)
- Modify: `CLAUDE.md` (skills section: the web-research mention — only if it names tools; otherwise skip)

**Interfaces:** none.

- [ ] **Step 1: Release-note bullet**

In `docs/MVP-2.0.0-RELEASE.md`, locate the most recent feature section (updated 2026-07-01) and add one bullet at its end:

```markdown
- **web_search（DuckDuckGo）**：`web-research` skill v1.1 新增 `web_search` 工具（lite→html 双端点降级、零新依赖、广告过滤、uddg 解链）；agent 可先搜后 `web_fetch` 深读。
```

(Exact placement: read the file first; put it in the feature list of the current release section, matching surrounding bullet style.)

- [ ] **Step 2: CLAUDE.md check**

Read the Skills section of `CLAUDE.md`. It describes architecture, not per-skill tools — if (and only if) a sentence explicitly lists web-research's tools, update it; otherwise make NO change.

- [ ] **Step 3: Live E2E smoke (real network, one query)**

```bash
.venv/bin/python -c "
import warnings, logging
warnings.filterwarnings('ignore'); logging.disable(logging.CRITICAL)
from agenticops.tools.web_tools import web_search
out = web_search(query='kubernetes node notready kubelet')
print(out[:800])"
```

Expected: `Query: ... / Engine: duckduckgo / 1. <title> ...` with real URLs.
Acceptable degraded outcome: rate-limit error text (bot challenge) — the error message itself must be well-formed. If rate-limited, wait 60 s and retry once; report the outcome either way.

- [ ] **Step 4: Full regression**

```bash
.venv/bin/python -m pytest tests/ -q -x --ignore=tests/e2e 2>&1 | tail -5
```
Expected: same pass count as baseline + new tests; the only allowed failure is the pre-existing `test_sre_window_size_from_yaml` config-drift failure (settings.yaml has -1, test expects 0). Anything else new = fix before proceeding.

- [ ] **Step 5: Commit docs**

```bash
git add docs/MVP-2.0.0-RELEASE.md CLAUDE.md
git commit --no-verify -m "docs: web_search feature note in 2.0.0 release doc

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(If CLAUDE.md was untouched in Step 2, omit it from `git add`.)

- [ ] **Step 6: STOP — report to owner**

Report: test counts, live-smoke output sample, commit list. **Do NOT `git push`.** Owner confirms E2E and authorizes push (project rule: push only after E2E + owner confirmation).
