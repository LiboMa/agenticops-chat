"""Evidence-mode E2E: drive the agent via chat, capture transcript + report.

Soft assertions only (a session completes, an artifact is produced). The
captured artifacts under results/<id>/ are the deliverable for human review.
"""
import json
import pathlib
import time

import requests

from conftest import run_chaos, restore_and_wait, E2E_DIR


def _post_chat_message(client, session_id, prompt) -> str:
    """POST a chat message and accumulate the (SSE or JSON) response as text."""
    url = f"{client.base_url}/api/chat/sessions/{session_id}/messages"
    r = requests.post(url, headers=client._headers(),
                      json={"content": prompt}, stream=True, timeout=600)
    r.raise_for_status()
    chunks = []
    for line in r.iter_lines(decode_unicode=True):
        if line:
            chunks.append(line)
    return "\n".join(chunks)


def test_evidence(client, evidence_scenario):
    sc = evidence_scenario
    results = E2E_DIR / "results" / sc["id"]
    results.mkdir(parents=True, exist_ok=True)
    restore_and_wait(sc)

    try:
        run_chaos(sc["inject"])
        time.sleep(10)

        # NOTE: create body field is `name` (ChatSessionCreate.name); the messages
        # endpoint keys off the STRING `session_id` (UUID), NOT the int `id`.
        session = client.post("/api/chat/sessions", json={"name": f"e2e-{sc['id']}"})
        session_id = session.get("session_id")
        assert session_id, f"no session_id in {session}"

        transcript = _post_chat_message(client, session_id, sc["chat_prompt"])
        (results / "transcript.md").write_text(transcript)

        # Capture newest report as evidence (best-effort).
        try:
            reports = client.get("/api/reports")
            items = reports if isinstance(reports, list) else reports.get("items", [])
            (results / "reports.json").write_text(json.dumps(items[:5], indent=2, default=str))
        except Exception as e:  # noqa: BLE001
            (results / "reports.json").write_text(f"error: {e}")

        # Soft guarantees.
        assert transcript.strip(), "[evidence] empty transcript"
        assert (results / "transcript.md").exists()
    finally:
        restore_and_wait(sc)
