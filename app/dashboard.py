from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from . import logging_config
from .pii import scrub_text
from .tracing import tracing_enabled


REPO_ROOT = Path(__file__).resolve().parents[1]
def _log_path() -> Path:
    path = logging_config.LOG_PATH
    return path if path.is_absolute() else REPO_ROOT / path


def _timestamp(record: dict[str, Any]) -> datetime | None:
    value = record.get("ts")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_log_records() -> list[dict[str, Any]]:
    log_path = _log_path()
    if not log_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile / 100 * len(ordered)) - 1))
    return round(ordered[index], 1)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def _bucket_start(timestamp: datetime, bucket_minutes: int) -> datetime:
    bucket_seconds = bucket_minutes * 60
    epoch_seconds = int(timestamp.timestamp())
    return datetime.fromtimestamp(
        epoch_seconds - (epoch_seconds % bucket_seconds), tz=timezone.utc
    )


def _window_records(records: list[dict[str, Any]], minutes: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return [record for record in records if (timestamp := _timestamp(record)) and timestamp >= cutoff]


def _series(records: list[dict[str, Any]], minutes: int) -> dict[str, list[dict[str, Any]]]:
    bucket_minutes = max(1, math.ceil(minutes / 12))
    now = datetime.now(timezone.utc)
    start = _bucket_start(now - timedelta(minutes=minutes), bucket_minutes)
    end = _bucket_start(now, bucket_minutes)
    buckets: list[datetime] = []
    cursor = start
    while cursor <= end:
        buckets.append(cursor)
        cursor += timedelta(minutes=bucket_minutes)

    grouped: dict[datetime, dict[str, list[float]]] = defaultdict(
        lambda: {
            "latency": [],
            "ttft": [],
            "cost": [],
            "quality": [],
            "tokens_in": [],
            "tokens_out": [],
        }
    )
    traffic: dict[datetime, int] = defaultdict(int)
    errors: dict[datetime, int] = defaultdict(int)
    for record in records:
        timestamp = _timestamp(record)
        if not timestamp:
            continue
        bucket = _bucket_start(timestamp, bucket_minutes)
        event = record.get("event")
        if event == "request_received":
            traffic[bucket] += 1
        if event == "request_failed":
            errors[bucket] += 1
        if event != "response_sent":
            continue
        for field, key in (
            ("latency", "latency_ms"),
            ("ttft", "ttft_ms"),
            ("cost", "cost_usd"),
            ("quality", "quality_score"),
        ):
            value = record.get(key)
            if isinstance(value, (int, float)):
                grouped[bucket][field].append(float(value))
        tokens_in = record.get("tokens_in")
        tokens_out = record.get("tokens_out")
        if isinstance(tokens_in, (int, float)):
            grouped[bucket]["tokens_in"].append(float(tokens_in))
        if isinstance(tokens_out, (int, float)):
            grouped[bucket]["tokens_out"].append(float(tokens_out))

    latency = []
    traffic_series = []
    cost = []
    quality = []
    tokens = []
    label_format = "%m-%d %H:%M" if minutes > 180 else "%H:%M"
    for bucket in buckets:
        label = bucket.strftime(label_format)
        values = grouped[bucket]
        latency.append(
            {
                "label": label,
                "p50": _percentile(values["latency"], 50),
                "p95": _percentile(values["latency"], 95),
                "p99": _percentile(values["latency"], 99),
                "ttft": _percentile(values["ttft"], 95),
            }
        )
        traffic_series.append(
            {"label": label, "value": traffic[bucket], "errors": errors[bucket]}
        )
        cost.append({"label": label, "value": round(sum(values["cost"]), 5)})
        quality.append({"label": label, "value": _mean(values["quality"])})
        tokens.append(
            {
                "label": label,
                "input": round(sum(values["tokens_in"])),
                "output": round(sum(values["tokens_out"])),
            }
        )
    return {"latency": latency, "traffic": traffic_series, "cost": cost, "quality": quality, "tokens": tokens}


def _read_config(name: str, default: dict[str, Any]) -> dict[str, Any]:
    path = REPO_ROOT / "config" / name
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, yaml.YAMLError):
        return default
    return payload if isinstance(payload, dict) else default


