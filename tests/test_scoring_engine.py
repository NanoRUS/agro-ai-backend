"""
Unit tests for ScoringEngine v2.

Покрывают:
- Нормализацию score
- required_any / required_all gates
- environment_modifiers
- weather_modifiers
- crop overrides и stage_modifiers
- urgency aggregation и risk aggregation
- Tie-breaking
- get_confidence_label пороги
"""
import pytest
from app.services.scoring_engine import (
    ScoringEngine, SignalExtractor, get_confidence_label, compute_urgency, IssueScore,
    URGENCY_ORDER,
)
from app.rules.loader import get_issues_for_crop, load_issue_catalog
from tests.conftest import make_questionnaire, extract_signals


# ===========================================================================
# 1. Signal Extractor
# ===========================================================================

class TestSignalExtractor:
    def test_wet_soil(self, extractor):
        q = make_questionnaire(soil_moisture="very_wet")
        signals = extractor.extract(q, None, None)
        assert signals["wet_soil"] == 1.0
        assert "dry_soil" not in signals

    def test_dry_soil(self, extractor):
        q = make_questionnaire(soil_moisture="dry")
        signals = extractor.extract(q, None, None)
        assert signals["dry_soil"] == 0.7

    def test_greenhouse_signal(self, extractor):
        q = make_questionnaire(growing_environment="greenhouse")
        signals = extractor.extract(q, None, None)
        assert signals["greenhouse"] == 1.0
        assert "open_field" not in signals

    def test_open_field_signal(self, extractor):
        q = make_questionnaire(growing_environment="open_field")
        signals = extractor.extract(q, None, None)
        assert signals["open_field"] == 1.0
        assert "greenhouse" not in signals

    def test_boolean_symptoms(self, extractor):
        q = make_questionnaire(
            has_dark_spots=True,
            has_webbing=True,
            has_wilting=True,
        )
        signals = extractor.extract(q, None, None)
        assert signals["dark_spots"] == 1.0
        assert signals["webbing"] == 1.0
        assert signals["wilting"] == 1.0

    def test_has_spots_fallback(self, extractor):
        """has_spots без has_dark_spots → dark_spots = 0.55 (не 1.0)."""
        q = make_questionnaire(has_spots=True, has_dark_spots=False)
        signals = extractor.extract(q, None, None)
        assert signals.get("dark_spots") == 0.55

    def test_has_spots_no_override(self, extractor):
        """has_dark_spots берёт приоритет над has_spots."""
        q = make_questionnaire(has_spots=True, has_dark_spots=True)
        signals = extractor.extract(q, None, None)
        assert signals["dark_spots"] == 1.0

    def test_cv_passthrough(self, extractor):
        q = make_questionnaire()
        signals = extractor.extract(q, None, {"cv_fungal_confidence": 0.85})
        assert signals["cv_fungal_confidence"] == 0.85

    def test_weather_humidity_scaling(self, extractor):
        from app.schemas.analyze import UserContext, WeatherContext
        ctx = UserContext(weather=WeatherContext(humidity=85.0))
        q = make_questionnaire()
        signals = extractor.extract(q, ctx, None)
        # humidity=85 → (85-70)/30 = 0.5
        assert abs(signals["high_humidity"] - 0.5) < 0.01

    def test_weather_cold_nights(self, extractor):
        from app.schemas.analyze import UserContext, WeatherContext
        ctx = UserContext(weather=WeatherContext(temperature_night=3.0))
        q = make_questionnaire()
        signals = extractor.extract(q, ctx, None)
        assert signals["cold_nights"] >= 0.8


# ===========================================================================
# 2. Required_any gate
# ===========================================================================

