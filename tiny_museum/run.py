from __future__ import annotations

import asyncio
import copy
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import HandoffMessage, TextMessage, ThoughtEvent, ToolCallExecutionEvent, ToolCallRequestEvent
from autogen_core import CancellationToken

from .autogen_swarm import agent_system_message, build_team
from .budget import BudgetExceeded, BudgetLedger, estimate_tokens
from .decision import DecisionError, parse_decision
from .image_generation import ImageGenerator, create_image_generator
from .models import AGENT_IDS, AppConfig, SwarmEvent, Usage
from .workspace import SharedWorkspace


class SwarmRun:
    def __init__(self, topic: str, config: AppConfig, storage_dir: Path, image_generator: ImageGenerator | None = None):
        self.id = uuid.uuid4().hex[:12]
        self.topic = " ".join(topic.split())[:300]
        self.config = copy.deepcopy(config)
        self.storage_dir = storage_dir
        self.workspace = SharedWorkspace(topic=self.topic)
        self.ledger = BudgetLedger(self.config)
        self.events: list[SwarmEvent] = []
        self.status = "created"
        self.termination_reason: str | None = None
        self.agent_status = {agent_id: "idle" for agent_id in AGENT_IDS}
        self.curator_rejections = 0
        self.curator_format_retries = 0
        self.malformed_tool_retries = 0
        self.cancel_requested = threading.Event()
        self.condition = threading.Condition()
        self._cancellation_lock = threading.Lock()
        self._current_cancellation: CancellationToken | None = None
        self.image_generator = image_generator if image_generator is not None else create_image_generator(self.config)
        self.image_path: Path | None = None

    def start(self) -> None:
        threading.Thread(target=self._run, name=f"museum-{self.id}", daemon=True).start()

    def cancel(self) -> None:
        self.cancel_requested.set()
        with self._cancellation_lock:
            if self._current_cancellation is not None:
                self._current_cancellation.cancel()
        self.emit("human_intervention", "A person requested cancellation. AutoGen is stopping the active turn safely.")

    def emit(self, event_type: str, message: str, **values: Any) -> SwarmEvent:
        with self.condition:
            event = SwarmEvent(
                id=len(self.events) + 1,
                type=event_type,
                public_message=message,
                meta={
                    "metrics": self.ledger.snapshot(),
                    "agent_status": dict(self.agent_status),
                    "workspace": self.workspace.to_dict(),
                    "orchestrator": "AutoGen AgentChat Swarm 0.7.5",
                    **values.pop("meta", {}),
                },
                **values,
            )
            self.events.append(event)
            self.condition.notify_all()
            return event

    def snapshot(self) -> dict[str, Any]:
        with self.condition:
            return {
                "id": self.id,
                "topic": self.topic,
                "status": self.status,
                "termination_reason": self.termination_reason,
                "orchestrator": "AutoGen AgentChat Swarm 0.7.5",
                "workspace": self.workspace.to_dict(),
                "metrics": self.ledger.snapshot(),
                "agent_status": dict(self.agent_status),
                "curator_rejections": self.curator_rejections,
                "image_url": f"/api/runs/{self.id}/image" if self.image_path else None,
                "events": [event.to_dict() for event in self.events],
            }

    def _run(self) -> None:
        try:
            asyncio.run(self._run_autogen())
        except Exception as exc:
            if self.status not in {"completed", "cancelled", "stopped"}:
                self._terminate("internal_error", f"The AutoGen run stopped safely: {type(exc).__name__}: {exc}")

    async def _run_autogen(self) -> None:
        self.status = "running"
        active = "scout"
        bundle = None
        self.emit("run_started", f"AutoGen AgentChat Swarm opened a new exhibition study about “{self.topic}”.", meta={"run_id": self.id})
        self.emit("assignment", "Curiosity Scout received the opening assignment.", agent=active)
        try:
            bundle = build_team(self.config)
            task: str | HandoffMessage = self._opening_task()
            while True:
                if self.cancel_requested.is_set():
                    self._terminate("manual_cancellation", "Run cancelled safely by a person.")
                    return
                if active != "curator" and self.ledger.total_tokens >= self.config.limits.curator_reserve_starts_at:
                    active, task = self._force_curator_reserve(active)

                self._preflight_call(active, task)
                self.agent_status[active] = "working"
                self.emit(
                    "model_call_started",
                    f"AutoGen activated {self.config.agents[active].display_name} for one bounded turn.",
                    agent=active,
                    meta={"model": self.config.agents[active].model, "provider": self.config.agents[active].provider},
                )
                cancellation = CancellationToken()
                with self._cancellation_lock:
                    self._current_cancellation = cancellation
                try:
                    turn = await self._consume_turn(bundle.team, task, active, cancellation)
                except Exception as exc:
                    with self._cancellation_lock:
                        self._current_cancellation = None
                    self.agent_status[active] = "idle"
                    if active == "curator" and self._is_truncated_tool_call(exc) and self.malformed_tool_retries < 1:
                        self.malformed_tool_retries += 1
                        self.emit(
                            "provider_retry",
                            "The Curator's approval JSON was truncated. AutoGen is retrying once with a shorter response.",
                            agent="curator",
                        )
                        await bundle.close()
                        bundle = build_team(self.config)
                        self.agent_status["curator"] = "queued"
                        task = HandoffMessage(
                            source="application_guardrail",
                            target="curator",
                            content=self._truncated_tool_retry_task(),
                        )
                        continue
                    raise
                with self._cancellation_lock:
                    self._current_cancellation = None
                self.agent_status[active] = "idle"

                if self.cancel_requested.is_set():
                    self._terminate("manual_cancellation", "Run cancelled safely by a person.")
                    return
                if self.ledger.warning_due():
                    self.emit("budget_warning", "The swarm has used 70% of its global token budget.")

                handoff = turn.get("handoff")
                approval = turn.get("approval")
                text_response = turn.get("text")
                if approval is not None:
                    if active != "curator":
                        raise DecisionError("Only the Curator may use the approval tool")
                    decision = parse_decision(approval)
                    format_problem = self._approval_format_problem(decision)
                    if format_problem:
                        if self.curator_format_retries >= self.config.limits.max_curator_format_retries:
                            self._terminate("needs_human_review", f"Curator output remained incomplete: {format_problem}")
                            return
                        self.curator_format_retries += 1
                        self.agent_status["curator"] = "queued"
                        self.emit(
                            "curator_revision_requested",
                            f"The application asked the Curator to expand the incomplete final exhibition: {format_problem}",
                            agent="curator",
                        )
                        task = HandoffMessage(
                            source="application_guardrail",
                            target="curator",
                            content=self._curator_format_revision_task(decision, format_problem),
                        )
                        continue
                    self._complete_from_curator(decision)
                    return
                if handoff is not None:
                    decision = parse_decision(handoff.content)
                    if decision.handoff_target != handoff.target:
                        raise DecisionError("AutoGen handoff target did not match its structured public payload")
                    if active != "curator":
                        decision.curator_decision = None
                        decision.final_exhibition = None
                    workspace_before = self.workspace.compact()
                    self.workspace.apply(decision.workspace_updates, active)
                    workspace_changed = workspace_before != self.workspace.compact()
                    event_type = "curator_rejection" if active == "curator" else "agent_message"
                    self.emit(
                        event_type,
                        decision.public_message,
                        agent=active,
                        decision_summary=decision.decision_summary,
                        handoff_target=handoff.target,
                        handoff_reason=decision.handoff_reason,
                        meta={"autogen_message": "HandoffMessage"},
                    )

                    if active == "curator":
                        stop_reason = self._record_curator_rejection(workspace_changed)
                        if stop_reason:
                            self.emit(
                                "human_intervention",
                                stop_reason,
                                agent="curator",
                                decision_summary="The bounded review cycle ended without approval.",
                            )
                            self._terminate("needs_human_review", stop_reason)
                            return

                    target, reason = self._resolve_target(active, handoff.target, decision.handoff_reason)
                    if self.ledger.total_tokens >= self.config.limits.curator_reserve_starts_at and target != "curator":
                        target = "curator"
                        reason = "Guardrail reroute: exploration is closed and remaining tokens are reserved for Curator finalization."
                    self.ledger.record_handoff(active, target)
                    self.emit(
                        "handoff",
                        f"AutoGen handed the exhibition from {self.config.agents[active].display_name} to {self.config.agents[target].display_name}.",
                        agent=active,
                        decision_summary=decision.decision_summary,
                        handoff_target=target,
                        handoff_reason=reason,
                        meta={"autogen_message": "HandoffMessage"},
                    )
                    source = active
                    active = target
                    self.agent_status[active] = "queued"
                    self.emit("assignment", f"{self.config.agents[active].display_name} accepted the AutoGen handoff.", agent=active)
                    task = HandoffMessage(source=source, target=target, content=self._resume_context(decision.public_message, reason))
                    continue

                if text_response is None:
                    raise DecisionError("AutoGen turn ended without a public response or handoff")
                if active != "curator":
                    raise DecisionError(f"{active} returned text instead of using an AutoGen handoff tool")
                decision = parse_decision(text_response.content)
                self._complete_from_curator(decision)
                return
        except asyncio.CancelledError:
            self._terminate("manual_cancellation", "Run cancelled safely by a person.")
        except BudgetExceeded as exc:
            self._terminate("budget_guard", str(exc))
        except DecisionError as exc:
            self._terminate("provider_error", str(exc))
        except Exception as exc:
            self._terminate("autogen_error", f"AutoGen stopped safely: {type(exc).__name__}: {exc}")
        finally:
            if bundle is not None:
                await bundle.close()

    async def _consume_turn(self, team, task: str | HandoffMessage, active: str, cancellation: CancellationToken) -> dict[str, Any]:
        result: dict[str, Any] = {"handoff": None, "approval": None, "text": None, "call_recorded": False}
        async for item in team.run_stream(task=task, cancellation_token=cancellation, output_task_messages=False):
            if isinstance(item, ThoughtEvent):
                continue
            if isinstance(item, ToolCallRequestEvent):
                calls = [{"name": call.name, "arguments": call.arguments, "call_id": call.id} for call in item.content]
                for call in item.content:
                    if call.name == "approve_exhibition":
                        values = json.loads(call.arguments)
                        result["approval"] = json.dumps(
                            {
                                "public_message": values.get("public_message", ""),
                                "decision_summary": values.get("decision_summary", ""),
                                "curator_decision": "approve",
                                "final_exhibition": values.get("final_exhibition"),
                                "visual_plan": {
                                    "center": values.get("visual_center", self.topic),
                                    "elements": values.get("visual_elements", []),
                                    "caption": values.get("visual_caption", ""),
                                },
                                "workspace_updates": {
                                    "facts": values.get("facts", []),
                                    "connections": values.get("connections", []),
                                    "narrative": values.get("narrative", []),
                                    "concerns": values.get("concerns", []),
                                },
                            },
                            ensure_ascii=False,
                        )
                usage, budget_error = self._record_autogen_usage(active, item.models_usage, json.dumps(calls, ensure_ascii=False))
                if budget_error is not None:
                    result["budget_error"] = budget_error
                result["call_recorded"] = True
                self.emit(
                    "tool_call",
                    "AutoGen requested: " + ", ".join(call["name"] for call in calls) + "\n" + json.dumps(calls, ensure_ascii=False, indent=2),
                    agent=active,
                    tool_calls=calls,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    usage_is_estimated=usage.estimated,
                    estimated_cost_usd=self._cost(active, usage),
                    meta={"autogen_message": "ToolCallRequestEvent"},
                )
            elif isinstance(item, ToolCallExecutionEvent):
                results = [{"name": value.name, "content": value.content, "call_id": value.call_id, "is_error": value.is_error} for value in item.content]
                self.emit(
                    "tool_result",
                    "AutoGen executed the handoff tool.\n" + json.dumps(results, ensure_ascii=False, indent=2),
                    agent=active,
                    tool_calls=results,
                    meta={"autogen_message": "ToolCallExecutionEvent"},
                )
            elif isinstance(item, HandoffMessage):
                result["handoff"] = item
            elif isinstance(item, TextMessage) and item.source in AGENT_IDS:
                if not result["call_recorded"]:
                    usage, budget_error = self._record_autogen_usage(active, item.models_usage, item.content)
                    if budget_error is not None:
                        result["budget_error"] = budget_error
                    result["call_recorded"] = True
                    self.emit(
                        "model_result",
                        "AutoGen returned a public text response.",
                        agent=active,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        usage_is_estimated=usage.estimated,
                        estimated_cost_usd=self._cost(active, usage),
                        meta={"autogen_message": "TextMessage"},
                    )
                result["text"] = item
            elif isinstance(item, TaskResult):
                result["stop_reason"] = item.stop_reason
        if not result["call_recorded"]:
            raise DecisionError("AutoGen did not report a model call for the turn")
        if result.get("budget_error") is not None:
            raise result["budget_error"]
        return result

    def _record_autogen_usage(self, agent_id: str, request_usage: Any, visible_output: str) -> tuple[Usage, BudgetExceeded | None]:
        if request_usage is None or request_usage.prompt_tokens + request_usage.completion_tokens <= 0:
            usage = Usage(
                input_tokens=estimate_tokens(agent_system_message(agent_id) + self._resume_context("", "")),
                output_tokens=estimate_tokens(visible_output),
                estimated=True,
            )
        else:
            usage = Usage(input_tokens=int(request_usage.prompt_tokens), output_tokens=int(request_usage.completion_tokens), estimated=False)
        try:
            self.ledger.record_call(agent_id, usage, self._cost(agent_id, usage))
        except BudgetExceeded as exc:
            return usage, exc
        return usage, None

    def _preflight_call(self, agent_id: str, task: str | HandoffMessage) -> None:
        task_text = task if isinstance(task, str) else task.content
        estimated_input = estimate_tokens(agent_system_message(agent_id) + task_text) + 500
        allowance = self.ledger.output_allowance(agent_id, estimated_input)
        configured = self.config.limits.curator_max_output_tokens if agent_id == "curator" else self.config.limits.specialist_max_output_tokens
        if allowance < configured:
            raise BudgetExceeded(f"The remaining budget cannot safely guarantee {agent_id}'s configured {configured}-token output cap")

    def _opening_task(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "assignment": "Begin the miniature museum. Investigate what is most useful, then choose the next agent dynamically.",
                "shared_workspace": self.workspace.compact(),
                "limits": self.ledger.snapshot(),
                "curator_review_policy": {
                    "rejections_used": self.curator_rejections,
                    "maximum_rejections": self.config.limits.max_curator_rejections,
                    "convergence_mode": self.curator_rejections >= self.config.limits.max_curator_rejections,
                    "instruction": "Approve with approve_exhibition when ready; do not request confirmation work.",
                },
            },
            ensure_ascii=False,
        )

    def _resume_context(self, latest_public_message: str, handoff_reason: str) -> str:
        recent = [
            {"agent": event.agent, "message": event.public_message[:400], "decision": event.decision_summary[:250]}
            for event in self.events
            if event.type in {"agent_message", "curator_rejection"}
        ][-2:]
        return json.dumps(
            {
                "topic": self.topic,
                "handoff_reason": handoff_reason,
                "latest_public_message": latest_public_message,
                "shared_workspace": self.workspace.compact(),
                "recent_relevant_public_messages": recent,
                "limits": self.ledger.snapshot(),
            },
            ensure_ascii=False,
        )

    def _force_curator_reserve(self, source: str) -> tuple[str, HandoffMessage]:
        reserve_start = self.config.limits.curator_reserve_starts_at
        reason = (
            f"Exploration closed at {reserve_start:,} tokens; "
            "the remaining budget is reserved for Curator finalization."
        )
        self.ledger.record_handoff(source, "curator")
        self.agent_status[source] = "idle"
        self.agent_status["curator"] = "queued"
        self.emit(
            "budget_warning",
            reason,
            agent=source,
            decision_summary="Stopped new exploratory work and protected the Curator reserve.",
            handoff_target="curator",
            handoff_reason=reason,
        )
        return "curator", HandoffMessage(source=source, target="curator", content=self._resume_context("Exploratory work has closed.", reason))

    def _resolve_target(self, source: str, proposed: str, reason: str) -> tuple[str, str]:
        if proposed not in AGENT_IDS or proposed == source:
            raise DecisionError(f"Invalid AutoGen handoff from {source} to {proposed}")
        allowed, block_reason = self.ledger.can_handoff(source, proposed)
        if allowed and self._target_has_budget(proposed, reason):
            return proposed, reason
        if allowed:
            block_reason = f"{self.config.agents[proposed].display_name} lacks enough personal budget for another safe turn"
        candidates = ["storysmith", "scout", "weaver"] if source == "curator" else ["curator", "scout", "weaver", "storysmith"]
        for candidate in candidates:
            if candidate == source:
                continue
            candidate_allowed, _ = self.ledger.can_handoff(source, candidate)
            if candidate_allowed and self._target_has_budget(candidate, reason):
                return candidate, f"Guardrail reroute: {block_reason}. {reason}".strip()
        raise BudgetExceeded(block_reason)

    def _target_has_budget(self, agent_id: str, reason: str) -> bool:
        estimated_input = estimate_tokens(agent_system_message(agent_id) + self._resume_context("", reason)) + 500
        configured = self.config.limits.curator_max_output_tokens if agent_id == "curator" else self.config.limits.specialist_max_output_tokens
        try:
            return self.ledger.output_allowance(agent_id, estimated_input) >= configured
        except BudgetExceeded:
            return False

    def _record_curator_rejection(self, workspace_changed: bool) -> str | None:
        self.curator_rejections += 1
        if self.curator_rejections > self.config.limits.max_curator_rejections:
            return "Curator rejection limit reached; the run needs human review instead of another callback."
        if self.curator_rejections >= 2 and not workspace_changed:
            return "Curator repeated a review without adding a new requirement; the run needs human review."
        return None

    def _approval_format_problem(self, decision) -> str | None:
        exhibition_words = len((decision.final_exhibition or "").split())
        visual_words = len(str((decision.visual_plan or {}).get("caption", "")).split())
        if exhibition_words < 150:
            return f"final exhibition has {exhibition_words} words; at least 150 are required"
        if visual_words < 45:
            return f"visual story has {visual_words} words; at least 45 are required"
        return None

    def _curator_format_revision_task(self, decision, problem: str) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "correction": problem,
                "instruction": (
                    "Call approve_exhibition again. Expand final_exhibition into a 150-250 word visitor-facing story "
                    "with a title and multiple paragraphs. Write visual_caption as a distinct 3-5 sentence, "
                    "45-120 word story explaining what the generated image is intended to depict."
                ),
                "incomplete_final_exhibition": decision.final_exhibition,
                "incomplete_visual_plan": decision.visual_plan,
                "shared_workspace": self.workspace.compact(),
            },
            ensure_ascii=False,
        )

    def _is_truncated_tool_call(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return "invalid tool call arguments" in message or "unexpected end of json input" in message

    def _truncated_tool_retry_task(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "instruction": (
                    "Call approve_exhibition with valid compact JSON. Write a 150-250 word final_exhibition and a "
                    "45-90 word visual_caption. Use empty facts, connections, narrative, and concerns arrays."
                ),
                "shared_workspace": self.workspace.compact(),
            },
            ensure_ascii=False,
        )

    def _complete_from_curator(self, decision) -> None:
        if decision.curator_decision != "approve" or not decision.final_exhibition:
            raise DecisionError("The Curator must reject by handoff or approve with a final exhibition")
        self.workspace.apply(decision.workspace_updates, "curator")
        self.workspace.final_exhibition = decision.final_exhibition
        self.workspace.final_visual_plan = decision.visual_plan
        self.emit(
            "agent_message",
            decision.public_message,
            agent="curator",
            decision_summary=decision.decision_summary,
            meta={"autogen_message": "approve_exhibition"},
        )
        self.emit(
            "curator_approval",
            "The Museum Curator approved the exhibition through AutoGen Swarm.",
            agent="curator",
            decision_summary=decision.decision_summary,
        )
        self._generate_exhibition_image(decision)
        self.status = "completed"
        self.termination_reason = "curator_approved"
        self.emit(
            "run_completed",
            "The exhibition is complete.",
            agent="curator",
            meta={
                "termination_reason": self.termination_reason,
                "final_exhibition": decision.final_exhibition,
                "final_visual_plan": decision.visual_plan,
                "image_url": f"/api/runs/{self.id}/image" if self.image_path else None,
            },
        )
        self._persist()

    def _generate_exhibition_image(self, decision) -> None:
        if self.image_generator is None:
            return
        self.status = "rendering"
        self.emit(
            "image_generation_started",
            f"The Curator's approved exhibition is being illustrated with {self.config.image_generation.model}.",
            agent="curator",
        )
        plan = decision.visual_plan or {}
        elements = ", ".join(str(value) for value in plan.get("elements", [])[:5])
        prompt = (
            "Create one polished isometric miniature museum diorama. "
            f"Central subject: {plan.get('center') or self.topic}. "
            f"Exhibition elements: {elements or self.topic}. "
            "Warm gallery lighting, handcrafted scale-model appearance, coherent composition, no written labels, square image."
        )
        destination = self.storage_dir / f"{self.id}.png"
        try:
            self.image_generator.generate(prompt, destination)
        except Exception as exc:
            self.emit(
                "image_generation_failed",
                f"The exhibition completed, but its optional image could not be created: {exc}",
                agent="curator",
            )
            return
        self.image_path = destination
        self.emit(
            "image_generated",
            "Z-Image Turbo created the Curator-approved exhibition image.",
            agent="curator",
            meta={"image_url": f"/api/runs/{self.id}/image", "image_model": self.config.image_generation.model},
        )

    def _cost(self, agent_id: str, usage: Usage) -> float:
        agent = self.config.agents[agent_id]
        provider = self.config.providers[agent.provider]
        return usage.input_tokens * provider.input_cost_per_million / 1_000_000 + usage.output_tokens * provider.output_cost_per_million / 1_000_000

    def _terminate(self, reason: str, message: str) -> None:
        self.status = "cancelled" if reason == "manual_cancellation" else "stopped"
        self.termination_reason = reason
        for agent_id in self.agent_status:
            self.agent_status[agent_id] = "idle"
        self.emit("run_terminated", message, meta={"termination_reason": reason})
        self._persist()

    def _persist(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        path = self.storage_dir / f"{self.id}.json"
        path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")


class RunRegistry:
    def __init__(self, config: AppConfig, storage_dir: Path):
        self.config = config
        self.storage_dir = storage_dir
        self.runs: dict[str, SwarmRun] = {}
        self.lock = threading.Lock()

    def create(self, topic: str) -> SwarmRun:
        if not topic.strip():
            raise ValueError("Topic cannot be empty")
        run = SwarmRun(topic, self.config, self.storage_dir)
        with self.lock:
            self.runs[run.id] = run
        run.start()
        return run

    def get(self, run_id: str) -> SwarmRun | None:
        with self.lock:
            return self.runs.get(run_id)
