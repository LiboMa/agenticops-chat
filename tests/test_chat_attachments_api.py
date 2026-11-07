"""Chat attachments API: upload one file, read its state and content, remove it (2026-11-07)."""
import time
import urllib.parse
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agenticops.config import ChatUploadSettings
from tests.fixtures.attachments import TOKENS, make

URL = "/api/chat/attachments"


@pytest.fixture
def env(tmp_path, monkeypatch):
    import agenticops.auth.models  # noqa: F401
    import agenticops.models as models_mod
    from agenticops.auth.service import AuthService
    from agenticops.chat.attachments import service
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    from agenticops.web.app import APIAuthMiddleware, app
    monkeypatch.setattr(models_mod, "_engine", None)
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/api.db")
    monkeypatch.setattr(settings, "chat_attachments_dir", str(tmp_path / "files"))
    monkeypatch.setattr(settings, "chat_upload", ChatUploadSettings())
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    models_mod.init_db()
    runtime_settings.reset_cache()
    service._last_sweep = 0.0

    def login(email, **kw):
        user = AuthService.create_user(email, "pw-123456", **kw)
        return {"Authorization": f"Bearer {AuthService.create_session(user.id)}"}, user
    # the app adds APIAuthMiddleware only when auth is on at import time: wrap it here, as a deployment with auth has it
    yield SimpleNamespace(client=TestClient(APIAuthMiddleware(app)), login=login, tmp=tmp_path, settings=settings)
    runtime_settings.reset_cache()


def upload(env, headers, path, name=None):
    with open(path, "rb") as f:
        return env.client.post(URL, headers=headers, files={"file": (name or path.name, f.read())})


