"""The service log handlers (2026-11-08): they write under `settings.log_dir`, and installing them twice adds nothing.
The test suite sets AIOPS_LOG_DIR to a temp dir (conftest): a test that starts the app's lifespan must never write, or
rotate away, the running service's logs/backend.log (the full suite did: five rotations of DEBUG test output pushed
the service's history out)."""
import logging

import pytest


@pytest.fixture
def fresh_loggers():
    names = ("agenticops", "uvicorn.error", "uvicorn", "uvicorn.access")
    before = {n: list(logging.getLogger(n).handlers) for n in names}
    yield
    for n in names:
        lg = logging.getLogger(n)
        for h in list(lg.handlers):
            if h not in before[n]:
                lg.removeHandler(h)
                h.close()


def _service_handlers():
    out = []
    for n in ("agenticops", "uvicorn.error", "uvicorn", "uvicorn.access"):
        out += [h for h in logging.getLogger(n).handlers if isinstance(h, logging.FileHandler)]
    return out


def test_logs_go_under_the_data_dirs_logs_directory(tmp_path, monkeypatch, fresh_loggers):
    import agenticops.web.app as webapp
    monkeypatch.setattr(webapp.settings, "log_dir", tmp_path / "logs")
    webapp._setup_service_logging()
    logging.getLogger("agenticops").info("hello from the test")
    for h in _service_handlers():
        h.flush()
    assert "hello from the test" in (tmp_path / "logs" / "backend.log").read_text(encoding="utf-8")
    # nothing this setup attached writes anywhere else (the running service's logs/ above all)
    added = [h for h in _service_handlers() if str(tmp_path) in h.baseFilename]
    assert {h.baseFilename.rsplit("/", 1)[-1] for h in added} == {"backend.log", "frontend.log"}


def test_installing_twice_adds_each_handler_once(tmp_path, monkeypatch, fresh_loggers):
    import agenticops.web.app as webapp
    monkeypatch.setattr(webapp.settings, "log_dir", tmp_path / "logs")
    webapp._setup_service_logging()
    webapp._setup_service_logging()
    mine = [h for h in _service_handlers() if str(tmp_path) in h.baseFilename]
    backend = [h for h in logging.getLogger("agenticops").handlers if h in mine]
    assert len(backend) == 1
    assert len([h for h in logging.getLogger("uvicorn.access").handlers if h in mine]) == 1


def test_the_suite_never_logs_into_the_projects_logs_directory():
    """conftest points AIOPS_LOG_DIR at a temp dir before anything reads the settings."""
    from agenticops.config import PROJECT_ROOT, settings
    assert settings.log_dir.resolve() != (PROJECT_ROOT / "logs").resolve()
