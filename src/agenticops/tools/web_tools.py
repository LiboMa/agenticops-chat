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
from urllib.parse import urlparse

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
