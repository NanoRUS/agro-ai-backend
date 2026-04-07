"""
POST /follow-up — повторная диагностика с учётом динамики.

Принимает analysis_id + статус изменения + (опционально) обновлённую анкету.
Пересчитывает scoring при наличии новой анкеты.
Адаптирует рекомендации под статус better/unchanged/worse.
"""
import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.analysis import Analysis, Followup
from app.schemas.followup import FollowupRequest, FollowupResponse
from app.schemas.analyze import IssueResult
from app.services.scoring_engine import ScoringEngine, compute_urgency, get_confidence_label
from app.services.explanation_service import ExplanationService
from app.services.cv_provider import CVProvider

router = APIRouter()
logger = logging.getLogger(__name__)

_scoring = ScoringEngine()
_explanation = ExplanationService()
_cv = CVProvider()


@router.post("/follow-up", response_model=FollowupResponse)
async def follow_up(
    questionnaire_json: Annotated[str, Form()],
    images: Annotated[list[UploadFile], File()] = [],
    db: AsyncSession = Depends(get_db),
):
    """
    Повторная проверка растения.

    questionnaire_json — JSON-строка FollowupRequest.
    images — (опционально) до 5 новых фото.
    """
    try:
        from app.schemas.followup import FollowupRequest as FR
        request = FR.model_validate_json(questionnaire_json)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid followup request: {e}")

    result = await db.execute(select(Analysis).where(Analysis.id == request.analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    image_bytes_list = [await img.read() for img in images[:5]]
    cv_output = await _cv.analyze_images(image_bytes_list, crop_hint=analysis.crop_selected) if image_bytes_list else None

    # Пересчёт scoring при наличии новой анкеты
    if request.questionnaire:
        scored_issues, signals = _scoring.analyze(
            crop=analysis.crop_selected,
            plant_stage=request.questionnaire.plant_stage,
            questionnaire=request.questionnaire,
            user_context=request.user_context,
            cv_output=cv_output,
        )
        new_urgency_level, _ = compute_urgency(scored_issues)
        issue_results = [_explanation.build_issue_result(i) for i in scored_issues]
        actions = _build_followup_actions(
            request.status_change, _explanation.merge_top_actions(scored_issues)
        )
        urgency_changed = new_urgency_level != analysis.urgency_level
    else:
        # Нет новой анкеты — используем предыдущие результаты
        issue_results = [IssueResult.model_validate(i) for i in analysis.top_issues]
        actions = _build_followup_actions(request.status_change, analysis.today_actions)
        new_urgency_level = analysis.urgency_level
        urgency_changed = False
        signals = {}

    followup_id = str(uuid.uuid4())
    db.add(Followup(
        id=followup_id,
        analysis_id=request.analysis_id,
        status_change=request.status_change,
        updated_top_issues=[r.model_dump() for r in issue_results],
        updated_actions=actions,
        raw_signals=signals,
    ))
    await db.commit()

    return FollowupResponse(
        followup_id=followup_id,
        analysis_id=request.analysis_id,
        status_change=request.status_change,
        updated_top_issues=issue_results,
        updated_actions=actions,
        urgency_changed=urgency_changed,
        message=_build_message(request.status_change, new_urgency_level, issue_results),
    )


def _build_followup_actions(status_change: str, original_actions: list[str]) -> list[str]:
    """Адаптирует действия под статус изменения."""
    if status_change == "better":
        return original_actions[:3]  # только топ-3 — продолжаем лечение
    if status_change == "worse":
        escalation = ["Сфотографируйте поражение и сделайте новую диагностику с обновлёнными симптомами"]
        return escalation + original_actions
    return original_actions  # unchanged — всё то же


def _build_message(status_change: str, urgency: str, issues: list[IssueResult]) -> str:
    top_issue = issues[0].title if issues else "проблема"
    base = {
        "better": f"Хорошо! «{top_issue}» отступает. Продолжайте лечение ещё 5–7 дней.",
        "unchanged": f"Изменений нет. Убедитесь, что выполняете рекомендации по «{top_issue}».",
        "worse": f"Симптомы усилились. Рекомендую новый анализ с обновлёнными фото.",
    }.get(status_change, "")
    if status_change == "worse" and urgency in ("critical", "high"):
        base += " Рассмотрите консультацию с агрономом."
    return base