def build_dashboard_payload(minutes: int = 60) -> dict[str, Any]:
    minutes = max(5, min(minutes, 24 * 60))
    records = _window_records(load_log_records(), minutes)
    received = [record for record in records if record.get("event") == "request_received"]
    responses = [record for record in records if record.get("event") == "response_sent"]
    failures = [record for record in records if record.get("event") == "request_failed"]
    latencies = [float(record["latency_ms"]) for record in responses if isinstance(record.get("latency_ms"), (int, float))]
    ttft = [float(record["ttft_ms"]) for record in responses if isinstance(record.get("ttft_ms"), (int, float))]
    costs = [float(record["cost_usd"]) for record in responses if isinstance(record.get("cost_usd"), (int, float))]
    input_tokens = [int(record["tokens_in"]) for record in responses if isinstance(record.get("tokens_in"), (int, float))]
    output_tokens = [int(record["tokens_out"]) for record in responses if isinstance(record.get("tokens_out"), (int, float))]
    quality = [float(record["quality_score"]) for record in responses if isinstance(record.get("quality_score"), (int, float))]
    tool_results = [record.get("tool_success") for record in responses + failures if record.get("tool_success") is not None]
    successful_tools = sum(result is True for result in tool_results)
    total_requests = len(received)
    completed_requests = len(responses) + len(failures)
    error_denominator = max(total_requests, completed_requests)
    error_rate = (
        round((len(failures) / error_denominator) * 100, 2)
        if error_denominator
        else 0.0
    )
    retrieval_rate = round((successful_tools / len(tool_results)) * 100, 2) if tool_results else 0.0
    dashboard_config = _read_config("dashboard.yaml", {})
    slo_config = _read_config("slo.yaml", {})
    alert_config = _read_config("alert_rules.yaml", {})
    primary_slo = slo_config.get("primary_slo", {})
    alerts = []
    current_values = {"latency_p95": _percentile(latencies, 95), "error_rate_pct": error_rate, "quality_avg": _mean(quality)}
    for alert in alert_config.get("alerts", []):
        condition = str(alert.get("condition", ""))
        metric = condition.split(" ", 1)[0]
        value = current_values.get(metric)
        active = False
        if value is not None:
            if " > " in condition:
                active = value > float(condition.rsplit(" ", 1)[-1])
            elif " < " in condition:
                active = value < float(condition.rsplit(" ", 1)[-1])
        alerts.append({**alert, "threshold_breached": active, "value": value})
    panel_configs = {
        panel.get("id"): panel
        for panel in dashboard_config.get("dashboard", {}).get("panels", [])
        if isinstance(panel, dict) and panel.get("id")
    }
    latency_panel = panel_configs.get("latency", {})
    traffic_panel = panel_configs.get("traffic", {})
    errors_panel = panel_configs.get("errors", {})
    cost_panel = panel_configs.get("cost", {})
    tokens_panel = panel_configs.get("tokens", {})
    quality_panel = panel_configs.get("quality", {})
    chart_series = _series(records, minutes)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_minutes": minutes,
        "window": {"minutes": minutes, "start": (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()},
        "has_data": bool(received or responses or failures),
        "source": str(_log_path().relative_to(REPO_ROOT)) if _log_path().is_relative_to(REPO_ROOT) else str(_log_path()),
        "tracing_enabled": tracing_enabled(),
        "summary": {
            "requests": total_requests,
            "traffic_per_minute": round(total_requests / minutes, 2),
            "latency_p50": _percentile(latencies, 50),
            "latency_p95": _percentile(latencies, 95),
            "latency_p99": _percentile(latencies, 99),
            "ttft_p95": _percentile(ttft, 95),
            "error_rate_pct": error_rate,
            "retrieval_success_rate_pct": retrieval_rate,
            "cost_usd": round(sum(costs), 5),
            "tokens_in": sum(input_tokens),
            "tokens_out": sum(output_tokens),
            "quality_avg": _mean(quality),
        },
        "series": chart_series,
        "panels": {
            "latency": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95), "p99": _percentile(latencies, 99), "ttft_p95": _percentile(ttft, 95), "unit": latency_panel.get("unit", "ms"), "threshold": latency_panel.get("threshold", {}), "series": chart_series["latency"]},
            "traffic": {"count": total_requests, "rate_per_minute": round(total_requests / minutes, 2), "unit": traffic_panel.get("unit", "requests_per_minute"), "threshold": traffic_panel.get("threshold", {}), "series": chart_series["traffic"]},
            "errors": {"error_rate_pct": error_rate, "retrieval_success_rate_pct": retrieval_rate, "breakdown": _error_breakdown(failures), "unit": errors_panel.get("unit", "percent"), "threshold": errors_panel.get("threshold", {}), "series": chart_series["traffic"]},
            "cost": {"total_usd": round(sum(costs), 5), "unit": cost_panel.get("unit", "usd"), "threshold": cost_panel.get("threshold", {}), "series": chart_series["cost"]},
            "tokens": {"input_total": sum(input_tokens), "output_total": sum(output_tokens), "unit": tokens_panel.get("unit", "tokens"), "threshold": tokens_panel.get("threshold", {}), "series": chart_series["tokens"]},
            "quality": {"avg": _mean(quality), "unit": quality_panel.get("unit", "score_0_to_1"), "threshold": quality_panel.get("threshold", {}), "series": chart_series["quality"]},
        },
        "requests": _recent_requests(records),
        "alerts": alerts,
        "slo": {
            "name": primary_slo.get("name", "fast_successful_requests"),
            "target_percent": primary_slo.get("target_percent", 99.5),
            "error_budget_percent": primary_slo.get("error_budget_percent", 0.5),
            "window": primary_slo.get("window", "28d"),
        },
        "panel_count": len(panel_configs),
    }
    return _safe_value(payload)


