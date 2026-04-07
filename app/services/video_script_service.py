"""
Video Script Service — генерирует текстовый скрипт для видеорасбора AI-агронома.

Три тональности:
  urgent_expert    — авторитетный эксперт, срочный тон, факты и риски
  calm_consultant  — спокойный консультант, объяснение, шаги
  crop_doctor      — врачебная метафора: диагноз → лечение → прогноз
"""
from __future__ import annotations
from app.schemas.analyze import IssueResult


# ---------------------------------------------------------------------------
# Tone templates: opener, body_intro, action_intro, closer
# ---------------------------------------------------------------------------

TONE_TEMPLATES: dict[str, dict[str, str]] = {
    "urgent_expert": {
        "opener": (
            "Смотрел ваши фото — ситуация требует действий сегодня. "
            "Расскажу, что происходит и что делать прямо сейчас."
        ),
        "body_intro": "На вашем {crop} вижу признаки «{issue}».",
        "why_intro": "Вот почему я так считаю:",
        "action_intro": "Три действия, которые нужно сделать сегодня:",
        "closer_critical": (
            "Не затягивайте — каждый день промедления увеличивает потери. "
            "Обработайте сегодня, через 5 дней сделайте повторное фото."
        ),
        "closer_high": (
            "Действуйте в ближайшие 1–2 дня. "
            "Через неделю сделайте повторную диагностику — проверим результат."
        ),
        "closer_medium": (
            "Ситуация под контролем, если действовать сейчас. "
            "Через 10 дней посмотрим на динамику."
        ),
        "closer_low": (
            "Понаблюдайте 3–4 дня. "
            "Если симптомы усилятся — сделайте повторное фото для точного диагноза."
        ),
    },
    "calm_consultant": {
        "opener": (
            "Посмотрел ваши фото, давайте разберёмся вместе — "
            "объясню, что происходит с растением и как это исправить."
        ),
        "body_intro": "По снимкам вашего {crop} скорее всего мы имеем дело с «{issue}».",
        "why_intro": "Почему я так думаю:",
        "action_intro": "Вот что я рекомендую сделать:",
        "closer_critical": (
            "Это важно сделать сегодня, чтобы остановить распространение. "
            "Я здесь, если нужно — сделайте повторную диагностику после обработки."
        ),
        "closer_high": (
            "Не срочно, но лучше не откладывать больше чем на пару дней. "
            "Повторная диагностика через 7–10 дней покажет, как идут дела."
        ),
        "closer_medium": (
            "Всё решаемо — следуйте шагам и через неделю станет лучше. "
            "Через 10 дней можно проверить динамику."
        ),
        "closer_low": (
            "Ситуация неоднозначная — понаблюдайте несколько дней. "
            "При ухудшении пришлите более чёткие фото листьев."
        ),
    },
    "crop_doctor": {
        "opener": (
            "Осмотрел ваше растение — сейчас поставлю диагноз, "
            "объясню причины и назначу лечение."
        ),
        "body_intro": "Диагноз: «{issue}» на {crop}.",
        "why_intro": "Основания для диагноза:",
        "action_intro": "Назначаю следующее лечение:",
        "closer_critical": (
            "Прогноз серьёзный — без лечения растение не выживет. "
            "Немедленно начните обработку. Контрольный осмотр через 5 дней."
        ),
        "closer_high": (
            "Прогноз благоприятный при своевременном лечении. "
            "Контрольный осмотр через 7–10 дней."
        ),
        "closer_medium": (
            "Прогноз хороший — при соблюдении назначений полное восстановление через 10–14 дней. "
            "Повторный осмотр через 2 недели."
        ),
        "closer_low": (
            "Диагноз предварительный — нужно больше симптомов. "
            "Пришлите фото через 3–4 дня для уточнения."
        ),
    },
}

# Обратная совместимость со старыми значениями tone
TONE_ALIAS: dict[str, str] = {
    "calm_expert": "calm_consultant",
    "calm_practical": "calm_consultant",
    "friendly_guide": "calm_consultant",
}


class VideoScriptService:
    def generate_script(
        self,
        issue: IssueResult,
        crop_name_ru: str,
        urgency_level: str,
        tone: str = "calm_consultant",
    ) -> str:
        tone = TONE_ALIAS.get(tone, tone)
        tmpl = TONE_TEMPLATES.get(tone, TONE_TEMPLATES["calm_consultant"])

        opener = tmpl["opener"]
        body = tmpl["body_intro"].format(crop=crop_name_ru, issue=issue.title)
        why_intro = tmpl["why_intro"]
        action_intro = tmpl["action_intro"]
        closer_key = f"closer_{urgency_level}"
        closer = tmpl.get(closer_key, tmpl["closer_medium"])

        why_text = self._format_why(issue.why[:3])
        actions_text = self._format_actions(issue.today_actions[:3])

        script = (
            f"{opener}\n\n"
            f"{body}\n\n"
            f"{why_intro}\n{why_text}\n\n"
            f"{action_intro}\n{actions_text}\n\n"
            f"{closer}"
        )

        # TODO: pass to LLM for personalization in production:
        # async with anthropic.AsyncAnthropic() as client:
        #     message = await client.messages.create(
        #         model="claude-opus-4-6",
        #         max_tokens=500,
        #         messages=[{"role": "user", "content": f"Перепиши скрипт агронома живым языком:\n{script}"}]
        #     )
        #     return message.content[0].text

        return script

    def _format_why(self, reasons: list[str]) -> str:
        if not reasons:
            return "— признаки характерны для данной проблемы"
        return "\n".join(f"— {r}" for r in reasons)

    def _format_actions(self, actions: list[str]) -> str:
        return "\n".join(f"{i + 1}. {a}" for i, a in enumerate(actions))

    async def submit_to_pipeline(
        self, script: str, job_id: str, style: str = "calm_consultant"
    ) -> str | None:
        """Отправить скрипт во внешний video generation pipeline. Stub → None."""
        # TODO:
        # async with httpx.AsyncClient() as client:
        #     r = await client.post(
        #         f"{settings.video_pipeline_url}/generate",
        #         headers={"Authorization": f"Bearer {settings.video_pipeline_api_key}"},
        #         json={"script": script, "style": style, "reference_id": job_id},
        #     )
        #     return r.json().get("job_id")
        return None
