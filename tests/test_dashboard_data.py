from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import dashboard, logging_config


def _record(timestamp: datetime, event: str, correlation_id: str, **fields) -> dict:
    return {
        "ts": timestamp.isoformat().replace("+00:00", "Z"),
        "level": "error" if event == "request_failed" else "info",
        "service": "api",
        "event": event,
        "correlation_id": correlation_id,
        "env": "dev",
        "user_id_hash": "abc123",
        "session_id": "session-01",
        "feature": "qa",
        "model": "fake-llm",
        **fields,
    }


def test_dashboard_aggregates_six_panels_and_ignores_old_or_malformed_lines(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime.now(timezone.utc)
    records = [
        _record(now - timedelta(minutes=3), "request_received", "req-ok"),
        _record(
            now - timedelta(minutes=2),
            "response_sent",
            "req-ok",
            latency_ms=120,
            ttft_ms=40,
            tokens_in=30,
            tokens_out=80,
            cost_usd=0.002,
            quality_score=0.9,
            tool_name="retrieval",
            tool_success=True,
        ),
        _record(now - timedelta(minutes=3), "request_received", "req-fail"),
        _record(
            now - timedelta(minutes=2),
            "request_failed",
            "req-fail",
            error_type="RuntimeError",
            tool_name="retrieval",
            tool_success=False,
        ),
        _record(now - timedelta(hours=2), "request_received", "req-old"),
    ]
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\nnot-json\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    payload = dashboard.build_dashboard_payload(60)

    assert payload["has_data"] is True
    assert payload["panel_count"] == 6
    assert set(payload["panels"]) == {"latency", "traffic", "errors", "cost", "tokens", "quality"}
    assert payload["panels"]["traffic"]["count"] == 2
    assert payload["panels"]["latency"]["p95"] == 120.0
    assert payload["panels"]["errors"]["error_rate_pct"] == 50.0
    assert payload["panels"]["errors"]["retrieval_success_rate_pct"] == 50.0
    assert payload["panels"]["tokens"]["input_total"] == 30
    assert payload["panels"]["tokens"]["output_total"] == 80
    assert len(payload["requests"]) == 2
    assert all(len(point) > 0 for point in payload["panels"]["latency"]["series"])


def test_logs_payload_filters_and_scrubs_records(monkeypatch, tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    record = _record(
        now,
        "request_received",
        "req-safe",
        payload={"message_preview": "email student@vinai.example"},
    )
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    payload = dashboard.build_logs_payload(
        correlation_id="req-safe", event="request_received", limit=10
    )

    assert payload["count"] == 1
    returned = payload["records"][0]
    assert "student@vinai.example" not in json.dumps(returned)
    assert "message_preview" in returned["payload"]
    assert dashboard.build_logs_payload(correlation_id="missing")["count"] == 0


def test_dashboard_payload_scrubs_request_and_error_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime.now(timezone.utc)
    email = "student@vinai.example"
    records = [
        _record(now, "request_received", email, feature=email),
        _record(
            now,
            "request_failed",
            email,
            feature=email,
            error_type=f"Failure for {email}",
            tool_success=False,
        ),
    ]
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    payload = dashboard.build_dashboard_payload(60)
    serialized = json.dumps(payload)

    assert email not in serialized
    assert "[REDACTED_EMAIL]" in serialized


def test_day_window_uses_unique_aligned_time_buckets(
    monkeypatch, tmp_path: Path
) -> None:
    now = datetime.now(timezone.utc)
    records = []
    for hours_ago in range(24):
        timestamp = now - timedelta(hours=hours_ago, minutes=1)
        correlation_id = f"req-{hours_ago:02d}"
        records.extend(
            [
                _record(timestamp, "request_received", correlation_id),
                _record(
                    timestamp,
                    "response_sent",
                    correlation_id,
                    latency_ms=100 + hours_ago,
                    ttft_ms=40,
                    tokens_in=10,
                    tokens_out=20,
                    cost_usd=0.001,
                    quality_score=0.8,
                    tool_success=True,
                ),
            ]
        )
    log_path = tmp_path / "logs.jsonl"
    log_path.write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    payload = dashboard.build_dashboard_payload(1440)
    traffic_series = payload["panels"]["traffic"]["series"]

    assert sum(point["value"] for point in traffic_series) == 24
    assert len({point["label"] for point in traffic_series}) == len(traffic_series)


def test_dashboard_has_explicit_empty_state(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "missing.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", log_path)

    payload = dashboard.build_dashboard_payload(60)

    assert payload["has_data"] is False
    assert payload["summary"]["requests"] == 0
    assert payload["panels"]["quality"]["avg"] == 0.0
