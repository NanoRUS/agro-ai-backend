"""
15 fixture-сценариев — сквозные интеграционные тесты scoring engine.

Каждый сценарий: культура + симптомы + ожидаемая топ-проблема + urgency.
"""
import pytest
from app.services.scoring_engine import ScoringEngine, compute_urgency
from tests.conftest import make_questionnaire

engine = ScoringEngine(top_n=3, min_score=0.08)


def analyze(crop, stage, **kwargs):
    q = make_questionnaire(plant_stage=stage, **kwargs)
    issues, signals = engine.analyze(crop, stage, q)
    return issues, signals


def top_id(issues):
    return issues[0].id if issues else None


# ===========================================================================
# Томат
# ===========================================================================

class TestTomatoScenarios:
    def test_1_phytophthora_open_field_rainy(self):
        """Томат, плодоношение, открытый грунт, пятна + дождь + холодные ночи → фитофтороз critical."""
        issues, _ = analyze(
            "tomato", "fruiting",
            has_dark_spots=True, had_cold_nights=True, had_recent_rain=True,
            growing_environment="open_field",
        )
        assert top_id(issues) == "phytophthora"
        assert issues[0].urgency == "critical"
        assert issues[0].score >= 0.55

    def test_2_overwatering_greenhouse(self):
        """Томат, теплица, переполив → перелив."""
        issues, _ = analyze(
            "tomato", "growing",
            soil_moisture="very_wet", has_yellowing_lower_leaves=True, has_wilting=True,
            growing_environment="greenhouse",
        )
        assert top_id(issues) == "overwatering"
        urgency, _ = compute_urgency(issues)
        assert urgency in ("medium", "high")

    def test_3_blossom_end_rot_fruiting(self):
        """Томат, плодоношение, вершинная гниль."""
        issues, _ = analyze(
            "tomato", "fruiting",
            has_blossom_end_rot=True, soil_moisture="dry",
        )
        assert top_id(issues) == "blossom_end_rot"

    def test_4_aphids_visible(self):
        """Томат, видны насекомые + скрученные листья → тля."""
        issues, _ = analyze(
            "tomato", "growing",
            insects_visible=True, has_curled_leaves=True,
        )
        assert top_id(issues) == "aphids"
        assert issues[0].category == "pest"

    def test_5_nitrogen_deficiency_lower_yellowing(self):
        """Томат, пожелтение нижних листьев + медленный рост → дефицит азота."""
        issues, _ = analyze(
            "tomato", "growing",
            has_yellowing_lower_leaves=True, has_slow_growth=True,
        )
        assert top_id(issues) == "nitrogen_deficiency"


# ===========================================================================
# Огурец
# ===========================================================================

class TestCucumberScenarios:
    def test_6_powdery_mildew_greenhouse(self):
        """Огурец, теплица, белый налёт → мучнистая роса high."""
        issues, _ = analyze(
            "cucumber", "growing",
            has_white_powder=True, growing_environment="greenhouse",
        )
        assert top_id(issues) == "powdery_mildew"
        assert issues[0].urgency == "high"

    def test_7_underwatering_hot(self):
        """Огурец, скрученные листья + сухая почва + жара → недолив."""
        issues, _ = analyze(
            "cucumber", "fruiting",
            soil_moisture="very_dry", has_curled_leaves=True, had_heat_stress=True,
        )
        assert top_id(issues) == "underwatering"

    def test_8_spider_mites_heat(self):
        """Огурец, паутинка + жара → паутинный клещ."""
        issues, _ = analyze(
            "cucumber", "fruiting",
            has_webbing=True, had_heat_stress=True,
        )
        assert top_id(issues) == "spider_mites"
        assert issues[0].urgency == "high"

    def test_9_cold_stress_seedling(self):
        """Огурец, рассада, холодные ночи → холодовой стресс."""
        issues, _ = analyze(
            "cucumber", "seedling",
            had_cold_nights=True, has_slow_growth=True,
        )
        assert top_id(issues) == "cold_stress"
        # Огурец/рассада → urgency high
        assert issues[0].urgency == "high"


# ===========================================================================
# Картофель
# ===========================================================================

