from typing import Optional, Literal
from pydantic import BaseModel
from app.schemas.analyze import IssueResult, UrgencyResult, QuestionnaireAnswers, UserContext

StatusChange = Literal["better", "worse", "unchanged"]


class FollowupRequest(BaseModel):
    analysis_id: str
    status_change: StatusChange
    questionnaire: Optional[QuestionnaireAnswers] = None
    user_context: Optional[UserContext] = None


class FollowupResponse(BaseModel):
    followup_id: str
    analysis_id: str
    status_change: StatusChange
    updated_top_issues: list[IssueResult]
    updated_actions: list[str]
    urgency_changed: bool
    message: str