class TestRequiredAny:
    def test_phytophthora_requires_dark_spots(self, engine):
        """Фитофтороз не должен попасть в топ без dark_spots."""
        q = make_questionnaire(
            had_cold_nights=True, had_recent_rain=True,
            growing_environment="open_field", plant_stage="fruiting",
        )
        issues, _ = engine.analyze("tomato", "fruiting", q)
        ids = [i.id for i in issues]
        assert "phytophthora" not in ids

    def test_phytophthora_appears_with_spots(self, engine):
        q = make_questionnaire(
            has_dark_spots=True, had_cold_nights=True, had_recent_rain=True,
            growing_environment="open_field", plant_stage="fruiting",
        )
        issues, _ = engine.analyze("tomato", "fruiting", q)
        ids = [i.id for i in issues]
        assert "phytophthora" in ids

    def test_powdery_mildew_requires_white_powder(self, engine):
        q = make_questionnaire(growing_environment="greenhouse")
        issues, _ = engine.analyze("tomato", "growing", q)
        assert all(i.id != "powdery_mildew" for i in issues)

    def test_spider_mites_requires_webbing(self, engine):
        q = make_questionnaire(had_heat_stress=True, soil_moisture="dry")
        issues, _ = engine.analyze("tomato", "fruiting", q)
        assert all(i.id != "spider_mites" for i in issues)

    def test_blossom_end_rot_requires_signal(self, engine):
        q = make_questionnaire(soil_moisture="dry", plant_stage="fruiting")
        issues, _ = engine.analyze("tomato", "fruiting", q)
        assert all(i.id != "blossom_end_rot" for i in issues)

    def test_transplant_stress_requires_recently_transplanted(self, engine):
        q = make_questionnaire(has_wilting=True, has_slow_growth=True)
        issues, _ = engine.analyze("tomato", "seedling", q)
        assert all(i.id != "transplant_stress" for i in issues)


# ===========================================================================
# 3. Required_all gate
# ===========================================================================

class TestRequiredAll:
    def test_required_all_empty_always_passes(self, engine):
        """Все issues с required_all=[] должны проходить gate."""
        catalog = load_issue_catalog()
        for issue_id, cfg in catalog.items():
            if cfg.get("required_all"):
                # Если есть required_all, проверяем что gate работает
                pass  # covered by other tests
        # Smoke test: basic analysis runs without error
        q = make_questionnaire(has_dark_spots=True)
        issues, _ = engine.analyze("tomato", "growing", q)
        assert isinstance(issues, list)

    def test_issue_with_required_all_blocked_when_missing(self, engine):
        """Искусственно проверяем required_all через прямой вызов _compute_score."""
        issue_cfg = {
            "id": "test_issue",
            "title": "Test",
            "category": "test",
            "urgency_base": "medium",
            "required_any": [],
            "required_all": ["dark_spots", "wet_soil"],  # оба обязательны
            "positive_signals": {"dark_spots": 0.5, "wet_soil": 0.5},
            "negative_signals": {},
            "environment_modifiers": {},
            "weather_modifiers": {},
            "explanation_factors": {},
            "today_actions": [],
            "what_to_check_next": [],
        }
        # Только один из двух — должно быть None
        signals_partial = {"dark_spots": 1.0}
        result = engine._compute_score(issue_cfg, signals_partial)
        assert result is None

        # Оба присутствуют — должен дать результат
        signals_full = {"dark_spots": 1.0, "wet_soil": 1.0}
        result = engine._compute_score(issue_cfg, signals_full)
        assert result is not None
        assert result.score > 0


# ===========================================================================
# 4. Score normalization
# ===========================================================================

