"""Web tools — fetch public web pages, APIs, and status pages.

Provides agents with the ability to retrieve content from public URLs
for operational investigation (cloud status pages, documentation, CVE
databases, changelogs, API endpoints).

Security: private/reserved IPs are blocked, only GET/HEAD allowed,
response size and output length are capped.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx
from strands import tool

logger = logging.getLogger(__name__)

# ── Limits ────────────────────────────────────────────────────────────
MAX_RESULT_CHARS = 4000
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1_048_576  # 1 MB
USER_AGENT = "AgenticOps/1.0"
ALLOWED_METHODS = {"GET", "HEAD"}

# ── Cloud metadata hostnames (always blocked) ─────────────────────────
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "metadata.aws.internal",
    "169.254.169.254",
})


def _truncate(text: str, limit: int = MAX_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... (output truncated)"


def _is_private_ip(ip_str: str) -> bool:
    """Return True if the IP address is private, loopback, link-local, or reserved."""
    try:
        addr = ipaddress.ip_address(ip_str)
        return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
    except ValueError:
        return True  # If we can't parse it, block it


def _resolve_and_check(hostname: str) -> str | None:
    """Resolve hostname and return error string if any resolved IP is private."""
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return f"Error: Hostname '{hostname}' is blocked (cloud metadata endpoint)."
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in results:
            ip_str = sockaddr[0]
            if _is_private_ip(ip_str):
                return f"Error: URL resolves to private/reserved IP ({ip_str}). Blocked for security."
        return None
    except socket.gaierror:
        return f"Error: Could not resolve hostname '{hostname}'."


def _strip_html(html: str) -> str:
    """Convert HTML to readable plain text using regex (no external deps)."""
    # Remove script, style, nav, footer, header blocks entirely
    for tag in ("script", "style", "nav", "footer", "header"):
        html = re.sub(rf"<{tag}[\s>].*?</{tag}>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Try to extract <main> or <article> content
    for container in ("main", "article"):
        match = re.search(rf"<{container}[\s>](.*?)</{container}>", html, re.DOTALL | re.IGNORECASE)
        if match:
            html = match.group(1)
            break

    # Convert headings to markdown-style
    html = re.sub(r"<h[1-6][^>]*>(.*?)</h[1-6]>", r"\n## \1\n", html, flags=re.DOTALL | re.IGNORECASE)
    # Convert list items
    html = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1", html, flags=re.DOTALL | re.IGNORECASE)
    # Convert <br> and <p> to newlines
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</?p[^>]*>", "\n", html, flags=re.IGNORECASE)
    # Strip all remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Decode common HTML entities
    html = html.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    html = html.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
    # Collapse multiple blank lines
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


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


@tool
def web_fetch(url: str, method: str = "GET", headers: str = "") -> str:
    """Fetch content from a public URL and return the text.

    Use this to check cloud provider status pages, read documentation,
    query public APIs, or fetch changelogs and CVE data.

    Args:
        url: The URL to fetch. Must start with http:// or https://.
        method: HTTP method — only GET and HEAD are allowed.
        headers: Optional JSON string of additional headers
                 (e.g., '{"Accept": "application/json"}').

    Returns:
        Response content as text. HTML is automatically converted to
        readable plain text. JSON is returned as-is. Truncated to 4000 chars.

    Examples:
        web_fetch(url="https://health.aws.amazon.com/health/status")
        web_fetch(url="https://api.github.com/repos/owner/repo/releases/latest",
                  headers='{"Accept": "application/json"}')
    """
    # ── Validate URL ──────────────────────────────────────────────────
    url = url.strip()
    if not url:
        return "Error: URL is empty."

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Error: Only http:// and https:// URLs are allowed (got '{parsed.scheme}://')."

    if not parsed.hostname:
        return "Error: Invalid URL — no hostname found."

    # ── Validate method ───────────────────────────────────────────────
    method = method.upper().strip()
    if method not in ALLOWED_METHODS:
        return f"Error: Only {', '.join(sorted(ALLOWED_METHODS))} methods are allowed (got '{method}')."

    # ── Check for private/reserved IPs ────────────────────────────────
    ip_error = _resolve_and_check(parsed.hostname)
    if ip_error:
        return ip_error

    # ── Parse optional headers ────────────────────────────────────────
    extra_headers: dict = {}
    if headers and headers.strip():
        try:
            extra_headers = json.loads(headers)
            if not isinstance(extra_headers, dict):
                return "Error: headers must be a JSON object (e.g., '{\"Accept\": \"application/json\"}')."
        except json.JSONDecodeError as e:
            return f"Error: Invalid JSON in headers: {e}"

    # ── Make the request ──────────────────────────────────────────────
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            max_redirects=0,
        ) as client:
            request_headers = {"User-Agent": USER_AGENT, **extra_headers}
            response = client.request(method, url, headers=request_headers)

            # Handle redirects — return target, let agent decide
            if response.is_redirect:
                location = response.headers.get("location", "unknown")
                return (
                    f"Redirect ({response.status_code}) → {location}\n"
                    f"Call web_fetch again with the new URL if you want to follow it."
                )

            # Check for HTTP errors
            if response.status_code >= 400:
                body_preview = response.text[:500] if response.text else ""
                return f"HTTP {response.status_code} error fetching {url}\n{body_preview}"

            # Check size
            content_length = len(response.content)
            if content_length > MAX_RESPONSE_BYTES:
                return f"Error: Response too large ({content_length:,} bytes, limit is {MAX_RESPONSE_BYTES:,})."

            # HEAD requests — return headers only
            if method == "HEAD":
                header_lines = [f"{k}: {v}" for k, v in response.headers.items()]
                return _truncate(f"HEAD {url}\nStatus: {response.status_code}\n" + "\n".join(header_lines))

            # Process response body
            content_type = response.headers.get("content-type", "")
            body = response.text

            if "text/html" in content_type:
                body = _strip_html(body)

            result = f"URL: {url}\nStatus: {response.status_code}\nContent-Type: {content_type}\n\n{body}"
            return _truncate(result)

    except httpx.ConnectTimeout:
        return f"Error: Connection timed out after {TIMEOUT_SECONDS}s connecting to {parsed.hostname}."
    except httpx.ReadTimeout:
        return f"Error: Read timed out after {TIMEOUT_SECONDS}s reading from {url}."
    except httpx.ConnectError as e:
        return f"Error: Could not connect to {parsed.hostname}: {e}"
    except httpx.TooManyRedirects:
        return f"Error: Too many redirects from {url}."
    except Exception as e:
        return f"Error fetching {url}: {e}"


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
