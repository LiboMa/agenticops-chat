"""`aiops quickstart --scan` sends its scan command through the chat API (MVP-2.7.0 S5: every send carries a
client_message_id), and says it was triggered only when the server accepted it."""
import re

from agenticops.cli.main import _trigger_quickstart_scan


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


def test_the_scan_message_carries_a_client_id_and_is_checked():
    calls = []

    def post(url, json=None, timeout=None):
        calls.append((url, json))
        return _Resp(201, {"session_id": "s1"}) if url.endswith("/sessions") else _Resp(200)

    assert _trigger_quickstart_scan("127.0.0.1", 8000, post=post) == (True, "s1")
    url, body = calls[1]
    assert url.endswith("/api/chat/sessions/s1/messages") and body["content"] == "scan all resources"
    assert re.fullmatch(r"[0-9a-f-]{36}", body["client_message_id"])


def test_a_refused_scan_is_not_reported_as_triggered():
    def post(url, json=None, timeout=None):
        return _Resp(201, {"session_id": "s1"}) if url.endswith("/sessions") else _Resp(422)

    assert _trigger_quickstart_scan("127.0.0.1", 8000, post=post) == (False, "s1")
