"""Chat attachments: extraction runs in a subprocess — a crash, a hang or a bad file never reaches the service."""
import json
import time

from agenticops.chat.attachments.extract import ExtractLimits
from agenticops.chat.attachments.worker import WorkerResult, run
from tests.fixtures.attachments import TOKENS, make

LIM = ExtractLimits(text_max_chars=100_000, image_max_edge_px=1568, pdf_render_pages_max=5)


def _out(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    return out


def test_run_ok_writes_meta(tmp_path):
    out = _out(tmp_path)
    result = run(make("docx", tmp_path / "in"), ".docx", out, LIM)
    assert isinstance(result, WorkerResult)
    assert result.ok is True and result.reason is None
    assert result.meta == json.loads((out / "meta.json").read_text())
    assert TOKENS["docx"] in (out / "text.txt").read_text()


def test_extract_error_maps_reason(tmp_path):
    result = run(make("encrypted_pdf", tmp_path / "in"), ".pdf", _out(tmp_path), LIM)
    assert result.ok is False and result.reason == "encrypted" and result.meta == {}


def test_timeout_kills_child(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOPS_ATTACHMENT_WORKER_TEST_SLEEP", "30")
    started = time.monotonic()
    result = run(make("txt", tmp_path / "in"), ".txt", _out(tmp_path), LIM, timeout=1)
    assert result.ok is False and result.reason == "timeout"
    assert time.monotonic() - started < 10


def test_crash_is_reason_not_exception(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOPS_ATTACHMENT_WORKER_TEST_CRASH", "1")
    result = run(make("txt", tmp_path / "in"), ".txt", _out(tmp_path), LIM)
    assert result.ok is False and result.reason == "worker_crashed"


def test_child_env_has_no_aws_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "do-not-leak")
    monkeypatch.setenv("AWS_PROFILE", "prod")
    monkeypatch.setenv("AIOPS_ATTACHMENT_WORKER_TEST_ENV", "1")
    out = _out(tmp_path)
    result = run(make("txt", tmp_path / "in"), ".txt", out, LIM)
    keys = json.loads((out / "env.json").read_text())
    assert result.ok is True
    assert not [k for k in keys if k.startswith("AWS_")]
    assert "PATH" in keys


def test_missing_source_is_failed(tmp_path):
    result = run(tmp_path / "nope.txt", ".txt", _out(tmp_path), LIM)
    assert result.ok is False and result.reason


def test_memory_limit_is_set_in_the_child_not_through_preexec_fn(tmp_path, monkeypatch):
    """preexec_fn is unsafe in a threaded process (and disables the vfork fast path): the child limits itself."""
    import subprocess as sp
    from agenticops.chat.attachments import worker
    seen = {}
    real_run = sp.run

    def spy(cmd, **kw):
        seen.update(kw)
        return real_run(cmd, **kw)
    monkeypatch.setattr(worker.subprocess, "run", spy)
    monkeypatch.setattr(worker.sys, "platform", "linux")
    run(make("txt", tmp_path / "in"), ".txt", _out(tmp_path), LIM)
    assert seen.get("preexec_fn") is None
    calls = []
    monkeypatch.setattr(worker, "_limit_memory", lambda: calls.append("limited"))
    out = tmp_path / "child"
    out.mkdir()
    src = make("txt", tmp_path / "in2")
    assert worker.main([str(src), ".txt", str(out), json.dumps({"text_max_chars": 1000, "image_max_edge_px": 512,
                                                               "pdf_render_pages_max": 1})]) == 0
    assert calls == ["limited"]
