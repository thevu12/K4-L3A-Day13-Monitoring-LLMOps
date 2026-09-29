from app import metrics
from app.metrics import percentile


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_snapshot_exposes_error_and_retrieval_rates(monkeypatch) -> None:
    monkeypatch.setattr(metrics, "TRAFFIC", 9)
    monkeypatch.setattr(metrics, "ERRORS", {"RuntimeError": 1})

    snapshot = metrics.snapshot()

    assert snapshot["error_rate_pct"] == 10.0
    assert snapshot["retrieval_success_rate_pct"] == 90.0
