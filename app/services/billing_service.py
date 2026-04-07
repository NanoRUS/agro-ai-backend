"""
Billing Service — заглушка проверки доступа.

В продакшне интегрируется с существующей биллинговой системой.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class AccessDenied(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class BillingService:
    """
    Stub: всегда разрешает доступ.
    Реальная реализация: проверяет токен/user_id в биллинговой системе.
    """

    async def check_analysis_access(
        self, user_id: str | None, subscription_tier: str = "free"
    ) -> bool:
        # TODO: validate against external billing API
        # Example:
        # async with httpx.AsyncClient() as client:
        #     r = await client.get(
        #         f"{settings.billing_service_url}/users/{user_id}/quota",
        #         headers={"Authorization": f"Bearer {settings.billing_service_api_key}"},
        #     )
        #     return r.json()["analyses_remaining"] > 0
        logger.debug("BillingService stub: access granted")
        return True

    async def check_video_access(
        self, user_id: str | None, subscription_tier: str = "free"
    ) -> bool:
        # TODO: check if user has purchased video or has Pro subscription
        logger.debug("BillingService stub: video access granted")
        return True

    async def record_analysis_usage(self, user_id: str | None) -> None:
        # TODO: increment usage counter in billing system
        logger.debug("BillingService stub: usage recorded")
