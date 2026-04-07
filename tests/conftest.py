"""Pytest configuration and fixtures for agro-ai backend tests."""
import pytest
from app.services.scoring_engine import ScoringEngine, SignalExtractor, compute_urgency
from app.schemas.analyze import QuestionnaireAnswers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_questionnaire(**kwargs) -> QuestionnaireAnswers:
    """Factory with sensible defaults — override only what the test needs."""
    defaults = dict(
        growing_environment="open_field",
        plant_stage="growing",
        days_since_problem_started=3,
        watering_frequency="every_2_days",
        soil_moisture="normal",
    )
    defaults.update(kwargs)
    return QuestionnaireAnswers(**defaults)


def extract_signals(questionnaire: QuestionnaireAnswers, ctx=None, cv=None) -> dict:
    return SignalExtractor().extract(questionnaire, ctx, cv)


@pytest.fixture
def engine() -> ScoringEngine:
    return ScoringEngine(top_n=3, min_score=0.08)


@pytest.fixture
def extractor() -> SignalExtractor:
    return SignalExtractor()
