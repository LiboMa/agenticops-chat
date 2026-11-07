"""Live E2E: chat attachments through the real API and the real Main agent on real Bedrock models (2026-11-07).

    AIOPS_TESTS_ALLOW_AWS=1 pytest --run-integration tests/integration/test_chat_attachments_live.py -v -s

Billed (≈ $2–4). Every file carries a unique code word (tests/fixtures/attachments.TOKENS); a model answers right
only if it read that file. Files go through POST /api/chat/attachments (the subprocess worker), then
POST /api/chat/sessions/{id}/messages with attachment_ids, on sessions pinned to Opus 5.5, GPT-6 Astra and gpt-oss.
.doc / .xls are real legacy files made by LibreOffice (`soffice`) from the .docx / .xlsx fixtures.
"""
import json
import shutil
import subprocess
import time
import uuid

import pytest

from tests.fixtures.attachments import TOKENS, make

pytestmark = pytest.mark.integration

OPUS = "global.anthropic.claude-opus-5-5"
GPT6 = "global.openai.gpt-6-astra"
GPT_OSS = "openai.gpt-oss-120b-1:0"
ASK = ("Each attached file contains one code word made of capital letters, a hyphen and letters or digits "
       "(for example ABC-XYZ-1234; in a picture it is drawn as text). Reply with one line per attached file: "
       "<file name>: <code word>. Do not call any tools.")