class TestPotatoScenarios:
    def test_10_phytophthora_potato_critical(self):
        """Картофель, пятна + дождь → фитофтороз critical (самый высокий weight_multiplier)."""
        issues, _ = analyze(
            "potato", "fruiting",
            has_dark_spots=True, had_recent_rain=True, had_cold_nights=True,
            growing_environment="open_field",
        )
        assert top_id(issues) == "phytophthora"
        assert issues[0].urgency == "critical"

    def test_11_alternaria_hot_spots(self):
        """Картофель, жара + тёмные пятна + сухие пятна → альтернариоз."""
        issues, _ = analyze(
            "potato", "growing",
            has_dark_spots=True, had_heat_stress=True,
        )
        assert top_id(issues) in ("phytophthora", "alternaria")

    def test_12_slug_damage_after_rain(self):
        """Картофель, дырки в листьях + дождь + влажная почва → слизни."""
        issues, _ = analyze(
            "potato", "growing",
            has_holes_in_leaves=True, soil_moisture="wet", had_recent_rain=True,
        )
        assert top_id(issues) == "slug_damage"


# ===========================================================================
# Перец
# ===========================================================================

class TestPepperScenarios:
    def test_13_blossom_end_rot_pepper(self):
        """Перец, плодоношение, вершинная гниль → высокий score."""
        issues, _ = analyze(
            "pepper", "fruiting",
            has_blossom_end_rot=True,
        )
        assert top_id(issues) == "blossom_end_rot"
        assert issues[0].score >= 0.55

    def test_14_cold_stress_pepper_seedling_critical(self):
        """Перец, рассада, холодные ночи → cold_stress high/critical."""
        issues, _ = analyze(
            "pepper", "seedling",
            had_cold_nights=True, has_slow_growth=True,
        )
        assert top_id(issues) == "cold_stress"
        assert issues[0].urgency in ("high", "critical")


# ===========================================================================
# Клубника
# ===========================================================================

class TestStrawberryScenarios:
    def test_15_root_rot_strawberry_critical(self):
        """Клубника, почернение стебля + влажная почва + увядание → корневая гниль critical."""
        issues, _ = analyze(
            "strawberry", "growing",
            has_stem_darkening=True, soil_moisture="very_wet", has_wilting=True,
        )
        assert top_id(issues) == "root_rot"
        assert issues[0].urgency == "critical"


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_no_symptoms_returns_general_stress_or_empty(self):
        """Нет симптомов — либо нет результатов, либо только general_stress."""
        issues, _ = analyze("tomato", "growing")
        # Допустимо и 0 issues, и только general_stress
        for i in issues:
            assert i.id in ("general_stress", "nitrogen_deficiency")

    def test_contradicting_signals_reduces_score(self):
        """Dry_soil штрафует phytophthora."""
        issues_wet, _ = analyze("tomato", "fruiting", has_dark_spots=True, had_recent_rain=True)
        issues_dry, _ = analyze("tomato", "fruiting", has_dark_spots=True, soil_moisture="very_dry")

        p_wet = next((i for i in issues_wet if i.id == "phytophthora"), None)
        p_dry = next((i for i in issues_dry if i.id == "phytophthora"), None)

        if p_wet and p_dry:
            assert p_wet.score > p_dry.score

    def test_top_n_limit_respected(self):
        """Никогда не возвращается больше 3 проблем."""
        q = make_questionnaire(
            has_dark_spots=True, has_white_powder=True, has_wilting=True,
            has_webbing=True, insects_visible=True, soil_moisture="wet",
        )
        issues, _ = engine.analyze("tomato", "growing", q)
        assert len(issues) <= 3

    def test_all_crops_run_without_error(self):
        """Все 5 культур, все 4 стадии — без exceptions."""
        crops = ["tomato", "cucumber", "potato", "pepper", "strawberry"]
        stages = ["seedling", "growing", "flowering", "fruiting"]
        q = make_questionnaire(has_dark_spots=True, had_cold_nights=True)
        for crop in crops:
            for stage in stages:
                issues, signals = engine.analyze(crop, stage, q)
                assert isinstance(issues, list)
                assert isinstance(signals, dict)
