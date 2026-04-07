# Import all models here so Alembic/create_all can detect them
from app.models.user import User  # noqa: F401
from app.models.analysis import Analysis, AnalysisImage, QuestionnaireAnswer, IssueScore, Followup  # noqa: F401
from app.models.video_job import VideoJob  # noqa: F401
