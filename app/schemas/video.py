from typing import Optional, Literal
from pydantic import BaseModel

ResponseStyle = Literal["calm_expert", "urgent_expert", "friendly_guide"]


class VideoGenerateRequest(BaseModel):
    analysis_id: str
    selected_issue_id: str
    response_style: ResponseStyle = "calm_expert"
    user_plan_tier: str = "free"


class VideoGenerateResponse(BaseModel):
    status: str
    video_job_id: str
    preview_metadata: dict


class VideoStatusResponse(BaseModel):
    job_id: str
    status: str  # pending | processing | done | failed
    video_url: Optional[str] = None
    duration_seconds: Optional[int] = None
    thumbnail_url: Optional[str] = None
