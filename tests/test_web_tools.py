"""Tests for web_tools — web_fetch @tool and web-research skill."""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, "src")

from agenticops.tools.web_tools import (
    _is_private_ip,
    _resolve_and_check,
    _strip_html,
    _truncate,
    web_fetch,
)


# ── URL validation ────────────────────────────────────────────────────

class TestUrlValidation:
    def test_empty_url(self):
        result = web_fetch(url="")
        assert "Error" in result

    def test_file_scheme_rejected(self):
        result = web_fetch(url="file:///etc/passwd")
        assert "Error" in result and "http" in result.lower()

    def test_ftp_scheme_rejected(self):
        result = web_fetch(url="ftp://example.com/file")
        assert "Error" in result

    def test_javascript_scheme_rejected(self):
        result = web_fetch(url="javascript:alert(1)")
        assert "Error" in result

    def test_no_hostname(self):
        result = web_fetch(url="http://")
        assert "Error" in result


# ── Method restriction ────────────────────────────────────────────────

class TestMethodRestriction:
    def test_post_rejected(self):
        result = web_fetch(url="https://example.com", method="POST")
        assert "Error" in result and "POST" in result

    def test_put_rejected(self):
        result = web_fetch(url="https://example.com", method="PUT")
        assert "Error" in result

    def test_delete_rejected(self):
        result = web_fetch(url="https://example.com", method="DELETE")
        assert "Error" in result


# ── Private IP blocking ───────────────────────────────────────────────

class TestPrivateIpBlocking:
    def test_loopback_v4(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_private_10(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_172(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_private_192(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_link_local(self):
        assert _is_private_ip("169.254.169.254") is True

    def test_ipv6_loopback(self):
        assert _is_private_ip("::1") is True

    def test_public_ip(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_metadata_hostname_blocked(self):
        error = _resolve_and_check("metadata.google.internal")
        assert error is not None and "blocked" in error.lower()

    def test_169_254_hostname_blocked(self):
        error = _resolve_and_check("169.254.169.254")
        assert error is not None and "blocked" in error.lower()

    @patch("agenticops.tools.web_tools.socket.getaddrinfo")
    def test_hostname_resolving_to_private_ip(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("10.0.0.1", 0)),
        ]
        error = _resolve_and_check("evil.example.com")
        assert error is not None and "private" in error.lower()

    @patch("agenticops.tools.web_tools.socket.getaddrinfo")
    def test_hostname_resolving_to_public_ip(self, mock_getaddr):
        mock_getaddr.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]
        error = _resolve_and_check("example.com")
        assert error is None


# ── HTML stripping ────────────────────────────────────────────────────

class TestHtmlStripping:
    def test_script_removed(self):
        html = "<p>Hello</p><script>alert('xss')</script><p>World</p>"
        result = _strip_html(html)
        assert "alert" not in result
        assert "Hello" in result
        assert "World" in result

    def test_style_removed(self):
        html = "<style>.foo{color:red}</style><p>Content</p>"
        result = _strip_html(html)
        assert "color" not in result
        assert "Content" in result

    def test_tags_stripped(self):
        html = "<div><span>Hello</span> <b>World</b></div>"
        result = _strip_html(html)
        assert "Hello" in result
        assert "World" in result
        assert "<" not in result

    def test_article_extraction(self):
        html = "<nav>Menu</nav><article><p>Main content</p></article><footer>Foot</footer>"
        result = _strip_html(html)
        assert "Main content" in result

    def test_entities_decoded(self):
        html = "<p>A &amp; B &lt; C</p>"
        result = _strip_html(html)
        assert "A & B < C" in result


# ── Output truncation ─────────────────────────────────────────────────

class TestTruncation:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        text = "x" * 5000
        result = _truncate(text, 100)
        assert len(result) < 200
        assert "truncated" in result


# ── Successful fetch (mocked) ─────────────────────────────────────────

class TestWebFetchSuccess:
    @patch("agenticops.tools.web_tools._resolve_and_check", return_value=None)
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_get_json(self, mock_client_cls, mock_resolve):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.content = b'{"status": "ok"}'
        mock_response.text = '{"status": "ok"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(
            request=MagicMock(return_value=mock_response)
        ))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = web_fetch(url="https://api.example.com/status")
        assert "ok" in result
        assert "Status: 200" in result

    @patch("agenticops.tools.web_tools._resolve_and_check", return_value=None)
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_get_html_stripped(self, mock_client_cls, mock_resolve):
        html = "<html><script>bad</script><body><p>Good content</p></body></html>"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_redirect = False
        mock_response.content = html.encode()
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html; charset=utf-8"}
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(
            request=MagicMock(return_value=mock_response)
        ))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = web_fetch(url="https://example.com")
        assert "Good content" in result
        assert "bad" not in result

    @patch("agenticops.tools.web_tools._resolve_and_check", return_value=None)
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_redirect_returns_location(self, mock_client_cls, mock_resolve):
        mock_response = MagicMock()
        mock_response.status_code = 301
        mock_response.is_redirect = True
        mock_response.headers = {"location": "https://new.example.com/"}
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(
            request=MagicMock(return_value=mock_response)
        ))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = web_fetch(url="https://old.example.com")
        assert "Redirect" in result
        assert "new.example.com" in result


# ── Error handling ────────────────────────────────────────────────────

class TestWebFetchErrors:
    @patch("agenticops.tools.web_tools._resolve_and_check", return_value=None)
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_http_404(self, mock_client_cls, mock_resolve):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.is_redirect = False
        mock_response.text = "Not Found"
        mock_response.headers = {}
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=MagicMock(
            request=MagicMock(return_value=mock_response)
        ))
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = web_fetch(url="https://example.com/missing")
        assert "404" in result

    @patch("agenticops.tools.web_tools._resolve_and_check", return_value=None)
    @patch("agenticops.tools.web_tools.httpx.Client")
    def test_timeout(self, mock_client_cls, mock_resolve):
        import httpx
        mock_client = MagicMock()
        mock_client.request.side_effect = httpx.ConnectTimeout("timed out")
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = web_fetch(url="https://slow.example.com")
        assert "timed out" in result.lower() or "timeout" in result.lower()

    def test_invalid_headers_json(self):
        result = web_fetch(url="https://example.com", headers="not json")
        assert "Error" in result and "JSON" in result


# ── Skill discovery ───────────────────────────────────────────────────

class TestSkillDiscovery:
    def test_web_research_skill_discovered(self):
        from agenticops.skills.loader import discover_skills
        skills = discover_skills()
        names = [s.name for s in skills]
        assert "web-research" in names

    def test_web_research_tools_resolve(self):
        from agenticops.skills.loader import resolve_skill_tools
        tools = resolve_skill_tools("web-research")
        assert len(tools) == 1
        tool_names = [getattr(t, "__name__", getattr(t, "tool_name", "")) for t in tools]
        assert any("web_fetch" in n for n in tool_names)


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


# ── web_search tool ───────────────────────────────────────────────────

import httpx  # noqa: E402

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
