"""Photo validation gate — checks uploaded image before allowing diagnosis."""
from __future__ import annotations

import base64
import json
import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, File, UploadFile

from app.core.config import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)

VISION_MODEL = "gemma3:27b"
TIMEOUT = 60.0

_PROMPT = """\
You are a photo validation gate for a plant diagnosis app.

YOUR ONLY GOAL: decide if this photo is good enough to START a plant diagnosis.
You are NOT diagnosing disease. You are NOT checking if disease is visible.
A healthy-looking plant photo is perfectly valid — the diagnosis will happen later.

STEP 1 — IDENTIFY THE MAIN SUBJECT:
What is the PRIMARY, DOMINANT object in this image?
Write it concisely in "mainSubject" (e.g. "frying pan", "tomato leaf", "empty flower pot", "blurry houseplant in corner").

STEP 2 — APPLY RULES IN ORDER:

RULE 1 — NOT A PLANT → return "not_plant":
If the main subject is NOT a living plant or part of a living plant, return "not_plant".
This includes:
  - Cookware: frying pan, saucepan, cooking pot, skillet, wok, kettle
  - Tableware: plate, bowl, cup, mug, dish, glass, cutlery
  - Furniture: chair, table, sofa, desk, shelf, cabinet
  - Electronics: phone, computer, screen, appliance, keyboard
  - Other objects: document, paper, book, tool, container, bucket, jar, vehicle, building
  - People, animals, insects on non-plant surfaces
  - Cooked or cut food, vegetables/fruit on a plate or table
  CRITICAL: An empty pot or planter with NO visible plant → "not_plant"
  CRITICAL: Bare soil or dirt with NO visible plant → "not_plant"
  CRITICAL: Cooked or cut food on any surface → "not_plant"

RULE 2 — PLANT IS ONLY BACKGROUND → return "retake":
A plant is visible but is small, far away, or clearly background decoration,
and the main subject is something else → return "retake".

RULE 3 — VALID PLANT PHOTO → return "valid":
Return "valid" when the main subject IS a plant or plant part AND the photo is usable:
  ✓ A leaf, stem, flower, fruit, branch, or root is clearly visible
  ✓ The plant fills a reasonable portion of the frame
  ✓ The image is focused enough to see the plant
  ✓ Lighting is acceptable (not pitch black or completely blown out)
Do NOT require visible disease or damage. A green healthy leaf is a valid photo.
Do NOT reject a photo just because the plant looks healthy.

RULE 4 — POOR QUALITY → return "retake":
Return "retake" only for genuine quality problems:
  - Plant is so far away it is barely recognisable
  - Severely out of focus (cannot make out plant details at all)
  - Extremely dark or overexposed (plant is not visible)
  - Plant occupies only a tiny corner and is clearly not the subject

Set isDiagnosable = true whenever a plant is clearly visible as the main subject,
regardless of whether disease symptoms are present.

Return ONLY valid JSON with this exact shape:
{
  "status": "valid" | "retake" | "not_plant",
  "confidence": number between 0.0 and 1.0,
  "reason": string,
  "mainSubject": string,
  "isPlant": boolean,
  "isDiagnosable": boolean,
  "qualityIssues": string[]
}

Return JSON only. No markdown. No code blocks. No explanation outside JSON."""

_USER_MESSAGES = {
    "valid": {
        "title": "Фото подходит",
        "description": "Отличный снимок! Продолжаем диагностику.",
        "cta": "Продолжить",
    },
    "retake": {
        "title": "Фото не подходит для диагностики",
        "description": "Сфотографируйте лист, стебель, цветок или плод крупным планом при хорошем освещении.",
        "cta": "Сделать фото снова",
    },
    "not_plant": {
        "title": "Не похоже на растение",
        "description": "Загрузите фото листа, стебля, цветка или плода, чтобы мы могли провести диагностику.",
        "cta": "Выбрать другое фото",
    },
}

_FALLBACK_USER_MESSAGE = {
    "title": "Не удалось проверить фото",
    "description": "Попробуйте загрузить фото растения крупным планом.",
    "cta": "Загрузить другое фото",
}