def _error_breakdown(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        counts[str(record.get("error_type") or "unknown")] += 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _recent_requests(records: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    received = {record.get("correlation_id"): record for record in records if record.get("event") == "request_received"}
    outcomes = [record for record in records if record.get("event") in {"response_sent", "request_failed"}]
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        correlation_id = outcome.get("correlation_id")
        request = received.get(correlation_id, {})
        timestamp = _timestamp(outcome) or _timestamp(request)
        rows.append(
            {
                "ts": timestamp.isoformat() if timestamp else outcome.get("ts", ""),
                "correlation_id": correlation_id or "unknown",
                "event": outcome.get("event", "unknown"),
                "status": "error" if outcome.get("event") == "request_failed" else "ok",
                "feature": outcome.get("feature") or request.get("feature") or "-",
                "model": outcome.get("model") or request.get("model") or "-",
                "latency_ms": outcome.get("latency_ms"),
                "quality_score": outcome.get("quality_score"),
                "error_type": outcome.get("error_type"),
                "tool_success": outcome.get("tool_success"),
            }
        )
    return sorted(rows, key=lambda row: row["ts"], reverse=True)[:limit]


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, dict):
        return {key: _safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


LOG_FIELDS = {
    "ts", "level", "service", "event", "correlation_id", "env", "user_id_hash",
    "session_id", "feature", "model", "latency_ms", "ttft_ms", "tokens_in",
    "tokens_out", "cost_usd", "quality_score", "error_type", "tool_name",
    "tool_success", "payload",
}


def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
    return _safe_value({key: record.get(key) for key in LOG_FIELDS if key in record})


def build_logs_payload(
    limit: int = 100,
    query: str = "",
    correlation_id: str = "",
    event: str = "",
    level: str = "",
) -> dict[str, Any]:
    records = sorted(load_log_records(), key=lambda record: record.get("ts", ""), reverse=True)
    if correlation_id:
        records = [record for record in records if record.get("correlation_id") == correlation_id]
    if event:
        records = [record for record in records if record.get("event") == event]
    if level:
        records = [record for record in records if record.get("level") == level]
    if query.strip():
        needle = query.lower().strip()
        records = [record for record in records if needle in json.dumps(record, ensure_ascii=False).lower()]
    bounded_limit = max(1, min(limit, 500))
    return {"source": "data/logs.jsonl", "count": min(len(records), bounded_limit), "records": [_safe_record(record) for record in records[:bounded_limit]]}
