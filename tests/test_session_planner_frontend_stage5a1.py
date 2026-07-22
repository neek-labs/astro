from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frontend_source() -> str:
    return (ROOT / "session-planner.js").read_text(encoding="utf-8")


def frontend_styles() -> str:
    return (ROOT / "style.css").read_text(encoding="utf-8")


def test_nightly_cards_use_closed_native_disclosures() -> None:
    source = frontend_source()
    assert 'document.createElement("details")' in source
    assert 'disclosure.className = "session-planner-night-details"' in source
    assert 'document.createElement("summary")' in source
    assert 'summary.className = "session-planner-night-summary"' in source
    assert "disclosure.open" not in source
    assert 'setAttribute("open"' not in source


def test_collapsed_summary_contains_decision_fields() -> None:
    source = frontend_source()
    assert "formatDisplayDate(night.date, night.weekday, timezone)" in source
    assert "formatScore(recommendation.score)" in source
    assert "confidence`" in source
    assert "conditions.bestWindowStart" in source
    assert 'appendCompactMetric(weather, "Clouds"' in source
    assert 'appendCompactMetric(weather, "Wind"' in source
    assert 'appendCompactMetric(weather, "Moon"' in source
    assert 'label.textContent = "Suggested target: ";' in source
    assert "selectPriorityWarning(night, validTargets[0])" in source


def test_expanded_content_has_required_hierarchy_and_nested_reasoning() -> None:
    source = frontend_source()
    assert 'createExpandedSection("Conditions"' in source
    assert 'createExpandedSection("Target recommendations"' in source
    assert 'createExpandedSection("Planning notes"' in source
    assert 'createConditionGroup("Observing window"' in source
    assert 'createConditionGroup("Weather"' in source
    assert 'createConditionGroup("Environment"' in source
    assert 'disclosure.className = "session-planner-target-reasoning"' in source
    assert 'summary.textContent = "Why this target?"' in source
    assert "validTargets.slice(1).forEach" in source


def test_structured_timestamps_and_readable_units_are_used() -> None:
    source = frontend_source()
    assert "formatTimeRange(conditions.bestWindowStart, conditions.bestWindowEnd" in source
    assert "formatTimeRange(primary.usableWindowOverlapStart, primary.usableWindowOverlapEnd" in source
    assert "formatLocalTime(primary.maximumAltitudeTime, timezone)" in source
    assert 'hour12: true' in source
    assert 'timeZone: timezone || "America/Edmonton"' in source
    assert " km/h" in source
    assert "°C" in source
    assert "° high" in source
    assert "levelSymbol" not in source


def test_progressive_disclosure_has_focus_and_mobile_styles() -> None:
    styles = frontend_styles()
    assert ".session-planner-night-summary:focus-visible" in styles
    assert ".session-planner-target-reasoning > summary:focus-visible" in styles
    assert ".session-planner-condition-groups" in styles
    assert "grid-template-columns: 1fr;" in styles