def _fallback() -> dict:
    return {
        "status": "retake",
        "confidence": None,
        "reason": "validation_service_unavailable",
        "userMessage": _FALLBACK_USER_MESSAGE,
        "debug": {"qualityIssues": ["service_unavailable"]},
    }


# Keywords that clearly indicate a non-plant main subject.
# Checked after removing any plant-part words so "flower pot with plant" is not wrongly blocked.
_NON_PLANT_KEYWORDS = (
    "pan", "saucepan", "skillet", "wok", "kettle", "cookware",
    "plate", "bowl", "cup", "mug", "dish", "glass", "cutlery", "utensil",
    "pot",          # cooking pot / empty pot; guarded by _PLANT_WORDS below
    "planter",
    "furniture", "chair", "table", "desk", "sofa", "shelf",
    "phone", "computer", "screen", "appliance", "keyboard",
    "document", "paper", "book",
    "food", "meal", "cooked", "fried",
    "person", "human", "face", "hand",
    "animal", "dog", "cat", "bird",
    "soil", "dirt", "earth", "ground",
    "tool", "container", "bucket", "jar", "vehicle",
)

_PLANT_WORDS = frozenset({"plant", "leaf", "leaves", "stem", "flower", "fruit", "root", "bark", "seedling", "sprout", "branch", "bud"})


def _is_non_plant_subject(main_subject: str) -> bool:
    s = main_subject.lower()
    if any(pw in s for pw in _PLANT_WORDS):
        return False
    return any(kw in s for kw in _NON_PLANT_KEYWORDS)


def _apply_thresholds(raw: dict) -> str:
    status = raw.get("status", "retake")
    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    is_plant      = raw.get("isPlant")
    is_diagnosable = raw.get("isDiagnosable")
    main_subject  = (raw.get("mainSubject") or "").strip()

    # Missing or empty mainSubject → model uncertainty → retake
    if not main_subject:
        return "retake"

    # isPlant explicitly false → not_plant regardless of status
    if is_plant is False:
        return "not_plant"

    # mainSubject reveals a non-plant object → override to not_plant
    if _is_non_plant_subject(main_subject):
        return "not_plant"

    # valid: lowered confidence threshold; isDiagnosable no longer required
    # (gate checks photo quality/relevance, not presence of disease symptoms)
    if status == "valid" and confidence < 0.65:
        return "retake"

    # not_plant with very low confidence → model unsure → retake
    if status == "not_plant" and confidence < 0.6:
        return "retake"

    # Unknown status value → retake
    if status not in ("valid", "retake", "not_plant"):
        return "retake"

    return status


@router.post("/validate-photo")
async def validate_photo(image: Annotated[UploadFile, File()]) -> dict:
    """Validate whether the uploaded image is a suitable plant photo for diagnosis."""
    settings = get_settings()
    image_b64 = base64.b64encode(await image.read()).decode()

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/chat",
                json={
                    "model": VISION_MODEL,
                    "messages": [
                        {"role": "user", "content": _PROMPT, "images": [image_b64]}
                    ],
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            raw_content = resp.json()["message"]["content"]
    except httpx.TimeoutException:
        logger.warning("validate_photo: Ollama timed out (%.0fs)", TIMEOUT)
        return _fallback()
    except Exception as e:
        logger.error("validate_photo: Ollama error: %s", e)
        return _fallback()

    try:
        model_data = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error("validate_photo: non-JSON from model: %.200s", raw_content)
        return _fallback()

    status = _apply_thresholds(model_data)
    logger.info(
        "validate_photo: model=%s conf=%.2f mainSubject=%r → status=%s",
        model_data.get("status"),
        model_data.get("confidence", 0),
        model_data.get("mainSubject", ""),
        status,
    )

    return {
        "status": status,
        "confidence": model_data.get("confidence"),
        "reason": model_data.get("reason", ""),
        "userMessage": _USER_MESSAGES[status],
        "debug": {
            "mainSubject": model_data.get("mainSubject"),
            "isPlant": model_data.get("isPlant"),
            "isDiagnosable": model_data.get("isDiagnosable"),
            "qualityIssues": model_data.get("qualityIssues", []),
            "modelRaw": model_data,
        },
    }
