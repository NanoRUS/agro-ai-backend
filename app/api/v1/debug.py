"""
Debug Panel API — только для dev/demo окружения.

GET  /api/v1/debug/analysis/{analysis_id} — полный breakdown scores для сохранённого анализа
POST /api/v1/debug/analyze               — прогнать анкету без сохранения, вернуть raw debug
"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import get_db
from app.models.analysis import Analysis
from app.schemas.analyze import AnalyzeRequest
from app.services.scoring_engine import ScoringEngine

router = APIRouter(prefix="/debug", tags=["Debug"])
logger = logging.getLogger(__name__)

_scoring = ScoringEngine()


def _require_debug():
    """Блокирует доступ в production."""
    settings = get_settings()
    if not settings.debug:
        raise HTTPException(status_code=403, detail="Debug endpoints disabled in production")


@router.post("/analyze")
async def debug_analyze(
    questionnaire_json: Annotated[str, Form()],
):
    """Прогнать анкету через scoring engine и вернуть полный debug breakdown."""
    _require_debug()

    try:
        request = AnalyzeRequest.model_validate_json(questionnaire_json)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid questionnaire: {e}")

    from app.services.scoring_engine import SignalExtractor
    signals = SignalExtractor().extract(
        questionnaire=request.questionnaire,
        user_context=request.user_context,
        cv_output=None,
    )

    debug_data = _scoring.score_issues_debug(
        crop=request.crop_type,
        plant_stage=request.questionnaire.plant_stage,
        signals=signals,
    )

    return {
        "crop": request.crop_type,
        "plant_stage": request.questionnaire.plant_stage,
        **debug_data,
    }


@router.get("/analysis/{analysis_id}")
async def debug_analysis(analysis_id: str, db: AsyncSession = Depends(get_db)):
    """Вернуть сохранённые сигналы и полный breakdown для analysis_id."""
    _require_debug()

    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    signals = analysis.raw_signals or {}
    debug_data = _scoring.score_issues_debug(
        crop=analysis.crop_selected,
        plant_stage=analysis.growth_stage,
        signals=signals,
    )

    return {
        "analysis_id": analysis_id,
        "crop": analysis.crop_selected,
        "plant_stage": analysis.growth_stage,
        "saved_top_issues": [i.get("id") for i in (analysis.top_issues or [])],
        **debug_data,
    }