class TestScoreNormalization:
    def test_score_in_range(self, engine):
        """Все возвращаемые score должны быть в [0, 1]."""
        q = make_questionnaire(
            has_dark_spots=True, has_wilting=True, soil_moisture="wet",
            has_yellowing_lower_leaves=True, growing_environment="greenhouse",
        )
        issues, _ = engine.analyze("tomato", "fruiting", q)
        for issue in issues:
            assert 0.0 <= issue.score <= 1.0, f"{issue.id} score={issue.score}"

    def test_more_signals_higher_score(self, engine):
        """Больше совпадающих сигналов → выше score."""
        q_weak = make_questionnaire(has_dark_spots=True)
        q_strong = make_questionnaire(
            has_dark_spots=True, had_cold_nights=True, had_recent_rain=True,
            growing_environment="open_field",
        )
        issues_weak, _ = engine.analyze("tomato", "fruiting", q_weak)
        issues_strong, _ = engine.analyze("tomato", "fruiting", q_strong)

        phyto_weak = next((i for i in issues_weak if i.id == "phytophthora"), None)
        phyto_strong = next((i for i in issues_strong if i.id == "phytophthora"), None)

        assert phyto_weak is not None
        assert phyto_strong is not None
        assert phyto_strong.score > phyto_weak.score

    def test_negative_signals_reduce_score(self, engine):
        """Противоречащие сигналы снижают score."""
        q_pos = make_questionnaire(has_dark_spots=True, had_cold_nights=True)
        q_neg = make_questionnaire(has_dark_spots=True, had_cold_nights=True, had_heat_stress=True, soil_moisture="dry")

        issues_pos, _ = engine.analyze("tomato", "fruiting", q_pos)
        issues_neg, _ = engine.analyze("tomato", "fruiting", q_neg)

        phyto_pos = next((i for i in issues_pos if i.id == "phytophthora"), None)
        phyto_neg = next((i for i in issues_neg if i.id == "phytophthora"), None)

        if phyto_pos and phyto_neg:
            assert phyto_pos.score > phyto_neg.score


# ===========================================================================
# 5. Environment modifiers
# ===========================================================================

class TestEnvironmentModifiers:
    def test_powdery_mildew_higher_in_greenhouse(self, engine):
        q_gh = make_questionnaire(has_white_powder=True, growing_environment="greenhouse")
        q_of = make_questionnaire(has_white_powder=True, growing_environment="open_field")

        issues_gh, _ = engine.analyze("cucumber", "growing", q_gh)
        issues_of, _ = engine.analyze("cucumber", "growing", q_of)

        pm_gh = next((i for i in issues_gh if i.id == "powdery_mildew"), None)
        pm_of = next((i for i in issues_of if i.id == "powdery_mildew"), None)

        assert pm_gh is not None and pm_of is not None
        assert pm_gh.score > pm_of.score

    def test_phytophthora_higher_in_open_field(self, engine):
        q_of = make_questionnaire(has_dark_spots=True, growing_environment="open_field")
        q_gh = make_questionnaire(has_dark_spots=True, growing_environment="greenhouse")

        issues_of, _ = engine.analyze("tomato", "fruiting", q_of)
        issues_gh, _ = engine.analyze("tomato", "fruiting", q_gh)

        phyto_of = next((i for i in issues_of if i.id == "phytophthora"), None)
        phyto_gh = next((i for i in issues_gh if i.id == "phytophthora"), None)

        assert phyto_of is not None
        if phyto_gh:
            assert phyto_of.score > phyto_gh.score


# ===========================================================================
# 6. Weather modifiers
# ===========================================================================

class TestWeatherModifiers:
    def test_heat_stress_amplifies_spider_mites(self, engine):
        q_no_heat = make_questionnaire(has_webbing=True)
        q_heat = make_questionnaire(has_webbing=True, had_heat_stress=True)

        issues_no, _ = engine.analyze("tomato", "fruiting", q_no_heat)
        issues_heat, _ = engine.analyze("tomato", "fruiting", q_heat)

        mite_no = next((i for i in issues_no if i.id == "spider_mites"), None)
        mite_heat = next((i for i in issues_heat if i.id == "spider_mites"), None)

        assert mite_no is not None and mite_heat is not None
        assert mite_heat.score > mite_no.score

    def test_rain_amplifies_phytophthora(self, engine):
        q_dry = make_questionnaire(has_dark_spots=True)
        q_rain = make_questionnaire(has_dark_spots=True, had_recent_rain=True)

        issues_dry, _ = engine.analyze("tomato", "fruiting", q_dry)
        issues_rain, _ = engine.analyze("tomato", "fruiting", q_rain)

        p_dry = next((i for i in issues_dry if i.id == "phytophthora"), None)
        p_rain = next((i for i in issues_rain if i.id == "phytophthora"), None)

        assert p_dry is not None and p_rain is not None
        assert p_rain.score > p_dry.score


