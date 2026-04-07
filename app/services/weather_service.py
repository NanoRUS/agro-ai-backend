"""
Weather Service — заглушка получения погодных данных.

В продакшне интегрируется с OpenWeatherMap / Open-Meteo (бесплатный).
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WeatherData:
    temperature_day: float | None = None
    temperature_night: float | None = None
    humidity: float | None = None
    recent_rain_mm: float | None = None


class WeatherService:
    async def get_weather(
        self,
        latitude: float | None,
        longitude: float | None,
        region: str | None = None,
    ) -> WeatherData | None:
        if not latitude or not longitude:
            return None

        # TODO: integrate with weather API
        # Example with Open-Meteo (free, no API key):
        # async with httpx.AsyncClient() as client:
        #     r = await client.get(
        #         "https://api.open-meteo.com/v1/forecast",
        #         params={
        #             "latitude": latitude, "longitude": longitude,
        #             "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,relative_humidity_2m_mean",
        #             "forecast_days": 3,
        #         },
        #     )
        #     return self._parse(r.json())

        logger.debug("WeatherService stub: returning None")
        return None
