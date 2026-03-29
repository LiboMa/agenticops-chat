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
