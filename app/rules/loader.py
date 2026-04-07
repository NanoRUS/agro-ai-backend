"""Загрузчик и кеш конфигурационных правил из JSON-файлов."""
import json
from pathlib import Path
from functools import lru_cache
from typing import Any

RULES_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def load_issue_catalog() -> dict[str, Any]:
    with open(RULES_DIR / "issue_catalog.json", encoding="utf-8") as f:
        data = json.load(f)
    return {issue["id"]: issue for issue in data["issues"]}


@lru_cache(maxsize=1)
def load_signals() -> dict[str, Any]:
    with open(RULES_DIR / "signals.json", encoding="utf-8") as f:
        return json.load(f)["signals"]


@lru_cache(maxsize=10)
def load_crop_config(crop: str) -> dict[str, Any]:
    path = RULES_DIR / "crops" / f"{crop}.json"
    if not path.exists():
        raise ValueError(f"Unknown crop: {crop}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_all_issues_for_crop(crop: str, plant_stage: str | None = None) -> list[dict[str, Any]]:
    """Вернуть ВСЕ issues (без фильтрации), используется для debug mode."""
    return get_issues_for_crop(crop, plant_stage)


def get_issues_for_crop(crop: str, plant_stage: str | None = None) -> list[dict[str, Any]]:
    """Вернуть список конфигов задач применимых к данной культуре с учётом переопределений."""
    catalog = load_issue_catalog()
    crop_cfg = load_crop_config(crop)

    applicable_ids: list[str] = crop_cfg["applicable_issues"]
    overrides: dict = crop_cfg.get("issue_overrides", {})
    stage_modifiers: dict = crop_cfg.get("stage_modifiers", {})

    result = []
    for issue_id in applicable_ids:
        if issue_id not in catalog:
            continue
        issue = dict(catalog[issue_id])  # shallow copy

        # Apply crop-level overrides
        if issue_id in overrides:
            ovr = overrides[issue_id]
            if "urgency_base" in ovr:
                issue["urgency_base"] = ovr["urgency_base"]
            if "weight_multiplier" in ovr:
                issue["_weight_multiplier"] = ovr["weight_multiplier"]

        # Apply stage modifiers
        if plant_stage and plant_stage in stage_modifiers:
            stage_mod = stage_modifiers[plant_stage]
            if issue_id in stage_mod:
                existing = issue.get("_weight_multiplier", 1.0)
                issue["_weight_multiplier"] = existing * stage_mod[issue_id]

        result.append(issue)
    return result
