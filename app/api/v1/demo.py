"""
Demo Fixtures API — быстрый запуск готовых сценариев без загрузки фото.

GET /api/v1/demo/cases         — список всех демо-кейсов
GET /api/v1/demo/cases/{id}    — запустить конкретный кейс, вернуть AnalyzeResponse
"""
import uuid
import json
import logging
from pathlib import Path
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.schemas.analyze import (
    AnalyzeResponse, CropResult, IssueResult, UrgencyResult, UpsellResult,
    QuestionnaireAnswers,
)
from app.services.scoring_engine import ScoringEngine, compute_urgency, get_confidence_label
from app.services.explanation_service import ExplanationService

router = APIRouter(prefix="/demo", tags=["Demo"])
logger = logging.getLogger(__name__)

_scoring = ScoringEngine()
_explanation = ExplanationService()

FIXTURES_PATH = Path(__file__).parent.parent.parent / "app" / "fixtures" / "demo_cases.json"


@lru_cache(maxsize=1)
def _load_fixtures() -> list[dict]:
    path = Path(__file__).parent.parent.parent / "fixtures" / "demo_cases.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@router.get("/cases")
def list_demo_cases():
    """Вернуть каталог демо-кейсов (без результатов scoring)."""
    cases = _load_fixtures()
    return [
        {
            "id": c["id"],
            "label": c["label"],
            "description": c["description"],
            "crop": c["crop"],
            "plant_stage": c["plant_stage"],
            "expected_top_issue": c["expected_top_issue"],
        }
        for c in cases
    ]


@router.get("/cases/{fixture_id}", response_model=AnalyzeResponse)
def run_demo_case(fixture_id: str):
    """Запустить демо-кейс: прогнать scoring engine и вернуть AnalyzeResponse."""
    cases = _load_fixtures()
    case = next((c for c in cases if c["id"] == fixture_id), None)
    if not case:
        raise HTTPException(status_code=404, detail=f"Demo case '{fixture_id}' not found")

    questionnaire = QuestionnaireAnswers(**case["questionnaire"])
    scored_issues, signals = _scoring.analyze(
        crop=case["crop"],
        plant_stage=case["plant_stage"],
        questionnaire=questionnaire,
    )

    urgency_level, urgency_reason = compute_urgency(scored_issues)
    issue_results = [_explanation.build_issue_result(issue) for issue in scored_issues]
    today_actions = _explanation.merge_top_actions(scored_issues)
    check_next = _explanation.merge_check_next(scored_issues)

    # Synthetic analysis_id с префиксом demo для идентификации
    analysis_id = f"demo_{fixture_id}_{uuid.uuid4().hex[:8]}"

    return AnalyzeResponse(
        analysis_id=analysis_id,
        crop=CropResult(selected=case["crop"]),
        growth_stage=case["plant_stage"],
        top_issues=issue_results,
        urgency=UrgencyResult(level=urgency_level, reason=urgency_reason),
        today_actions=today_actions,
        what_to_check_next=check_next,
        upsell=UpsellResult(video_available=True),
    )
