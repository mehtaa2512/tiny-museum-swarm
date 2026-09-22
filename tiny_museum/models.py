from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


AGENT_IDS = ("scout", "weaver", "storysmith", "curator")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ProviderConfig:
    kind: str
    base_url: str
    api_key_env: str | None = None
    timeout_seconds: int = 180
    supports_tools: bool = False
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0


@dataclass(slots=True)
class AgentConfig:
    display_name: str
    provider: str
    model: str
    token_budget: int
    color: str


@dataclass(slots=True)
class Limits:
    total_tokens: int = 80_000
    warn_at_fraction: float = 0.7
    curator_reserve_starts_at: int = 70_000
    max_model_calls: int = 10
    max_handoffs: int = 9
    max_pair_handoffs: int = 2
    max_curator_rejections: int = 2
    max_curator_format_retries: int = 1
    max_context_tokens: int = 6_000
    curator_context_tokens: int = 3_000
    specialist_max_output_tokens: int = 800
    curator_max_output_tokens: int = 1_800


@dataclass(slots=True)
class ImageGenerationConfig:
    enabled: bool = True
    provider: str = "ollama_image"
    model: str = "x/z-image-turbo:fp8"
    size: str = "1024x1024"
    timeout_seconds: int = 600


@dataclass(slots=True)
class AppConfig:
    server: dict[str, Any]
    limits: Limits
    providers: dict[str, ProviderConfig]
    agents: dict[str, AgentConfig]
    image_generation: ImageGenerationConfig = field(default_factory=ImageGenerationConfig)


@dataclass(slots=True)
class Usage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class AgentDecision:
    public_message: str
    decision_summary: str
    handoff_target: str | None = None
    handoff_reason: str = ""
    workspace_updates: dict[str, list[str]] = field(default_factory=dict)
    curator_decision: str | None = None
    final_exhibition: str | None = None
    visual_plan: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class SwarmEvent:
    id: int
    type: str
    public_message: str
    timestamp: str = field(default_factory=utc_now)
    agent: str | None = None
    decision_summary: str = ""
    handoff_target: str | None = None
    handoff_reason: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    usage_is_estimated: bool = False
    estimated_cost_usd: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
