import asyncio
import json

from app.services.llm import set_llm_overrides
from app.services.sse import format_named, format_typed, heartbeat, with_heartbeats


def test_typed_event_puts_type_in_json_not_event_line():
    raw = format_typed({"type": "init", "totalSteps": 3, "analysisId": "a1"})
    assert raw.startswith("data: ")
    assert "event:" not in raw
    payload = json.loads(raw.split("data: ", 1)[1].strip())
    assert payload["type"] == "init"
    assert payload["analysisId"] == "a1"


def test_named_event_has_event_line():
    raw = format_named("chunk", {"content": "Hello"})
    assert "event: chunk\n" in raw
    assert '"content": "Hello"' in raw


def test_heartbeat_is_sse_comment():
    raw = heartbeat()
    assert raw.startswith(": ")
    assert raw.endswith("\n\n")


def test_with_heartbeats_emits_comment_while_source_is_slow():
    async def slow():
        await asyncio.sleep(0.05)
        yield "data: {\"type\": \"done\"}\n\n"

    async def collect():
        return [item async for item in with_heartbeats(slow(), interval=0.01)]

    items = asyncio.run(collect())
    assert any(i.startswith(": ") for i in items)
    assert any("done" in i for i in items)


def test_review_stream_emits_init_result_done(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)

    def fake_json(_system: str, _user: str) -> dict:
        return {
            "summary": "Short NDA.",
            "overallRisk": "yellow",
            "redlines": [
                {
                    "clauseName": "Term",
                    "currentLanguage": "twelve months",
                    "proposedLanguage": "twenty-four months",
                    "rationale": "Prefer a longer term.",
                    "isDealBreaker": False,
                    "nature": "substantive",
                }
            ],
            "missingClauses": [],
            "negotiationPriorities": [],
            "flags": [],
        }

    set_llm_overrides(complete_json=fake_json)
    res = client.post(
        "/api/v1/legal-tools/contract-review/stream",
        headers=auth_header,
        json={
            "documentText": "The term of this Agreement is twelve months.",
            "contractType": "nda",
            "userSide": "recipient",
            "jurisdiction": "US",
        },
    )
    assert res.status_code == 200
    body = res.text
    assert '"type": "init"' in body or '"type":"init"' in body
    assert '"type": "result"' in body or '"type":"result"' in body
    assert '"type": "done"' in body or '"type":"done"' in body
    assert "twelve months" in body
    assert '"grounding": "verified"' in body or '"grounding":"verified"' in body


def test_review_rejects_oversized_document(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)
    res = client.post(
        "/api/v1/legal-tools/contract-review/stream",
        headers=auth_header,
        json={
            "documentText": "x" * 200_001,
            "contractType": "nda",
            "userSide": "recipient",
            "jurisdiction": "US",
        },
    )
    assert res.status_code == 413
    assert res.json()["detail"]["error_code"] == "document_too_large"


def test_chat_stream_named_events_and_done(client, auth_header):
    client.get("/api/v1/auth/me", headers=auth_header)

    async def fake_stream(_system, _messages):
        yield "Hello "
        yield "world"

    set_llm_overrides(stream_tokens=fake_stream)
    res = client.post(
        "/api/v1/stream/chat",
        headers=auth_header,
        json={"messages": [{"role": "user", "content": "Hi"}], "context": "A contract."},
    )
    assert res.status_code == 200
    assert "event: thinking" in res.text
    assert "event: chunk" in res.text
    assert "event: done" in res.text
    assert "Hello " in res.text
