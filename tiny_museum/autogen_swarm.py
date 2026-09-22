from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from collections.abc import AsyncGenerator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.base import Handoff
from autogen_agentchat.teams import Swarm
from autogen_core import CancellationToken, FunctionCall
from autogen_core.model_context import TokenLimitedChatCompletionContext
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    ModelCapabilities,
    ModelInfo,
    RequestUsage,
)
from autogen_core.tools import BaseTool, FunctionTool, Tool, ToolSchema
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .models import AGENT_IDS, AppConfig


ROLE_GUIDANCE = {
    "scout": (
        "You are the Curiosity Scout. Investigate origins, facts, engineering, history, materials, "
        "and unusual details. Distinguish well-supported knowledge from uncertainty."
    ),
    "weaver": (
        "You are the Connection Weaver. Discover defensible links across culture, science, psychology, "
        "language, technology, and symbolism. Reject vague or decorative associations."
    ),
    "storysmith": (
        "You are the Storysmith. Shape accurate shared material into a vivid miniature exhibition. "
        "Request missing facts or connections through a handoff instead of inventing them."
    ),
    "curator": (
        "You are the Museum Curator. Evaluate evidence, coherence, and visitor experience. Reject weak "
        "work with a targeted handoff. You alone may approve and complete the exhibition."
    ),
}


class ObservableHandoff(Handoff):
    """AutoGen handoff whose tool arguments are public and structured."""

    source: str

    @property
    def handoff_tool(self) -> BaseTool[Any, Any]:
        target = self.target
        source = self.source

        def transfer(
            public_message: str,
            decision_summary: str,
            handoff_reason: str,
            facts: list[str],
            connections: list[str],
            narrative: list[str],
            concerns: list[str],
        ) -> str:
            """Transfer work with a public contribution, decision, reason, and shared-state updates."""
            return json.dumps(
                {
                    "public_message": public_message,
                    "decision_summary": decision_summary,
                    "handoff_target": target,
                    "handoff_reason": handoff_reason,
                    "workspace_updates": {
                        "facts": facts,
                        "connections": connections,
                        "narrative": narrative,
                        "concerns": concerns,
                    },
                    "curator_decision": "reject" if source == "curator" else None,
                    "final_exhibition": None,
                    "tool_calls": [],
                },
                ensure_ascii=False,
            )

        return FunctionTool(transfer, name=self.name, description=self.description, strict=True)


def agent_system_message(agent_id: str) -> str:
    completion_rule = (
        "If the exhibition is ready, call approve_exhibition. Never hand off work merely for confirmation. "
        "Reject only for a concrete missing requirement, and list that requirement in concerns. "
        "The final_exhibition must be a complete 150-250 word visitor story with a title and several paragraphs; "
        "a title or tagline alone is invalid. "
        "The visual_caption must be a standalone 3-5 sentence visitor-facing story explaining the image's "
        "scientific, cultural, and narrative meaning; never submit only a title or tagline. For approval, keep facts, "
        "connections, narrative, and concerns empty unless adding genuinely new information; never repeat the workspace."
        if agent_id == "curator"
        else "You cannot complete the exhibition. You must finish every turn by calling exactly one handoff tool."
    )
    return f"""{ROLE_GUIDANCE[agent_id]}

You are one participant in a genuine AutoGen AgentChat Swarm. Choose the next agent from the available handoff
tools based on what the shared work needs; there is no fixed sequence. A handoff tool call is a public action.
Fill every tool argument: public_message, decision_summary, handoff_reason, and all four workspace arrays.
Use empty arrays when a section has no update. Keep claims concise and mark uncertainty honestly.

{completion_rule}

Never reveal or claim to reveal hidden chain-of-thought. Provide only conclusions, structured public decisions,
and reusable shared work. Do not claim to use research tools or sources that are not present.
"""


