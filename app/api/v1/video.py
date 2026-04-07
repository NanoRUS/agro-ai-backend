"""
POST /generate-video — запуск генерации видеорасбора AI-агронома.
GET  /video/{job_id}  — статус и ссылка на готовое видео.

Внутренний flow:
1. Загружаем analysis из БД
2. Строим скрипт через VideoScriptService
3. Отправляем во внешний video pipeline (stub)
4. Сохраняем VideoJob
5. Возвращаем job_id + preview
"""
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.models.video_job import VideoJob
from app.models.analysis import Analysis
from app.schemas.video import VideoGenerateRequest, VideoGenerateResponse, VideoStatusResponse
from app.schemas.analyze import IssueResult
from app.services.billing_service import BillingService, AccessDenied
from app.services.video_script_service import VideoScriptService

router = APIRouter()
logger = logging.getLogger(__name__)

_billing = BillingService()
_script_svc = VideoScriptService()

CROP_NAMES_RU = {
    "tomato": "томате", "cucumber": "огурце",
    "potato": "картофеле", "pepper": "перце", "strawberry": "клубнике",
}


@router.post("/generate-video", response_model=VideoGenerateResponse)
async def generate_video(
    request: VideoGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Создаёт задачу на генерацию видеорасбора для выбранной проблемы."""
    try:
        await _billing.check_video_access(user_id=None, subscription_tier=request.user_plan_tier)
    except AccessDenied as e:
        raise HTTPException(status_code=402, detail=e.reason)

    result = await db.execute(select(Analysis).where(Analysis.id == request.analysis_id))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Выбираем issue для видео: либо выбранный пользователем, либо топ-1
    if request.selected_issue_id:
        issue_data = next(
            (i for i in analysis.top_issues if i["id"] == request.selected_issue_id), None
        )
        if not issue_data:
            raise HTTPException(status_code=404, detail=f"Issue '{request.selected_issue_id}' not in this analysis")
    else:
        if not analysis.top_issues:
            raise HTTPException(status_code=400, detail="No issues found in analysis")
        issue_data = analysis.top_issues[0]

    selected_issue = IssueResult.model_validate(issue_data)
    crop_name = CROP_NAMES_RU.get(analysis.crop_selected, analysis.crop_selected)

    # Определяем tone из issue или из запроса
    issue_tone = issue_data.get("video_tone") or request.response_style
    tone = request.response_style if request.response_style != "calm_expert" else issue_tone

    # Генерируем скрипт
    script = _script_svc.generate_script(
        issue=selected_issue,
        crop_name_ru=crop_name,
        urgency_level=analysis.urgency_level,
        tone=tone,
    )

    job_id = str(uuid.uuid4())
    external_job_id = await _script_svc.submit_to_pipeline(
        script=script, job_id=job_id, style=tone
    )

    job = VideoJob(
        id=job_id,
        analysis_id=request.analysis_id,
        selected_issue_id=selected_issue.id,
        response_style=tone,
        status="processing" if external_job_id else "pending",
        script=script,
        external_job_id=external_job_id,
        meta={
            "crop": analysis.crop_selected,
            "issue_title": selected_issue.title,
            "urgency": analysis.urgency_level,
            "script_length": len(script),
        },
    )
    db.add(job)
    await db.commit()

    logger.info("VideoJob created: job_id=%s issue=%s crop=%s", job_id, selected_issue.id, analysis.crop_selected)

    return VideoGenerateResponse(
        status=job.status,
        video_job_id=job_id,
        preview_metadata={
            "issue_id": selected_issue.id,
            "issue_title": selected_issue.title,
            "crop": analysis.crop_selected,
            "urgency": analysis.urgency_level,
            "duration_estimate_seconds": 45,
            "style": tone,
            "script_preview": script[:200] + ("..." if len(script) > 200 else ""),
        },
    )


@router.get("/video/{job_id}", response_model=VideoStatusResponse)
async def get_video_status(job_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(VideoJob).where(VideoJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Video job not found")

    return VideoStatusResponse(
        job_id=job.id,
        status=job.status,
        video_url=job.video_url,
        duration_seconds=45 if job.status == "done" else None,
        thumbnail_url=None,
    )
