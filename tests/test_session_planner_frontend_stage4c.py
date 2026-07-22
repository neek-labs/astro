from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def frontend_source() -> str:
    return (ROOT / "session-planner.js").read_text(encoding="utf-8")


def frontend_html() -> str:
    return (ROOT / "session-planner.html").read_text(encoding="utf-8")


def test_generated_timestamp_replaces_sample_note_in_hero() -> None:
    html = frontend_html()
    source = frontend_source()
    hero = html.split('<section class="session-planner-hero">', 1)[1].split(
        "</section>", 1
    )[0]
    assert html.count('id="session-planner-generated"') == 1
    assert 'id="session-planner-generated"' in hero
    assert "session-planner-sample-note" not in html
    assert "session-planner-sample-note" not in source


def test_frontend_keeps_weather_rendering_when_recommendations_are_missing() -> None:
    source = frontend_source()
    assert '["Best window", formatTimeRange(' in source
    assert "if (!recommendations || !Array.isArray(recommendations.topTargets))" in source
    assert "Detailed target recommendations are unavailable for this forecast." in source


def test_frontend_skips_one_malformed_recommendation_locally() -> None:
    source = frontend_source()
    assert "recommendations.topTargets.filter(isValidTargetRecommendation).slice(0, 3)" in source
    assert "Number.isFinite(target.recommendationScore)" in source
    assert "Number.isFinite(target.usableWindowOverlapMinutes)" in source


def test_frontend_uses_semantic_safe_dom_rendering() -> None:
    source = frontend_source()
    assert 'alternativesHeading.textContent = "Also recommended"' in source
    assert 'validTargets.slice(1).forEach((target) =>' in source
    assert 'document.createElement("section")' in source
    assert ".textContent" in source
    assert "innerHTML" not in source
    assert "insertAdjacentHTML" not in source
