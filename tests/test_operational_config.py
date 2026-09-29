from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_slo_defines_consistent_error_budget() -> None:
    config = yaml.safe_load(
        (REPO_ROOT / "config" / "slo.yaml").read_text(encoding="utf-8")
    )
    slo = config["primary_slo"]

    assert slo["target_percent"] + slo["error_budget_percent"] == 100
    assert slo["error_budget"]["example_allowed_bad_events"] == 50
    assert slo["rationale"]


def test_alerts_are_actionable_and_have_matching_runbooks() -> None:
    config = yaml.safe_load(
        (REPO_ROOT / "config" / "alert_rules.yaml").read_text(encoding="utf-8")
    )
    runbook = (REPO_ROOT / "docs" / "alerts.md").read_text(encoding="utf-8")
    alerts = config["alerts"]

    assert len(alerts) == 3
    for alert in alerts:
        assert alert["severity"] in {"warning", "critical"}
        assert alert["condition"]
        assert alert["duration"].endswith("m")
        assert alert["type"] == "symptom-based"
        assert alert["channel"].startswith("slack:#")
        assert alert["owner"]
        assert alert["runbook"].startswith("docs/alerts.md#")
        assert f"## {alert['name']}" in runbook
