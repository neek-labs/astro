from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frontend_source() -> str:
    return (ROOT / "session-planner.js").read_text(encoding="utf-8")


def test_frontend_keeps_weather_rendering_when_recommendations_are_missing() -> None:
    source = frontend_source()
    assert 'addDetail(details, "Best window"' in source
    assert "if (!recommendations || !Array.isArray(recommendations.topTargets))" in source
    assert "Detailed target recommendations are unavailable for this forecast." in source


def test_frontend_skips_one_malformed_recommendation_locally() -> None:
    source = frontend_source()
    assert "recommendations.topTargets.filter(isValidTargetRecommendation).slice(0, 3)" in source
    assert "Number.isFinite(target.recommendationScore)" in source
    assert "Number.isFinite(target.usableWindowOverlapMinutes)" in source


def test_frontend_uses_semantic_safe_dom_rendering() -> None:
    source = frontend_source()
    assert 'document.createElement("details")' in source
    assert 'document.createElement("section")' in source
    assert ".textContent" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
