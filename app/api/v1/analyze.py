import uuid
import json
import logging
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.analysis import Analysis, AnalysisImage, QuestionnaireAnswer, IssueScore as IssueScoreModel
from app.schemas.analyze import (
    AnalyzeRequest, AnalyzeResponse, CropResult, IssueResult, UrgencyResult, UpsellResult,
)
from app.services.scoring_engine import ScoringEngine, compute_urgency
from app.services.explanation_service import ExplanationService
from app.services.cv_provider import CVProvider
from app.services.billing_service import BillingService, AccessDenied
from app.services.weather_service import WeatherService

router = APIRouter()
logger = logging.getLogger(__name__)

_scoring = ScoringEngine()
_explanation = ExplanationService()
_cv = CVProvider()
_billing = BillingService()
_weather = WeatherService()

CROP_NAMES_RU = {
    "tomato": "томате", "cucumber": "огурце",
    "potato": "картофеле", "pepper": "перце", "strawberry": "клубнике",
    "houseplant": "комнатном растении", "flowering": "цветущем растении",
    "succulent": "суккуленте", "decorative": "декоративном растении",
    "unknown": "растении",
}


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    questionnaire_json: Annotated[str, Form()],
    images: Annotated[list[UploadFile], File()] = [],
    db: AsyncSession = Depends(get_db),
):
    """
    Принимает фото и анкету, возвращает top-3 проблемы, urgency и план действий.

    questionnaire_json — JSON-строка с полями AnalyzeRequest.
    images — до 5 фото (multipart/form-data).
    """
    try:
        request = AnalyzeRequest.model_validate_json(questionnaire_json)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid questionnaire: {e}")

    # --- Billing check ---
    try:
        await _billing.check_analysis_access(user_id=None)
    except AccessDenied as e:
        raise HTTPException(status_code=402, detail=e.reason)

    # --- Read image bytes ---
    image_bytes_list = []
    for img in images[:5]:
        image_bytes_list.append(await img.read())

    # --- Resolve crop context ---
    # farm: crop_type set, plant_category=None
    # home/dacha: crop_type=None, plant_category set → generic issue set
    effective_crop = request.crop_type or "generic"
    display_selected = request.crop_type or request.plant_category or "unknown"

    # --- CV analysis (stub) ---
    cv_output = await _cv.analyze_images(image_bytes_list, crop_hint=request.crop_type or request.plant_category)

    # --- Weather enrichment ---
    ctx = request.user_context
    if ctx and ctx.latitude and not (ctx.weather and ctx.weather.temperature_day):
        weather = await _weather.get_weather(ctx.latitude, ctx.longitude)
        if weather:
            from app.schemas.analyze import WeatherContext
            ctx.weather = WeatherContext(
                temperature_day=weather.temperature_day,
                temperature_night=weather.temperature_night,
                humidity=weather.humidity,
                recent_rain_mm=weather.recent_rain_mm,
            )

    # --- Scoring ---
    scored_issues, signals = _scoring.analyze(
        crop=effective_crop,
        plant_stage=request.questionnaire.plant_stage,
        questionnaire=request.questionnaire,
        user_context=ctx,
        cv_output=cv_output,
    )

    urgency_level, urgency_reason = compute_urgency(scored_issues)

    # --- Build response objects ---
    issue_results = [_explanation.build_issue_result(issue) for issue in scored_issues]
    today_actions = _explanation.merge_top_actions(scored_issues)
    check_next = _explanation.merge_check_next(scored_issues)

    analysis_id = str(uuid.uuid4())

    # --- Persist ---
    analysis = Analysis(
        id=analysis_id,
        crop_selected=display_selected,
        growth_stage=request.questionnaire.plant_stage,
        urgency_level=urgency_level,
        urgency_reason=urgency_reason,
        top_issues=[r.model_dump() for r in issue_results],
        today_actions=today_actions,
        what_to_check_next=check_next,
        video_available=True,
        raw_signals=signals,
    )
    db.add(analysis)

    db.add(QuestionnaireAnswer(
        analysis_id=analysis_id,
        answers=request.questionnaire.model_dump(),
    ))

    for i, issue in enumerate(scored_issues):
        db.add(IssueScoreModel(
            analysis_id=analysis_id,
            issue_id=issue.id,
            score=issue.score,
            rank=i + 1,
            contributing_signals=issue.contributing_signals,
        ))

    for i, img in enumerate(images[:5]):
        db.add(AnalysisImage(
            analysis_id=analysis_id,
            original_filename=img.filename,
            image_type="general",
        ))

    await db.commit()
    await _billing.record_analysis_usage(user_id=None)

    return AnalyzeResponse(
        analysis_id=analysis_id,
        crop=CropResult(
            selected=display_selected,
            detected=cv_output.get("detected_crop"),
            confidence=cv_output.get("crop_confidence"),
        ),
        growth_stage=request.questionnaire.plant_stage,
        top_issues=issue_results,
        urgency=UrgencyResult(level=urgency_level, reason=urgency_reason),
        today_actions=today_actions,
        what_to_check_next=check_next,
        upsell=UpsellResult(video_available=True),
    )


@router.get("/analysis/{analysis_id}", response_model=AnalyzeResponse)
async def get_analysis(analysis_id: str, db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select
    result = await db.execute(select(Analysis).where(Analysis.id == analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    top_issues = [IssueResult.model_validate(i) for i in analysis.top_issues]

    return AnalyzeResponse(
        analysis_id=analysis.id,
        crop=CropResult(selected=analysis.crop_selected),
        growth_stage=analysis.growth_stage,
        top_issues=top_issues,
        urgency=UrgencyResult(level=analysis.urgency_level, reason=analysis.urgency_reason or ""),
        today_actions=analysis.today_actions,
        what_to_check_next=analysis.what_to_check_next,
        upsell=UpsellResult(video_available=analysis.video_available),
    )
