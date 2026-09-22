from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import AGENT_IDS, AgentConfig, AppConfig, ImageGenerationConfig, Limits, ProviderConfig


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "agents.json"


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path or os.getenv("TINY_MUSEUM_CONFIG", DEFAULT_CONFIG))
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    providers = {name: ProviderConfig(**value) for name, value in raw["providers"].items()}
    agents = {name: AgentConfig(**value) for name, value in raw["agents"].items()}
    config = AppConfig(
        server=raw.get("server", {}),
        limits=Limits(**raw.get("limits", {})),
        providers=providers,
        agents=agents,
        image_generation=ImageGenerationConfig(**raw.get("image_generation", {})),
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    missing = set(AGENT_IDS) - set(config.agents)
    if missing:
        raise ValueError(f"Missing required agents: {', '.join(sorted(missing))}")
    for agent_id, agent in config.agents.items():
        if agent.provider not in config.providers:
            raise ValueError(f"Agent {agent_id} references unknown provider {agent.provider}")
        if agent.token_budget <= 0:
            raise ValueError(f"Agent {agent_id} must have a positive token budget")
    if sum(agent.token_budget for agent in config.agents.values()) != config.limits.total_tokens:
        raise ValueError("Per-agent token budgets must sum to the global token budget")
    if config.limits.curator_reserve_starts_at >= config.limits.total_tokens:
        raise ValueError("Curator reserve threshold must be below the global token budget")
    if config.limits.max_curator_rejections < 1:
        raise ValueError("Curator must be allowed at least one rejection")
    if config.limits.curator_context_tokens > config.limits.max_context_tokens:
        raise ValueError("Curator context cannot exceed the global context ceiling")
    image = config.image_generation
    if image.enabled:
        if image.provider not in config.providers:
            raise ValueError(f"Image generation references unknown provider {image.provider}")
        if config.providers[image.provider].kind != "ollama_image":
            raise ValueError("Image generation currently requires an Ollama provider")
        if not image.model.strip():
            raise ValueError("Image generation model cannot be empty")
        if "x" not in image.size or not all(part.isdigit() for part in image.size.split("x", 1)):
            raise ValueError("Image generation size must look like 1024x1024")


def public_config(config: AppConfig) -> dict[str, Any]:
    providers: dict[str, dict[str, Any]] = {}
    for name, provider in config.providers.items():
        value = asdict(provider)
        value.pop("api_key_env", None)
        providers[name] = value
    return {
        "orchestrator": "AutoGen AgentChat Swarm 0.7.5",
        "server": config.server,
        "limits": asdict(config.limits),
        "image_generation": asdict(config.image_generation),
        "providers": providers,
        "agents": {name: asdict(agent) for name, agent in config.agents.items()},
    }


def apply_runtime_agent_config(config: AppConfig, updates: dict[str, Any]) -> None:
    for agent_id, value in updates.items():
        if agent_id not in config.agents:
            raise ValueError(f"Unknown agent: {agent_id}")
        provider_name = str(value.get("provider", config.agents[agent_id].provider))
        model = str(value.get("model", config.agents[agent_id].model)).strip()
        if provider_name not in config.providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        if not model:
            raise ValueError("Model name cannot be empty")
        config.agents[agent_id].provider = provider_name
        config.agents[agent_id].model = model
