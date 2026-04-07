"""
Explanation Layer — формирует человекочитаемые объяснения из результатов scoring.

Отделён от scoring engine: не считает баллы, только переводит их в текст.
"""
from __future__ import annotations
from app.services.scoring_engine import IssueScore, get_confidence_label
from app.schemas.analyze import IssueResult


class ExplanationService:
    def build_issue_result(self, issue: IssueScore) -> IssueResult:
        why_lines = self._build_why(issue)
        return IssueResult(
            id=issue.id,
            title=issue.title,
            category=issue.category,
            score=issue.score,
            confidence_label=get_confidence_label(issue.score),
            why=why_lines,
            today_actions=issue.today_actions,
            what_to_check_next=issue.what_to_check_next,
        )

    def _build_why(self, issue: IssueScore) -> list[str]:
        lines: list[str] = []

        # Use human-readable explanation factors for active signals
        for signal, explanation in issue.explanation_factors.items():
            if issue.contributing_signals.get(signal, 0) > 0:
                lines.append(explanation)

        # Fallback: generic score statement
        if not lines:
            label = get_confidence_label(issue.score)
            label_text = {"high": "высокая", "medium": "средняя", "low": "низкая"}[label]
            lines.append(f"Уверенность системы: {label_text} ({issue.score:.0%})")

        return lines

    def merge_top_actions(self, scored_issues: list[IssueScore]) -> list[str]:
        """Merge today_actions from top issues, deduplicated, primary issue first."""
        seen: set[str] = set()
        merged: list[str] = []
        for issue in scored_issues:
            for action in issue.today_actions:
                normalized = action.lower().strip()
                if normalized not in seen:
                    seen.add(normalized)
                    merged.append(action)
        return merged

    def merge_check_next(self, scored_issues: list[IssueScore]) -> list[str]:
        seen: set[str] = set()
        merged: list[str] = []
        for issue in scored_issues:
            for item in issue.what_to_check_next:
                normalized = item.lower().strip()
                if normalized not in seen:
                    seen.add(normalized)
                    merged.append(item)
        return merged
