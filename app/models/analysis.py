import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, Float, Integer, Text, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    crop_selected: Mapped[str] = mapped_column(String(50))
    crop_detected: Mapped[str | None] = mapped_column(String(50), nullable=True)
    crop_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    urgency_level: Mapped[str] = mapped_column(String(20), default="medium")
    urgency_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    top_issues: Mapped[dict] = mapped_column(JSON, default=list)
    today_actions: Mapped[list] = mapped_column(JSON, default=list)
    what_to_check_next: Mapped[list] = mapped_column(JSON, default=list)
    video_available: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["AnalysisImage"]] = relationship(back_populates="analysis", lazy="selectin")
    questionnaire: Mapped["QuestionnaireAnswer | None"] = relationship(back_populates="analysis", uselist=False, lazy="selectin")
    issue_scores: Mapped[list["IssueScore"]] = relationship(back_populates="analysis", lazy="selectin")
    followups: Mapped[list["Followup"]] = relationship(back_populates="analysis", lazy="selectin")


class AnalysisImage(Base):
    __tablename__ = "analysis_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    image_type: Mapped[str] = mapped_column(String(50), default="general")  # general|leaf|stem|fruit|field
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis: Mapped["Analysis"] = relationship(back_populates="images")


class QuestionnaireAnswer(Base):
    __tablename__ = "questionnaire_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), unique=True, index=True)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis: Mapped["Analysis"] = relationship(back_populates="questionnaire")


class IssueScore(Base):
    __tablename__ = "issue_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    issue_id: Mapped[str] = mapped_column(String(100))
    score: Mapped[float] = mapped_column(Float)
    rank: Mapped[int] = mapped_column(Integer)
    contributing_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis: Mapped["Analysis"] = relationship(back_populates="issue_scores")


class Followup(Base):
    __tablename__ = "followups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    analysis_id: Mapped[str] = mapped_column(String(36), ForeignKey("analyses.id"), index=True)
    status_change: Mapped[str] = mapped_column(String(50))  # better|worse|unchanged
    updated_top_issues: Mapped[dict] = mapped_column(JSON, default=list)
    updated_actions: Mapped[list] = mapped_column(JSON, default=list)
    raw_signals: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    analysis: Mapped["Analysis"] = relationship(back_populates="followups")