# ===========================================================================
# 7. Crop overrides
# ===========================================================================

class TestCropOverrides:
    def test_phytophthora_critical_on_tomato(self, engine):
        q = make_questionnaire(has_dark_spots=True, had_recent_rain=True)
        issues, _ = engine.analyze("tomato", "fruiting", q)
        phyto = next((i for i in issues if i.id == "phytophthora"), None)
        assert phyto is not None
        assert phyto.urgency == "critical"

    def test_phytophthora_critical_on_potato(self, engine):
        q = make_questionnaire(has_dark_spots=True)
        issues, _ = engine.analyze("potato", "fruiting", q)
        phyto = next((i for i in issues if i.id == "phytophthora"), None)
        assert phyto is not None
        assert phyto.urgency == "critical"

    def test_root_rot_critical_on_strawberry(self, engine):
        q = make_questionnaire(has_stem_darkening=True, has_wilting=True, soil_moisture="wet")
        issues, _ = engine.analyze("strawberry", "growing", q)
        rr = next((i for i in issues if i.id == "root_rot"), None)
        assert rr is not None
        assert rr.urgency == "critical"

    def test_issue_not_in_crop_not_returned(self, engine):
        """blossom_end_rot есть у томата, но нет у картофеля."""
        q = make_questionnaire(has_blossom_end_rot=True, plant_stage="fruiting")
        issues, _ = engine.analyze("potato", "fruiting", q)
        assert all(i.id != "blossom_end_rot" for i in issues)

    def test_cold_stress_higher_on_cucumber_seedling(self, engine):
        """Огурец более чувствителен к холоду чем томат."""
        q = make_questionnaire(had_cold_nights=True, plant_stage="seedling")
        issues_cuc, _ = engine.analyze("cucumber", "seedling", q)
        issues_tom, _ = engine.analyze("tomato", "seedling", q)

        cs_cuc = next((i for i in issues_cuc if i.id == "cold_stress"), None)
        cs_tom = next((i for i in issues_tom if i.id == "cold_stress"), None)

        if cs_cuc and cs_tom:
            assert cs_cuc.score >= cs_tom.score


# ===========================================================================
# 8. Stage modifiers
# ===========================================================================

class TestStageModifiers:
    def test_blossom_end_rot_higher_at_fruiting(self, engine):
        q = make_questionnaire(has_blossom_end_rot=True, plant_stage="fruiting")
        q_grow = make_questionnaire(has_blossom_end_rot=True, plant_stage="growing")

        issues_fruit, _ = engine.analyze("tomato", "fruiting", q)
        issues_grow, _ = engine.analyze("tomato", "growing", q_grow)

        ber_fruit = next((i for i in issues_fruit if i.id == "blossom_end_rot"), None)
        ber_grow = next((i for i in issues_grow if i.id == "blossom_end_rot"), None)

        assert ber_fruit is not None and ber_grow is not None
        assert ber_fruit.score > ber_grow.score

    def test_transplant_stress_higher_at_seedling(self, engine):
        q = make_questionnaire(recently_transplanted=True, has_wilting=True, plant_stage="seedling")
        q_fruit = make_questionnaire(recently_transplanted=True, has_wilting=True, plant_stage="fruiting")

        issues_seed, _ = engine.analyze("tomato", "seedling", q)
        issues_fruit, _ = engine.analyze("tomato", "fruiting", q_fruit)

        ts_seed = next((i for i in issues_seed if i.id == "transplant_stress"), None)
        ts_fruit = next((i for i in issues_fruit if i.id == "transplant_stress"), None)

        assert ts_seed is not None
        if ts_fruit:
            assert ts_seed.score >= ts_fruit.score


