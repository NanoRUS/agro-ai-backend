"""
Scoring Engine v2 — изолированный модуль ранжирования проблем.

Ключевые улучшения v2:
- Нормализация по max_possible (не-CV сигналы) → scores реально сравнимы
- required_all — все перечисленные сигналы должны присутствовать
- environment_modifiers — мультипликаторы по среде выращивания
- weather_modifiers — мультипликаторы по погодным условиям (плавное масштабирование)
- Улучшенный urgency aggregation с risk aggregation
- Tie-breaking: score DESC → urgency_order DESC → issue_id ASC (детерминированный)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from app.rules.loader import get_issues_for_crop
from app.schemas.analyze import QuestionnaireAnswers, UserContext, ConfidenceLabel

URGENCY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}
CV_SIGNAL_PREFIX = "cv_"
# CV bonus can contribute at most this fraction on top of normalized core score
CV_MAX_BONUS = 0.20


@dataclass
class IssueScore:
    id: str
    title: str
    category: str
    score: float           # [0.0 – 1.0] normalized, comparable across issues
    urgency: str           # critical | high | medium | low
    contributing_signals: dict[str, float] = field(default_factory=dict)
    explanation_factors: dict[str, str] = field(default_factory=dict)
    today_actions: list[str] = field(default_factory=list)
    what_to_check_next: list[str] = field(default_factory=list)
    video_tone: str = "calm_practical"


class SignalExtractor:
    """Маппит анкету + контекст + CV output → Dict[signal_key, float 0–1]."""

    _BOOL_SIGNALS: dict[str, str] = {
        "has_dark_spots": "dark_spots",
        "has_white_powder": "white_powder",
        "has_holes_in_leaves": "holes_in_leaves",
        "has_webbing": "webbing",
        "insects_visible": "insects_visible",
        "has_yellowing_lower_leaves": "yellow_leaves_lower",
        "has_uniform_yellowing": "yellow_leaves_uniform",
        "has_leaf_edge_burn": "leaf_edge_burn",
        "has_curled_leaves": "curled_leaves",
        "has_wilting": "wilting",
        "has_stem_darkening": "stem_darkening",
        "has_fruit_rot": "fruit_rot",
        "has_blossom_end_rot": "blossom_end_rot",
        "has_slow_growth": "slow_growth",
        "had_cold_nights": "cold_nights",
        "had_heat_stress": "heat_stress",
        "had_recent_rain": "recent_rain",
        "recently_transplanted": "recently_transplanted",
        "recently_fertilized": "recently_fertilized",
    }

    def extract(
        self,
        questionnaire: QuestionnaireAnswers,
        user_context: UserContext | None,
        cv_output: dict[str, float] | None,
    ) -> dict[str, float]:
        signals: dict[str, float] = {}

        # Почва
        moisture_map: dict[str, dict] = {
            "very_wet": {"wet_soil": 1.0},
            "wet": {"wet_soil": 0.7},
            "normal": {},
            "dry": {"dry_soil": 0.7},
            "very_dry": {"dry_soil": 1.0},
        }
        signals.update(moisture_map.get(questionnaire.soil_moisture, {}))

        # Среда выращивания
        signals["greenhouse" if questionnaire.growing_environment == "greenhouse" else "open_field"] = 1.0

        # Булевые симптомы
        for field_name, signal_key in self._BOOL_SIGNALS.items():
            if getattr(questionnaire, field_name, False):
                signals[signal_key] = 1.0

        # has_spots без has_dark_spots → умеренный сигнал
        if questionnaire.has_spots and "dark_spots" not in signals:
            signals["dark_spots"] = 0.55

        # Погода из контекста (не перебивает ручные флаги, только усиливает)
        if user_context and user_context.weather:
            w = user_context.weather
            if w.humidity and w.humidity > 70:
                val = min(1.0, (w.humidity - 70) / 30)
                signals["high_humidity"] = max(signals.get("high_humidity", 0), val)
            if w.temperature_night and w.temperature_night < 8:
                signals["cold_nights"] = max(signals.get("cold_nights", 0), 0.8)
            if w.temperature_day and w.temperature_day > 35:
                signals["heat_stress"] = max(signals.get("heat_stress", 0), 0.8)
            if w.recent_rain_mm and w.recent_rain_mm > 5:
                val = min(1.0, w.recent_rain_mm / 15)
                signals["recent_rain"] = max(signals.get("recent_rain", 0), val)

        # CV output
        if cv_output:
            for key in ("cv_fungal_confidence", "cv_pest_confidence",
                        "cv_nutrient_deficiency_confidence", "cv_bacterial_confidence",
                        "cv_healthy_confidence"):
                if key in cv_output:
                    signals[key] = float(cv_output[key])

        return signals


class ScoringEngine:
    def __init__(self, top_n: int = 3, min_score: float = 0.08):
        self.top_n = top_n
        self.min_score = min_score
        self._extractor = SignalExtractor()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(
        self,
        crop: str,
        plant_stage: str | None,
        questionnaire: QuestionnaireAnswers,
        user_context: UserContext | None = None,
        cv_output: dict[str, float] | None = None,
    ) -> tuple[list[IssueScore], dict[str, float]]:
        signals = self._extractor.extract(questionnaire, user_context, cv_output)
        scored = self.score_issues(crop, plant_stage, signals)
        return scored, signals

    def score_issues(
        self,
        crop: str,
        plant_stage: str | None,
        signals: dict[str, float],
    ) -> list[IssueScore]:
        issues = get_issues_for_crop(crop, plant_stage)
        scored: list[IssueScore] = []

        for cfg in issues:
            result = self._compute_score(cfg, signals)
            if result is not None:
                scored.append(result)

        # Sort: score DESC, urgency_order DESC, id ASC (deterministic)
        scored.sort(
            key=lambda x: (-x.score, -URGENCY_ORDER.get(x.urgency, 0), x.id),
        )
        return scored[: self.top_n]

    def score_issues_debug(
        self,
        crop: str,
        plant_stage: str | None,
        signals: dict[str, float],
    ) -> dict[str, Any]:
        """Full debug breakdown — все issues с пошаговым score breakdown, без top_n фильтра."""
        from app.rules.loader import get_all_issues_for_crop
        issues = get_all_issues_for_crop(crop, plant_stage)

        passed: list[dict] = []
        gated: list[dict] = []

        for cfg in issues:
            breakdown = self._compute_score_debug(cfg, signals)
            if breakdown["gated_by"]:
                gated.append(breakdown)
            else:
                passed.append(breakdown)

        passed.sort(key=lambda x: -x["final_score"])
        top = passed[: self.top_n]

        return {
            "signals": signals,
            "scored_issues": passed,
            "gated_issues": gated,
            "top_issues_ids": [i["id"] for i in top],
        }

    # ------------------------------------------------------------------
    # Core scoring
    # ------------------------------------------------------------------

    def _compute_score_debug(self, issue: dict[str, Any], signals: dict[str, float]) -> dict[str, Any]:
        """Возвращает полный breakdown для debug panel / calibration."""
        pos_signals: dict[str, float] = issue.get("positive_signals", {})
        neg_signals: dict[str, float] = issue.get("negative_signals", {})

        required_any: list[str] = issue.get("required_any", [])
        required_all: list[str] = issue.get("required_all", [])

        gated_by: str | None = None
        if required_any and not any(signals.get(s, 0) > 0.3 for s in required_any):
            gated_by = "required_any"
        elif required_all and not all(signals.get(s, 0) > 0.3 for s in required_all):
            gated_by = "required_all"

        core_pos = {k: v for k, v in pos_signals.items() if not k.startswith(CV_SIGNAL_PREFIX)}
        cv_pos = {k: v for k, v in pos_signals.items() if k.startswith(CV_SIGNAL_PREFIX)}
        max_core = sum(core_pos.values()) or 1.0

        raw_core = sum(signals.get(s, 0) * w for s, w in core_pos.items())
        raw_penalty = sum(signals.get(s, 0) * abs(w) for s, w in neg_signals.items())
        normalized_core = max(0.0, (raw_core - raw_penalty)) / max_core

        max_cv = sum(cv_pos.values())
        cv_bonus = ((sum(signals.get(s, 0) * w for s, w in cv_pos.items()) / max_cv) * CV_MAX_BONUS) if max_cv > 0 else 0.0
        base_score = min(1.0, normalized_core + cv_bonus)

        multiplier = issue.get("_weight_multiplier", 1.0)
        base_score *= multiplier

        env_factors_applied: dict[str, float] = {}
        for env_key, factor in issue.get("environment_modifiers", {}).items():
            if signals.get(env_key, 0) > 0.5:
                base_score *= factor
                env_factors_applied[env_key] = factor

        weather_factors_applied: dict[str, float] = {}
        for wx_key, max_factor in issue.get("weather_modifiers", {}).items():
            sig_val = signals.get(wx_key, 0)
            if sig_val > 0:
                smooth_factor = 1.0 + (max_factor - 1.0) * sig_val
                base_score *= smooth_factor
                weather_factors_applied[wx_key] = round(smooth_factor, 3)

        final_score = round(max(0.0, min(1.0, base_score)), 4)

        active_signals = {s: round(signals.get(s, 0), 3) for s in list(core_pos) + list(cv_pos)
                         if signals.get(s, 0) > 0}
        penalty_signals = {s: round(-signals.get(s, 0), 3) for s in neg_signals if signals.get(s, 0) > 0}

        return {
            "id": issue["id"],
            "title": issue["title"],
            "urgency": issue["urgency_base"],
            "gated_by": gated_by,
            "final_score": final_score,
            "breakdown": {
                "raw_core": round(raw_core, 4),
                "raw_penalty": round(raw_penalty, 4),
                "max_core": round(max_core, 4),
                "normalized_core": round(normalized_core, 4),
                "cv_bonus": round(cv_bonus, 4),
                "crop_stage_multiplier": round(multiplier, 3),
                "env_factors": env_factors_applied,
                "weather_factors": weather_factors_applied,
            },
            "active_signals": active_signals,
            "penalty_signals": penalty_signals,
            "required_any": required_any,
            "required_all": required_all,
        }

    def _compute_score(self, issue: dict[str, Any], signals: dict[str, float]) -> IssueScore | None:
        pos_signals: dict[str, float] = issue.get("positive_signals", {})
        neg_signals: dict[str, float] = issue.get("negative_signals", {})

        # ---- Gate 1: required_any ----
        required_any: list[str] = issue.get("required_any", [])
        if required_any and not any(signals.get(s, 0) > 0.3 for s in required_any):
            return None

        # ---- Gate 2: required_all (NEW) ----
        required_all: list[str] = issue.get("required_all", [])
        if required_all and not all(signals.get(s, 0) > 0.3 for s in required_all):
            return None

        # ---- Separate core signals from CV signals ----
        core_pos = {k: v for k, v in pos_signals.items() if not k.startswith(CV_SIGNAL_PREFIX)}
        cv_pos = {k: v for k, v in pos_signals.items() if k.startswith(CV_SIGNAL_PREFIX)}

        max_core = sum(core_pos.values())
        if max_core <= 0:
            return None

        # ---- Compute normalized core score ----
        raw_core = sum(signals.get(s, 0) * w for s, w in core_pos.items())
        raw_penalty = sum(signals.get(s, 0) * abs(w) for s, w in neg_signals.items())
        normalized_core = max(0.0, (raw_core - raw_penalty)) / max_core

        # ---- CV bonus (normalized to CV_MAX_BONUS ceiling) ----
        max_cv = sum(cv_pos.values())
        if max_cv > 0:
            raw_cv = sum(signals.get(s, 0) * w for s, w in cv_pos.items())
            cv_bonus = (raw_cv / max_cv) * CV_MAX_BONUS
        else:
            cv_bonus = 0.0

        base_score = min(1.0, normalized_core + cv_bonus)

        # ---- Apply crop/stage multiplier ----
        multiplier: float = issue.get("_weight_multiplier", 1.0)
        base_score *= multiplier

        # ---- Environment modifiers (multiplicative, applied if env signal > 0.5) ----
        for env_key, factor in issue.get("environment_modifiers", {}).items():
            if signals.get(env_key, 0) > 0.5:
                base_score *= factor

        # ---- Weather modifiers (smooth: factor scales with signal strength) ----
        for wx_key, max_factor in issue.get("weather_modifiers", {}).items():
            sig_val = signals.get(wx_key, 0)
            if sig_val > 0:
                # At sig_val=1.0 full multiplier; at sig_val=0 no effect
                smooth_factor = 1.0 + (max_factor - 1.0) * sig_val
                base_score *= smooth_factor

        score = round(max(0.0, min(1.0, base_score)), 4)

        if score < self.min_score:
            return None

        # ---- Build contributing signals for transparency ----
        contributing: dict[str, float] = {}
        for sig in list(core_pos) + list(cv_pos):
            val = signals.get(sig, 0)
            if val > 0:
                contributing[sig] = round(val, 3)
        for sig, w in neg_signals.items():
            val = signals.get(sig, 0)
            if val > 0:
                contributing[sig] = round(-val, 3)  # negative = penalty

        # ---- Active explanation factors ----
        active_factors = {
            k: v for k, v in issue.get("explanation_factors", {}).items()
            if signals.get(k, 0) > 0.3
        }

        return IssueScore(
            id=issue["id"],
            title=issue["title"],
            category=issue["category"],
            score=score,
            urgency=issue["urgency_base"],
            contributing_signals=contributing,
            explanation_factors=active_factors,
            today_actions=issue.get("today_actions", []),
            what_to_check_next=issue.get("what_to_check_next", []),
            video_tone=issue.get("video_tone", "calm_practical"),
        )


# ------------------------------------------------------------------
# Confidence + urgency helpers
# ------------------------------------------------------------------

def get_confidence_label(score: float) -> ConfidenceLabel:
    """
    Calibrated for normalized scores (0–1).
    high   ≥ 0.55 — большинство ключевых сигналов совпадают
    medium ≥ 0.28 — часть сигналов совпадает
    low    < 0.28 — слабое совпадение
    """
    if score >= 0.55:
        return "high"
    if score >= 0.28:
        return "medium"
    return "low"


def compute_urgency(scored_issues: list[IssueScore]) -> tuple[str, str]:
    """
    Определяет общий urgency на основе топ-проблем.
    Включает risk aggregation: несколько высокорисковых проблем повышают urgency.
    """
    if not scored_issues:
        return "low", "Явных проблем не обнаружено — растение выглядит здоровым"

    top = scored_issues[0]
    urgency = top.urgency

    # ---- Confidence-based cap ----
    if top.score < 0.12:
        return "low", "Симптомы неспецифичны — понаблюдайте за растением 2–3 дня"
    if top.score < 0.28:
        if URGENCY_ORDER.get(urgency, 0) >= 3:  # critical/high → cap to medium
            urgency = "medium"

    # ---- Risk aggregation ----
    # Если 2+ проблемы уровня critical со score >= 0.35 → elevate to critical
    critical_high_score = [
        i for i in scored_issues
        if URGENCY_ORDER.get(i.urgency, 0) >= 3 and i.score >= 0.35
    ]
    if len(critical_high_score) >= 2 and URGENCY_ORDER.get(urgency, 0) < 4:
        urgency = max(urgency, critical_high_score[0].urgency,
                      key=lambda u: URGENCY_ORDER.get(u, 0))

    reasons = {
        "critical": f"«{top.title}» — немедленные действия, риск потери урожая",
        "high": f"«{top.title}» — нужно действовать сегодня",
        "medium": f"«{top.title}» — стоит принять меры в ближайшие дни",
        "low": f"Слабые признаки «{top.title}» — понаблюдайте за растением",
    }
    return urgency, reasons.get(urgency, "")
