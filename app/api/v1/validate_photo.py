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
You are a plant detector for a photo validation gate.

YOUR ONLY TASK: determine whether a plant is visible in the image.
Do NOT judge photo quality. Do NOT check for disease. Do NOT assess focus or distance.

DECISION LOGIC:

Return "valid" if ANY living plant is visible in the image:
  - any leaf, stem, flower, fruit, seedling, sprout, or branch
  - plant in a pot, in soil, on a table, anywhere
  - small seedlings in cups or trays
  - distant plants or garden scenes
  - partially visible plants
  - healthy plants with no visible disease
  Even if the plant is small, in the background, or not the main focus → "valid"

Return "not_plant" if there is clearly NO plant in the image:
  - cookware, tableware, kitchen items (pan, pot, plate, cup, bowl)
  - furniture, electronics, appliances, documents, tools
  - people, animals
  - cooked or cut food on a plate
  - empty pot or planter with no visible plant
  - bare soil with no visible plant above it
  - any non-plant object with no plant present

Return "retake" ONLY if the image is so degraded that you genuinely cannot tell
whether a plant is present (e.g. completely black image, total blur with no shapes).

Set isPlant = true whenever any plant is visible anywhere in the image.
Set isDiagnosable = true whenever isPlant = true.

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

    # isPlant explicitly true → always valid regardless of other fields
    if is_plant is True:
        return "valid"

    # isPlant explicitly false → not_plant (unless model is very uncertain)
    if is_plant is False:
        if confidence >= 0.5:
            return "not_plant"
        return "retake"

    # isPlant not set — fall back to model status with safety checks
    if not main_subject:
        return "retake"

    # mainSubject clearly a non-plant object → not_plant
    if _is_non_plant_subject(main_subject):
        return "not_plant"

    # Unknown status value → retake
    if status not in ("valid", "retake", "not_plant"):
        return "retake"

    return status


VALIDATION_VERSION = "plant-gate-v3-simple-isPlant"


@router.post("/validate-photo")
async def validate_photo(image: Annotated[UploadFile, File()]) -> dict:
    """Validate whether the uploaded image is a suitable plant photo for diagnosis."""
    settings = get_settings()
    image_bytes = await image.read()
    image_b64 = base64.b64encode(image_bytes).decode()

    logger.info(
        "validate_photo [%s]: file=%r content_type=%r size=%d bytes",
        VALIDATION_VERSION,
        image.filename,
        image.content_type,
        len(image_bytes),
    )

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
                    "keep_alive": "10m",
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

    logger.info("validate_photo: raw_ollama_response=%.500s", raw_content)

    try:
        model_data = json.loads(raw_content)
    except json.JSONDecodeError:
        logger.error("validate_photo: non-JSON from model: %.200s", raw_content)
        return _fallback()

    status = _apply_thresholds(model_data)
    logger.info(
        "validate_photo: isPlant=%s model_status=%s conf=%.2f mainSubject=%r → final_status=%s reason=%r",
        model_data.get("isPlant"),
        model_data.get("status"),
        model_data.get("confidence", 0),
        model_data.get("mainSubject", ""),
        status,
        model_data.get("reason", ""),
    )

    return {
        "status": status,
        "confidence": model_data.get("confidence"),
        "reason": model_data.get("reason", ""),
        "userMessage": _USER_MESSAGES[status],
        "validationVersion": VALIDATION_VERSION,
        "debug": {
            "mainSubject": model_data.get("mainSubject"),
            "isPlant": model_data.get("isPlant"),
            "isDiagnosable": model_data.get("isDiagnosable"),
            "qualityIssues": model_data.get("qualityIssues", []),
            "modelRaw": model_data,
        },
    }
