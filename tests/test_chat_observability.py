from __future__ import annotations

import json
import asyncio
from pathlib import Path

import httpx
from structlog.contextvars import bind_contextvars

from app import logging_config
from app.logging_config import get_logger
from app.main import app


def test_chat_response_log_exposes_quality_for_dashboard(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": "Explain observability",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.headers["x-request-id"].startswith("req-")
    assert len(response.headers["x-request-id"]) == 12
    assert float(response.headers["x-response-time-ms"]) >= 0
    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    request_event = next(event for event in events if event["event"] == "request_received")
    response_event = next(event for event in events if event["event"] == "response_sent")
    assert request_event["correlation_id"] == response.headers["x-request-id"]
    assert request_event["user_id_hash"] != "student-01"
    assert request_event["session_id"] == "session-01"
    assert request_event["feature"] == "qa"
    assert request_event["model"] == "claude-sonnet-4-5"
    assert request_event["env"] == "dev"
    assert response_event["quality_score"] == response.json()["quality_score"]
    assert response_event["ttft_ms"] == response.json()["ttft_ms"]
    assert response_event["tool_name"] == "retrieval"
    assert response_event["tool_success"] is True


def test_chat_preserves_request_id_and_scrubs_nested_pii(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    bind_contextvars(correlation_id="stale-request")

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            return await client.post(
                "/chat",
                headers={"x-request-id": "client-request-42"},
                json={
                    "user_id": "student-02",
                    "session_id": "session-02",
                    "feature": "policy",
                    "message": "Email student@vinuni.edu.vn, card 4111 1111 1111 1111",
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "client-request-42"
    raw_log = log_path.read_text(encoding="utf-8")
    assert "stale-request" not in raw_log
    assert "student@vinuni.edu.vn" not in raw_log
    assert "4111 1111 1111 1111" not in raw_log
    assert "[REDACTED_EMAIL]" in raw_log
    assert "[REDACTED_CREDIT_CARD]" in raw_log


def test_exception_traceback_is_scrubbed_before_file_write(
    monkeypatch, tmp_path: Path
) -> None:
    log_path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)
    logger = get_logger()

    try:
        raise ValueError("contact student@vinuni.edu.vn")
    except ValueError:
        logger.error("request_failed", exc_info=True)

    raw_log = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw_log
    assert "[REDACTED_EMAIL]" in raw_log