def handoffs_for(agent_id: str) -> list[ObservableHandoff]:
    descriptions = {
        "scout": "Transfer when factual, historical, material, or engineering investigation is needed.",
        "weaver": "Transfer when cross-domain connections and symbolism need development or repair.",
        "storysmith": "Transfer when the visitor narrative or exhibition structure needs development or repair.",
        "curator": "Transfer when the shared work is ready for critical review and possible approval.",
    }
    return [
        ObservableHandoff(source=agent_id, target=target, description=descriptions[target])
        for target in AGENT_IDS
        if target != agent_id
    ]


def curator_approval_tool() -> FunctionTool[Any, Any]:
    def approve_exhibition(
        public_message: str,
        decision_summary: str,
        final_exhibition: str,
        visual_center: str,
        visual_elements: list[str],
        visual_caption: str,
        facts: list[str],
        connections: list[str],
        narrative: list[str],
        concerns: list[str],
    ) -> str:
        """Approve with a 150-250 word final exhibition and a complete 3-5 sentence visual story."""
        return json.dumps(
            {
                "public_message": public_message,
                "decision_summary": decision_summary,
                "handoff_target": None,
                "handoff_reason": "",
                "workspace_updates": {
                    "facts": facts,
                    "connections": connections,
                    "narrative": narrative,
                    "concerns": concerns,
                },
                "curator_decision": "approve",
                "final_exhibition": final_exhibition,
                "visual_plan": {
                    "center": visual_center,
                    "elements": visual_elements[:5],
                    "caption": visual_caption,
                },
                "tool_calls": [],
            },
            ensure_ascii=False,
        )

    return FunctionTool(
        approve_exhibition,
        name="approve_exhibition",
        description="Approve the finished exhibition. Only use when no concrete revision remains.",
        strict=True,
    )


@dataclass(slots=True)
class AutoGenTeam:
    team: Swarm
    clients: list[ChatCompletionClient]

    async def close(self) -> None:
        for client in self.clients:
            await client.close()