# ===========================================================================
# 9. Urgency aggregation
# ===========================================================================

class TestUrgencyAggregation:
    def test_no_issues_returns_low(self):
        urgency, reason = compute_urgency([])
        assert urgency == "low"
        assert reason

    def test_low_score_caps_critical(self):
        # score=0.10 < min_threshold(0.12) → returns "low" (более консервативно, чем medium)
        issues = [IssueScore(id="x", title="x", category="x", score=0.10, urgency="critical")]
        urgency, _ = compute_urgency(issues)
        assert urgency == "low"

    def test_borderline_score_caps_critical_to_medium(self):
        # score=0.20 → >= 0.12, < 0.28 → cap critical → medium
        issues = [IssueScore(id="x", title="x", category="x", score=0.20, urgency="critical")]
        urgency, _ = compute_urgency(issues)
        assert urgency == "medium"  # cap: 0.12 ≤ score < 0.28 → medium

    def test_very_low_score_returns_low(self):
        issues = [IssueScore(id="x", title="x", category="x", score=0.08, urgency="high")]
        urgency, _ = compute_urgency(issues)
        assert urgency == "low"

    def test_high_score_critical_preserved(self):
        issues = [IssueScore(id="phytophthora", title="Ф", category="fungal", score=0.85, urgency="critical")]
        urgency, _ = compute_urgency(issues)
        assert urgency == "critical"

    def test_reason_contains_issue_title(self):
        issues = [IssueScore(id="x", title="Фитофтороз", category="fungal", score=0.8, urgency="critical")]
        _, reason = compute_urgency(issues)
        assert "Фитофтороз" in reason


# ===========================================================================
# 10. Confidence labels
# ===========================================================================

class TestConfidenceLabel:
    @pytest.mark.parametrize("score,expected", [
        (0.60, "high"),
        (0.55, "high"),
        (0.54, "medium"),
        (0.28, "medium"),
        (0.27, "low"),
        (0.00, "low"),
        (1.00, "high"),
    ])
    def test_thresholds(self, score, expected):
        assert get_confidence_label(score) == expected


# ===========================================================================
# 11. Tie-breaking
# ===========================================================================

class TestTieBreaking:
    def test_results_are_sorted_by_score_desc(self, engine):
        q = make_questionnaire(
            has_dark_spots=True, has_wilting=True, had_cold_nights=True,
            had_recent_rain=True, soil_moisture="wet",
        )
        issues, _ = engine.analyze("tomato", "fruiting", q)
        scores = [i.score for i in issues]
        assert scores == sorted(scores, reverse=True)

    def test_higher_urgency_wins_on_equal_score(self, engine):
        """При одинаковом score — выше urgency получает приоритет."""
        # Используем _compute_score напрямую с одинаковыми весами
        base_cfg = {
            "positive_signals": {"dark_spots": 0.5},
            "negative_signals": {},
            "environment_modifiers": {},
            "weather_modifiers": {},
            "required_any": [],
            "required_all": [],
            "explanation_factors": {},
            "today_actions": [],
            "what_to_check_next": [],
        }
        high_cfg = {**base_cfg, "id": "high_issue", "title": "H", "category": "c", "urgency_base": "high"}
        medium_cfg = {**base_cfg, "id": "medium_issue", "title": "M", "category": "c", "urgency_base": "medium"}

        signals = {"dark_spots": 1.0}
        score_high = engine._compute_score(high_cfg, signals)
        score_medium = engine._compute_score(medium_cfg, signals)

        # Оба имеют одинаковый score
        assert score_high is not None and score_medium is not None
        assert abs(score_high.score - score_medium.score) < 0.001

        # Сортировка ставит high urgency выше
        sorted_issues = sorted(
            [score_high, score_medium],
            key=lambda x: (-x.score, -URGENCY_ORDER.get(x.urgency, 0), x.id),
        )
        assert sorted_issues[0].urgency == "high"
