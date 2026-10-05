from claimtriagelab.health import build_health_report


def test_health_report_is_local_zero_cost_and_synthetic_only() -> None:
    report = build_health_report()

    assert report.status == "ok"
    assert report.project == "ClaimTriageLab"
    assert report.mode == "local_research_demo"
    assert report.data_classification == "synthetic_only"
    assert report.service_cost_usd == 0


def test_health_report_is_json_serializable() -> None:
    payload = build_health_report().to_dict()

    assert payload["status"] == "ok"
    assert isinstance(payload["python_version"], str)
