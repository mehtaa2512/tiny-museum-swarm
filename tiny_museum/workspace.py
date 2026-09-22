from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


WORKSPACE_SECTIONS = ("facts", "connections", "narrative", "concerns")


@dataclass(slots=True)
class SharedWorkspace:
    topic: str
    facts: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    narrative: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    curator_feedback: list[str] = field(default_factory=list)
    final_exhibition: str | None = None
    final_visual_plan: dict[str, Any] | None = None

    def apply(self, updates: dict[str, list[str]], author: str) -> None:
        for section, values in updates.items():
            if section not in WORKSPACE_SECTIONS or not isinstance(values, list):
                continue
            target: list[str] = getattr(self, section)
            for value in values[:8]:
                clean = " ".join(str(value).split()).strip()
                if clean and clean not in target:
                    target.append(clean[:800])
        if author == "curator":
            for concern in updates.get("concerns", []):
                clean = " ".join(str(concern).split()).strip()
                if clean and clean not in self.curator_feedback:
                    self.curator_feedback.append(clean[:800])

    def compact(self, max_items: int = 4, max_item_chars: int = 280) -> dict[str, Any]:
        def clipped(values: list[str], limit: int = max_items) -> list[str]:
            return [value[:max_item_chars] for value in values[-limit:]]

        return {
            "topic": self.topic,
            "facts": clipped(self.facts),
            "connections": clipped(self.connections),
            "narrative": clipped(self.narrative),
            "concerns": clipped(self.concerns),
            "curator_feedback": clipped(self.curator_feedback, 3),
            "has_final_exhibition": self.final_exhibition is not None,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
