from __future__ import annotations

import json

from .models import AgentDecision


class DecisionError(RuntimeError):
    pass


def parse_decision(content: str) -> AgentDecision:
    clean = content.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        clean = "\n".join(lines)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise DecisionError(f"Model returned invalid structured JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise DecisionError("Model response must be a JSON object")
    public_message = str(data.get("public_message", "")).strip()
    decision_summary = str(data.get("decision_summary", "")).strip()
    if not public_message or not decision_summary:
        raise DecisionError("Model response is missing public_message or decision_summary")
    target = data.get("handoff_target")
    if target in ("", "none", "null"):
        target = None
    updates = data.get("workspace_updates", {})
    if not isinstance(updates, dict):
        updates = {}
    tool_calls = data.get("tool_calls", [])
    if not isinstance(tool_calls, list):
        tool_calls = []
    visual_plan = data.get("visual_plan")
    if not isinstance(visual_plan, dict):
        visual_plan = None
    return AgentDecision(
        public_message=public_message,
        decision_summary=decision_summary,
        handoff_target=str(target) if target is not None else None,
        handoff_reason=str(data.get("handoff_reason", "")).strip(),
        workspace_updates=updates,
        curator_decision=str(data["curator_decision"]).lower() if data.get("curator_decision") else None,
        final_exhibition=str(data["final_exhibition"]).strip() if data.get("final_exhibition") else None,
        visual_plan=visual_plan,
        tool_calls=tool_calls,
    )