def frames(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        ev, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if data:
            out.append((ev, json.loads("\n".join(data))))
    return out


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    import agenticops.models as models_mod
    from fastapi.testclient import TestClient
    from agenticops.config import settings
    from agenticops.services import runtime_settings
    from agenticops.web.app import app
    tmp = tmp_path_factory.mktemp("att-live")
    saved = (settings.database_url, settings.chat_attachments_dir, settings.api_auth_enabled, models_mod._engine)
    settings.database_url = f"sqlite:///{tmp}/live.db"
    settings.chat_attachments_dir = str(tmp / "files")
    settings.api_auth_enabled = False
    models_mod._engine = None
    models_mod.init_db()
    runtime_settings.reset_cache()
    files = {kind: make(kind, tmp / "src" / kind) for kind in TOKENS if kind not in ("doc", "xls", "tsv")}
    files["tsv"] = make("gbk_tsv", tmp / "src" / "tsv")
    if shutil.which("soffice"):
        for kind, src in (("doc", files["docx"]), ("xls", files["xlsx"])):
            out = tmp / "src" / kind
            out.mkdir(parents=True)
            subprocess.run(["soffice", "--headless", "--convert-to", kind, "--outdir", str(out), str(src)],
                           check=True, capture_output=True, timeout=120)
            files[kind] = next(out.glob(f"*.{kind}"))
    yield {"client": TestClient(app), "files": files, "tmp": tmp}
    settings.database_url, settings.chat_attachments_dir, settings.api_auth_enabled, models_mod._engine = saved
    runtime_settings.reset_cache()


def _session(env, model: str) -> str:
    sid = env["client"].post("/api/chat/sessions", json={}).json()["session_id"]
    assert env["client"].patch(f"/api/chat/sessions/{sid}", json={"model_id": model}).status_code == 200
    return sid


def _upload(env, kind: str) -> str:
    path = env["files"][kind]
    r = env["client"].post("/api/chat/attachments", files={"file": (path.name, path.read_bytes())})
    assert r.status_code == 201, r.text
    att = r.json()["id"]
    deadline = time.monotonic() + 120
    while env["client"].get(f"/api/chat/attachments/{att}").json()["status"] == "processing":
        assert time.monotonic() < deadline
        time.sleep(0.2)
    return att


def _ask(env, sid: str, ids: list[str], question: str = ASK) -> tuple[str, dict, list]:
    started = time.monotonic()
    r = env["client"].post(f"/api/chat/sessions/{sid}/messages",
                           json={"content": question, "client_message_id": str(uuid.uuid4()), "attachment_ids": ids})
    assert r.status_code == 200, r.text
    events = frames(r.text)
    reply = "".join(d.get("token", "") for e, d in events if e == "text")
    errors = [d for e, d in events if e == "error"]
    if errors and "unsupported countries" in json.dumps(errors).lower():
        pytest.skip(f"model geo-blocked from this network: {errors}")
    deliveries = {i["id"]: i for e, d in events if e == "attachments" for i in d["items"]}
    usage = next((d for e, d in events if e == "done"), {})
    print(f"\n[{time.monotonic() - started:.0f}s] deliveries={[(i['filename'], i['delivery'], i['reason']) for i in deliveries.values()]}"
          f" usage={ {k: usage.get(k) for k in ('input_tokens', 'output_tokens')} }\nreply: {reply[:600]!r}")
    return reply, deliveries, errors


OPUS_GROUPS = [
    ["txt", "md", "html", "htm", "csv"],
    ["pdf", "scan_pdf", "docx", "json", "log"],
    ["xlsx", "xlsm", "tsv", "pptx"],
    ["doc", "xls", "jpg", "png"],
    ["gif", "webp", "bmp", "tiff", "heic"],
]


def test_opus_55_reads_all_23_types(env):
    if "doc" not in env["files"]:
        pytest.skip("soffice is needed to make real .doc / .xls files")
    token_of = {**TOKENS, "doc": TOKENS["docx"], "xls": TOKENS["xlsx"]}
    seen = set()
    for group in OPUS_GROUPS:
        sid = _session(env, OPUS)
        ids = [_upload(env, k) for k in group]
        reply, deliveries, errors = _ask(env, sid, ids)
        assert not errors, errors
        for kind, att in zip(group, ids):
            assert deliveries[att]["delivery"] not in ("notice", "failed"), (kind, deliveries[att])
            assert token_of[kind].lower() in reply.lower(), (kind, reply)
            seen.add(kind)
    assert len(seen) == 23


def test_gpt6_astra_delivery(env):
    sid = _session(env, GPT6)
    kinds = ["png", "txt", "pdf", "scan_pdf", "docx"] + (["doc"] if "doc" in env["files"] else [])
    ids = [_upload(env, k) for k in kinds]
    reply, deliveries, errors = _ask(env, sid, ids)
    assert not errors, errors
    by_kind = dict(zip(kinds, ids))
    assert deliveries[by_kind["png"]]["delivery"] == "native_image"
    assert deliveries[by_kind["scan_pdf"]]["delivery"] == "page_images"
    assert deliveries[by_kind["pdf"]]["delivery"] == "text"
    for kind in ("png", "txt", "pdf", "scan_pdf", "docx"):
        assert TOKENS[kind].lower() in reply.lower(), (kind, reply)
    if "doc" in by_kind:
        assert (deliveries[by_kind["doc"]]["delivery"], deliveries[by_kind["doc"]]["reason"]) == (
            "notice", "claude_only_format")


def test_gpt_oss_delivery(env):
    sid = _session(env, GPT_OSS)
    kinds = ["txt", "csv", "png"]
    ids = [_upload(env, k) for k in kinds]
    reply, deliveries, errors = _ask(env, sid, ids)
    assert not errors, errors
    assert (deliveries[ids[2]]["delivery"], deliveries[ids[2]]["reason"]) == ("notice", "model_no_images")
    for kind in ("txt", "csv"):
        assert TOKENS[kind].lower() in reply.lower(), (kind, reply)


def test_four_turns_three_pdfs_two_images_no_error(env):
    sid = _session(env, OPUS)
    for turn in range(4):
        ids = [_upload(env, "pdf") for _ in range(3)] + [_upload(env, "png"), _upload(env, "jpg")]
        reply, deliveries, errors = _ask(env, sid, ids, f"Turn {turn + 1}: how many files did I attach just now? "
                                                        "Answer with the number only. Do not call any tools.")
        assert not errors, (turn, errors)
        assert reply.strip(), turn


def test_rebuild_after_cache_clear_answers_pdf_and_xlsx(env):
    import agenticops.web.app as webapp
    sid = _session(env, OPUS)
    ids = [_upload(env, "pdf"), _upload(env, "xlsx")]
    _, _, errors = _ask(env, sid, ids, "Keep these two files in mind. Reply OK. Do not call any tools.")
    assert not errors
    webapp._chat_sessions.remove(sid)          # the agent is rebuilt from the stored history on the next turn
    reply, _, errors = _ask(env, sid, [], "What code word is in the PDF I sent earlier, and which one is in the "
                                          "spreadsheet? Do not call any tools.")
    assert not errors
    assert TOKENS["pdf"].lower() in reply.lower() and TOKENS["xlsx"].lower() in reply.lower(), reply
