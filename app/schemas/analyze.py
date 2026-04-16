from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field


CropType = Literal["tomato", "cucumber", "potato", "pepper", "strawberry"]
GrowingEnv = Literal["greenhouse", "open_field", "indoor"]
WateringFreq = Literal["daily", "every_2_days", "every_3_days", "weekly", "rarely"]
SoilMoisture = Literal["very_wet", "wet", "normal", "dry", "very_dry"]
PlantStage = Literal["seedling", "growing", "flowering", "fruiting"]
ConfidenceLabel = Literal["high", "medium", "low"]
UrgencyLevel = Literal["critical", "high", "medium", "low"]


class WeatherContext(BaseModel):
    temperature_day: Optional[float] = None
    temperature_night: Optional[float] = None
    humidity: Optional[float] = None
    recent_rain_mm: Optional[float] = None
    region: Optional[str] = None


class UserContext(BaseModel):
    weather: Optional[WeatherContext] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class QuestionnaireAnswers(BaseModel):
    growing_environment: GrowingEnv
    plant_stage: PlantStage
    days_since_problem_started: int = Field(ge=0, le=365)
    watering_frequency: WateringFreq
    soil_moisture: SoilMoisture

    # Visible symptoms
    has_spots: bool = False
    has_dark_spots: bool = False
    has_white_powder: bool = False
    has_holes_in_leaves: bool = False
    has_webbing: bool = False
    insects_visible: bool = False
    has_yellowing_lower_leaves: bool = False
    has_uniform_yellowing: bool = False
    has_leaf_edge_burn: bool = False
    has_curled_leaves: bool = False
    has_wilting: bool = False
    has_stem_darkening: bool = False
    has_fruit_rot: bool = False
    has_blossom_end_rot: bool = False
    has_slow_growth: bool = False

    # Environmental conditions
    had_cold_nights: bool = False
    had_heat_stress: bool = False
    had_recent_rain: bool = False

    # Recent events
    recently_transplanted: bool = False
    recently_fertilized: bool = False


class AnalyzeRequest(BaseModel):
    crop_type: CropType
    questionnaire: QuestionnaireAnswers
    user_context: Optional[UserContext] = None
    # images_base64: Optional[list[str]] = None  # alternative to multipart


class IssueResult(BaseModel):
    id: str
    title: str
    category: str
    score: float
    confidence_label: ConfidenceLabel
    why: list[str]
    today_actions: list[str]
    what_to_check_next: list[str]


class UrgencyResult(BaseModel):
    level: UrgencyLevel
    reason: str


class CropResult(BaseModel):
    selected: CropType
    detected: Optional[str] = None
    confidence: Optional[float] = None


class UpsellResult(BaseModel):
    video_available: bool
    video_type: str = "agronomist_answer"


class AnalyzeResponse(BaseModel):
    analysis_id: str
    crop: CropResult
    growth_stage: Optional[PlantStage]
    top_issues: list[IssueResult]
    urgency: UrgencyResult
    today_actions: list[str]
    what_to_check_next: list[str]
    upsell: UpsellResult