def build_team(config: AppConfig) -> AutoGenTeam:
    agents: list[AssistantAgent] = []
    clients: list[ChatCompletionClient] = []
    for agent_id in AGENT_IDS:
        agent_config = config.agents[agent_id]
        output_limit = (
            config.limits.curator_max_output_tokens
            if agent_id == "curator"
            else config.limits.specialist_max_output_tokens
        )
        client = create_model_client(config, agent_id, output_limit)
        clients.append(client)
        repeat_safe_context = max(1_200, agent_config.token_budget // 2 - output_limit - 500)
        context_limit = config.limits.curator_context_tokens if agent_id == "curator" else config.limits.max_context_tokens
        context = TokenLimitedChatCompletionContext(
            model_client=client,
            token_limit=min(context_limit, repeat_safe_context),
        )
        agents.append(
            AssistantAgent(
                name=agent_id,
                description=ROLE_GUIDANCE[agent_id],
                model_client=client,
                model_context=context,
                tools=[curator_approval_tool()] if agent_id == "curator" else None,
                handoffs=handoffs_for(agent_id),
                system_message=agent_system_message(agent_id),
                model_client_stream=False,
                max_tool_iterations=1,
            )
        )
    return AutoGenTeam(team=Swarm(agents, max_turns=1, emit_team_events=False), clients=clients)


def create_model_client(config: AppConfig, agent_id: str, max_tokens: int) -> ChatCompletionClient:
    agent = config.agents[agent_id]
    provider = config.providers[agent.provider]
    if provider.kind == "demo":
        return DemoAutoGenClient(agent_id)
    if not provider.supports_tools:
        raise ValueError(
            f"Provider '{agent.provider}' is not marked as tool-capable. AutoGen Swarm requires tool calling for handoffs."
        )
    common: dict[str, Any] = {
        "model": agent.model,
        "parallel_tool_calls": False,
        "max_tokens": max_tokens,
        "temperature": 0.45,
    }
    if provider.kind == "ollama":
        common.update(
            base_url=f"{provider.base_url.rstrip('/')}/v1",
            api_key="ollama",
            model_info=_compatible_model_info(),
        )
    elif provider.kind == "openai_compatible":
        key = os.getenv(provider.api_key_env) if provider.api_key_env else None
        if provider.base_url.rstrip("/") == "https://api.openai.com/v1":
            if not key:
                raise ValueError(f"Missing API key environment variable: {provider.api_key_env}")
            common["api_key"] = key
        else:
            common.update(
                base_url=provider.base_url,
                api_key=key or "not-required",
                model_info=_compatible_model_info(),
            )
    else:
        raise ValueError(f"AutoGen does not support configured provider kind: {provider.kind}")
    return OpenAIChatCompletionClient(**common)


def _compatible_model_info() -> ModelInfo:
    return {
        "vision": False,
        "function_calling": True,
        "json_output": True,
        "family": "unknown",
        "structured_output": True,
    }


class DemoAutoGenClient(ChatCompletionClient):
    """Deterministic AutoGen model client for an offline end-to-end demonstration."""

    component_type = "model"
    component_provider_override = "tiny_museum.autogen_swarm.DemoAutoGenClient"

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.calls = 0
        self._actual = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._total = RequestUsage(prompt_tokens=0, completion_tokens=0)

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Tool | ToolSchema] = [],
        tool_choice: Tool | Literal["auto", "required", "none"] = "auto",
        json_output: bool | type[Any] | None = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token: CancellationToken | None = None,
    ) -> CreateResult:
        self.calls += 1
        usage = RequestUsage(prompt_tokens=310, completion_tokens=180)
        self._actual = usage
        self._total = RequestUsage(
            prompt_tokens=self._total.prompt_tokens + usage.prompt_tokens,
            completion_tokens=self._total.completion_tokens + usage.completion_tokens,
        )
        if self.agent_id == "curator" and self.calls > 1:
            payload = {
                "public_message": "The revision now supports a compact exhibition that moves from object, to system, to meaning. Approved.",
                "decision_summary": "Approved the evidence, structure, and visitor experience.",
                "final_exhibition": (
                    "# The Ordinary, Enlarged\n\n*A tiny museum of a familiar thing*\n\n"
                    "## Entrance — Hold It\nBegin at hand scale. Notice weight, edge, surface, and the assumptions built into use.\n\n"
                    "## Gallery I — The Hidden Machine\nWhere grip, movement, and resistance meet, wear preserves a history of repeated force.\n\n"
                    "## Gallery II — A Social Object\nRepeated rituals turn useful things into signs of access, care, identity, or memory.\n\n"
                    "## Gallery III — Evidence of Lives\nScratches, polish, repairs, and worn edges are not defects to hide. They are evidence "
                    "of hands, environments, and decisions accumulated over time. A manufactured object becomes a small archive when visitors learn to read it closely.\n\n"
                    "## Reflection Case\nWhat would you miss first: what it does, how it feels, or what it means? Compare your answer "
                    "with another visitor's. The difference reveals why ordinary objects deserve museum attention: their engineering may be shared, but their meanings remain personal.\n\n"
                    "Leave by looking again at the object you first considered familiar. Its materials connect geology to manufacture; its wear connects force to habit; "
                    "and its associations connect private memory to public culture. The exhibition enlarges the ordinary not by making it grand, but by making its hidden relationships visible."
                ),
                "visual_center": "Everyday object",
                "visual_elements": ["Material", "Human touch", "Hidden system", "Social meaning"],
                "visual_caption": (
                    "At the center, one familiar object is enlarged so visitors can read its material, mechanism, wear, and social meaning together. "
                    "The surrounding miniature cases move from touch and physical force to memory and cultural symbolism. Marks on the surface show repeated human use rather than damage. "
                    "The scene depicts how an ordinary tool can become both an engineered system and a personal archive."
                ),
                "facts": [],
                "connections": [],
                "narrative": [],
                "concerns": [],
            }
            return CreateResult(
                finish_reason="function_calls",
                content=[FunctionCall(id=uuid.uuid4().hex, name="approve_exhibition", arguments=json.dumps(payload, ensure_ascii=False))],
                usage=usage,
                cached=False,
            )

        target, payload = self._handoff_payload()
        tool_name = f"transfer_to_{target}"
        return CreateResult(
            finish_reason="function_calls",
            content=[FunctionCall(id=uuid.uuid4().hex, name=tool_name, arguments=json.dumps(payload, ensure_ascii=False))],
            usage=usage,
            cached=False,
        )

    def _handoff_payload(self) -> tuple[str, dict[str, Any]]:
        if self.agent_id == "scout" and self.calls == 1:
            return "weaver", _payload(
                "A familiar object's form records repeated attempts to solve an everyday human problem.",
                "Established a factual and material foundation.",
                "The factual base is ready for cross-domain interpretation.",
                facts=["Form reflects constraints of material, manufacture, grip, storage, and repeated use."],
            )
        if self.agent_id == "weaver":
            return "storysmith", _payload(
                "The object sits between private habit and public culture: both a tool and a social signal.",
                "Connected utility with symbolism and social behavior.",
                "The exhibition now has enough factual and symbolic material for a visitor journey.",
                connections=["Repeated bodily rituals can make an everyday tool carry abstract meaning."],
            )
        if self.agent_id == "storysmith":
            return "curator", _payload(
                "I propose a three-room journey: encounter the object, open its hidden systems, then examine its meanings.",
                "Drafted the exhibition arc and visitor experience.",
                "The Curator should test the draft for evidence, specificity, and completeness.",
                narrative=["A three-gallery arc moves from touch, to mechanism, to cultural meaning."],
            )
        if self.agent_id == "curator":
            return "scout", _payload(
                "The arc is elegant, but the central case needs one concrete engineering observation. I reject this draft for revision.",
                "Rejected the first draft for insufficient physical specificity.",
                "Add a precise observation about how form answers force, material, or repeated handling.",
                concerns=["The physical mechanism must be described concretely before approval."],
            )
        return "curator", _payload(
            "The requested revision is supplied: wear marks reveal where grip, movement, and resistance repeatedly meet.",
            "Repaired the Curator's request with a concrete physical lens.",
            "The engineering gap is now addressed and ready for final review.",
            facts=["Wear concentrates where grip, motion, and resistance meet, preserving a material record of use."],
        )

    def create_stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[str | CreateResult, None]:
        async def stream() -> AsyncGenerator[str | CreateResult, None]:
            yield await self.create(*args, **kwargs)

        return stream()

    async def close(self) -> None:
        return None

    def actual_usage(self) -> RequestUsage:
        return self._actual

    def total_usage(self) -> RequestUsage:
        return self._total

    def count_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Tool | ToolSchema] = []) -> int:
        return max(1, sum(len(str(message.content)) for message in messages) // 3 + len(tools) * 80)

    def remaining_tokens(self, messages: Sequence[LLMMessage], *, tools: Sequence[Tool | ToolSchema] = []) -> int:
        return max(0, 16_000 - self.count_tokens(messages, tools=tools))

    @property
    def capabilities(self) -> ModelCapabilities:  # type: ignore[override]
        return self.model_info

    @property
    def model_info(self) -> ModelInfo:
        return _compatible_model_info()


def _payload(
    public_message: str,
    decision_summary: str,
    handoff_reason: str,
    *,
    facts: list[str] | None = None,
    connections: list[str] | None = None,
    narrative: list[str] | None = None,
    concerns: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "public_message": public_message,
        "decision_summary": decision_summary,
        "handoff_reason": handoff_reason,
        "facts": facts or [],
        "connections": connections or [],
        "narrative": narrative or [],
        "concerns": concerns or [],
    }
