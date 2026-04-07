"""
CV Provider — заглушка компьютерного зрения.

В продакшне заменяется на вызов Plant.id API или собственной модели.
Возвращает confidence scores по категориям болезней.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

CV_CATEGORIES = [
    "cv_fungal_confidence",
    "cv_pest_confidence",
    "cv_nutrient_deficiency_confidence",
    "cv_bacterial_confidence",
    "cv_healthy_confidence",
]


class CVProvider:
    """
    Stub: возвращает нейтральные значения.
    Реальная реализация: загружает изображение в Plant.id / PlantNet API,
    парсит ответ и маппит на наши категории сигналов.
    """

    async def analyze_images(
        self,
        image_bytes_list: list[bytes],
        crop_hint: str | None = None,
    ) -> dict[str, float]:
        if not image_bytes_list:
            return self._neutral()

        # TODO: integrate Plant.id / custom model
        # Example real call:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(
        #         "https://api.plant.id/v3/health_assessment",
        #         headers={"Api-Key": settings.plant_id_api_key},
        #         json={"images": [base64.b64encode(b).decode() for b in image_bytes_list]},
        #     )
        #     return self._parse_plant_id_response(response.json())

        logger.debug("CVProvider stub: returning neutral scores")
        return self._neutral()

    def _neutral(self) -> dict[str, float]:
        return {cat: 0.0 for cat in CV_CATEGORIES}
