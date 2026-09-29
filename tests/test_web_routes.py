from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app import logging_config
from app.main import app


def test_demo_routes_serve_ui_dashboard_and_filtered_logs(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs.jsonl"
    record = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "level": "info",
        "service": "api",
        "event": "request_received",
        "correlation_id": "req-demo-01",
        "env": "dev",
        "user_id_hash": "hash",
        "session_id": "demo",
        "feature": "qa",
        "model": "fake-llm",
        "payload": {"message_preview": "hello"},
    }
    log_path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    async def run() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return (
                await client.get("/"),
                await client.get("/api/dashboard?minutes=60"),
                await client.get("/api/logs?correlation_id=req-demo-01"),
            )

    root, dashboard_response, logs_response = asyncio.run(run())

    assert root.status_code == 200
    assert "LLMOps control room" in root.text
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["panel_count"] == 6
    assert logs_response.status_code == 200
    assert logs_response.json()["records"][0]["correlation_id"] == "req-demo-01"