def wait_ready(env, headers, att_id, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = env.client.get(f"{URL}/{att_id}", headers=headers).json()
        if body["status"] != "processing":
            return body
        time.sleep(0.2)
    raise AssertionError("still processing")


def bind_to_session(att_id, owner_id, visibility):
    from agenticops.chat.attachments import service
    from agenticops.models import ChatAttachment, ChatSession, get_db_session
    sid = str(uuid.uuid4())
    with get_db_session() as db:
        row = ChatSession(session_id=sid, name="t", owner_user_id=owner_id, visibility=visibility)
        db.add(row)
        db.flush()
        service.bind(db, [db.get(ChatAttachment, att_id)], row, None)
    service.move_bound([att_id], sid)
    return sid


def test_upload_returns_processing_then_ready(env):
    h, _ = env.login("alice@x")
    r = upload(env, h, make("pdf", env.tmp / "in"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "processing" and body["kind"] == "pdf" and body["filename"] == "sample-pdf.pdf"
    assert len(body["id"]) == 32 and body["size"] > 0
    ready = wait_ready(env, h, body["id"])
    assert ready["status"] == "ready" and ready["meta"]["pages"] == 3 and ready["meta"]["has_text_layer"] is True
    assert "sha256" not in ready["meta"] and ready["session_id"] is None


def test_411_without_length(env):
    h, _ = env.login("alice@x")

    def body():
        yield b"--x\r\nContent-Disposition: form-data; name=\"file\"; filename=\"a.txt\"\r\n\r\nhi\r\n--x--\r\n"
    r = env.client.post(URL, headers={**h, "Content-Type": "multipart/form-data; boundary=x"}, content=body())
    assert r.status_code == 411 and r.json()["code"] == "length_required"


def test_413_over_limit_and_config_change_applies_immediately(env):
    from agenticops.chat import upload_config
    h, _ = env.login("alice@x")
    big = env.tmp / "big.txt"
    big.write_bytes(b"a" * (2 * 1024 * 1024))
    assert upload(env, h, big).status_code == 201
    upload_config.save_patch({"max_file_mb": 1, "max_total_mb": 1}, "user:admin")
    r = upload(env, h, big)
    assert r.status_code == 413 and r.json()["code"] == "file_too_large"


def test_415_unknown_ext(env):
    h, _ = env.login("alice@x")
    exe = env.tmp / "setup.exe"
    exe.write_bytes(b"MZ\x90\x00")
    r = upload(env, h, exe)
    assert r.status_code == 415 and r.json()["code"] == "unsupported_type"


def test_415_not_in_allowed_extensions(env):
    from agenticops.chat import upload_config
    h, _ = env.login("alice@x")
    upload_config.save_patch({"allowed_extensions": [".pdf"]}, "user:admin")
    r = upload(env, h, make("txt", env.tmp / "in"))
    assert r.status_code == 415 and r.json()["code"] == "unsupported_type"


def test_415_magic_mismatch(env):
    h, _ = env.login("alice@x")
    fake = env.tmp / "photo.png"
    fake.write_bytes(b"%PDF-1.7 not a png")
    r = upload(env, h, fake)
    assert r.status_code == 415 and r.json()["code"] == "content_mismatch"
    binary = env.tmp / "notes.txt"
    binary.write_bytes(b"\x7fELF\x02\x01\x01\x00\x00")
    assert upload(env, h, binary).json()["code"] == "binary_text"


def test_507_low_disk(env, monkeypatch):
    from agenticops.chat.attachments import store
    h, _ = env.login("alice@x")
    monkeypatch.setattr(store, "disk_free_ok", lambda: False)
    r = upload(env, h, make("txt", env.tmp / "in"))
    assert r.status_code == 507 and r.json()["code"] == "insufficient_storage"


def test_accepts_extensionless_and_sh_and_utf16_tsv(env):
    h, _ = env.login("alice@x")
    mk = env.tmp / "Makefile"
    mk.write_text("all:\n\techo ok\n")
    sh = env.tmp / "deploy.sh"
    sh.write_text("#!/bin/sh\necho ok\n")
    for path in (mk, sh, make("utf16_tsv", env.tmp / "in")):
        r = upload(env, h, path)
        assert r.status_code == 201, (path.name, r.text)
        assert wait_ready(env, h, r.json()["id"])["status"] == "ready"


def test_get_other_users_staged_404(env):
    h, _ = env.login("alice@x")
    hb, _ = env.login("bob@x")
    att_id = upload(env, h, make("txt", env.tmp / "in")).json()["id"]
    assert env.client.get(f"{URL}/{att_id}", headers=hb).status_code == 404
    assert env.client.get(f"{URL}/{att_id}/content", headers=hb).status_code == 404
    assert env.client.delete(f"{URL}/{att_id}", headers=hb).status_code == 404
    assert env.client.get(f"{URL}/{'0' * 32}", headers=h).status_code == 404


def test_get_private_session_attachment_404_for_other(env):
    h, alice = env.login("alice@x")
    hb, _ = env.login("bob@x")
    ha, _ = env.login("root@x", is_admin=True)
    att_id = upload(env, h, make("png", env.tmp / "in")).json()["id"]
    wait_ready(env, h, att_id)
    sid = bind_to_session(att_id, alice.id, "private")
    assert env.client.get(f"{URL}/{att_id}", headers=h).json()["session_id"] == sid
    assert env.client.get(f"{URL}/{att_id}/content?variant=thumb", headers=hb).status_code == 404
    assert env.client.get(f"{URL}/{att_id}/content?variant=thumb", headers=ha).status_code == 200
    att2 = upload(env, h, make("png", env.tmp / "in2")).json()["id"]
    wait_ready(env, h, att2)
    bind_to_session(att2, alice.id, "workspace")
    assert env.client.get(f"{URL}/{att2}/content?variant=thumb", headers=hb).status_code == 200


def test_inline_image_attachment_others(env):
    h, _ = env.login("alice@x")
    png = upload(env, h, make("png", env.tmp / "a")).json()["id"]
    heic = upload(env, h, make("heic", env.tmp / "b")).json()["id"]
    pdf = upload(env, h, make("scan_pdf", env.tmp / "c")).json()["id"]
    for att_id in (png, heic, pdf):
        wait_ready(env, h, att_id)

    def get(att_id, variant):
        return env.client.get(f"{URL}/{att_id}/content", params={"variant": variant}, headers=h)
    r = get(png, "original")
    assert r.headers["content-type"] == "image/png" and r.headers["content-disposition"].startswith("inline")
    assert r.content[:4] == b"\x89PNG"
    r = get(heic, "original")
    assert r.headers["content-disposition"].startswith("attachment")   # browsers cannot show HEIC
    r = get(heic, "preview")
    assert r.headers["content-type"] == "image/jpeg" and r.headers["content-disposition"].startswith("inline")
    assert get(heic, "thumb").headers["content-type"] == "image/jpeg"
    r = get(pdf, "original")
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("attachment")
    r = get(pdf, "page-2")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert get(pdf, "page-9").status_code == 404
    assert get(pdf, "preview").json()["code"] == "variant_unavailable"
    assert get(pdf, "bogus").status_code == 422


def test_content_disposition_unicode_name(env):
    h, _ = env.login("alice@x")
    name = "报告 Q3; x(1).pdf"
    att_id = upload(env, h, make("pdf", env.tmp / "in"), name=name).json()["id"]
    wait_ready(env, h, att_id)
    cd = env.client.get(f"{URL}/{att_id}/content", headers=h).headers["content-disposition"]
    assert cd.startswith("attachment; filename=")
    star = cd.split("filename*=UTF-8''", 1)[1]
    assert urllib.parse.unquote(star) == name
    ascii_part = cd.split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part.isascii() and ";" not in ascii_part and ascii_part.endswith(".pdf")


def test_nosniff_and_csp_headers(env):
    h, _ = env.login("alice@x")
    att_id = upload(env, h, make("html", env.tmp / "in")).json()["id"]
    wait_ready(env, h, att_id)
    r = env.client.get(f"{URL}/{att_id}/content", headers=h)
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["content-security-policy"] == "sandbox"
    assert r.headers["cache-control"] == "private, max-age=3600"
    assert r.headers["content-disposition"].startswith("attachment")   # HTML is never rendered by the browser
    assert TOKENS["html"].encode() in r.content


def test_delete_staged_and_bound_409(env):
    h, alice = env.login("alice@x")
    att_id = upload(env, h, make("txt", env.tmp / "in")).json()["id"]
    wait_ready(env, h, att_id)
    assert env.client.delete(f"{URL}/{att_id}", headers=h).status_code == 204
    assert env.client.get(f"{URL}/{att_id}", headers=h).status_code == 404
    bound = upload(env, h, make("txt", env.tmp / "in2")).json()["id"]
    wait_ready(env, h, bound)
    bind_to_session(bound, alice.id, "private")
    r = env.client.delete(f"{URL}/{bound}", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "attachment_bound"


def test_viewer_can_upload_and_delete_own(env):
    h, _ = env.login("viewer@x", permissions=["read"])
    r = upload(env, h, make("txt", env.tmp / "in"))
    assert r.status_code == 201, r.text
    att_id = r.json()["id"]
    wait_ready(env, h, att_id)
    assert env.client.get(f"{URL}/{att_id}/content", headers=h).status_code == 200
    assert env.client.delete(f"{URL}/{att_id}", headers=h).status_code == 204


def test_unauthenticated_upload_refused(env):
    r = env.client.post(URL, files={"file": ("a.txt", b"hi")})
    assert r.status_code == 401
