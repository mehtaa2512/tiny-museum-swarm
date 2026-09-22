from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field

from .models import AppConfig, Usage


class BudgetExceeded(RuntimeError):
    pass


@dataclass(slots=True)
class BudgetLedger:
    config: AppConfig
    total_tokens: int = 0
    model_calls: int = 0
    handoffs: int = 0
    estimated_cost_usd: float = 0.0
    per_agent_tokens: Counter[str] = field(default_factory=Counter)
    per_agent_calls: Counter[str] = field(default_factory=Counter)
    per_agent_handoffs: Counter[str] = field(default_factory=Counter)
    pair_handoffs: Counter[tuple[str, str]] = field(default_factory=Counter)
    warned: bool = False

    def output_allowance(self, agent_id: str, input_tokens: int) -> int:
        limits = self.config.limits
        if self.model_calls >= limits.max_model_calls:
            raise BudgetExceeded("Maximum model calls reached")
        if agent_id != "curator" and self.total_tokens >= limits.curator_reserve_starts_at:
            raise BudgetExceeded("Exploration budget closed; remaining tokens are reserved for the Curator")
        global_left = limits.total_tokens - self.total_tokens - input_tokens
        agent_left = self.config.agents[agent_id].token_budget - self.per_agent_tokens[agent_id] - input_tokens
        configured_max = limits.curator_max_output_tokens if agent_id == "curator" else limits.specialist_max_output_tokens
        allowance = min(configured_max, global_left, agent_left)
        if allowance < 64:
            raise BudgetExceeded(f"Insufficient safe token allowance for {agent_id}")
        return allowance

    def record_call(self, agent_id: str, usage: Usage, cost_usd: float) -> None:
        new_total = self.total_tokens + usage.total
        new_agent_total = self.per_agent_tokens[agent_id] + usage.total
        self.total_tokens = new_total
        self.per_agent_tokens[agent_id] = new_agent_total
        self.model_calls += 1
        self.per_agent_calls[agent_id] += 1
        self.estimated_cost_usd += cost_usd
        if new_total > self.config.limits.total_tokens:
            raise BudgetExceeded(
                f"Provider usage crossed the {self.config.limits.total_tokens:,}-token hard limit"
            )
        if new_agent_total > self.config.agents[agent_id].token_budget:
            raise BudgetExceeded(f"{agent_id} crossed its hard token budget")

    def can_handoff(self, source: str, target: str) -> tuple[bool, str]:
        if self.handoffs >= self.config.limits.max_handoffs:
            return False, "Maximum handoff count reached"
        pair = tuple(sorted((source, target)))
        if self.pair_handoffs[pair] >= self.config.limits.max_pair_handoffs:
            return False, f"Repeated handoff limit reached for {source} and {target}"
        return True, ""

    def record_handoff(self, source: str, target: str) -> None:
        allowed, reason = self.can_handoff(source, target)
        if not allowed:
            raise BudgetExceeded(reason)
        self.handoffs += 1
        self.per_agent_handoffs[source] += 1
        self.pair_handoffs[tuple(sorted((source, target)))] += 1

    def warning_due(self) -> bool:
        threshold = int(self.config.limits.total_tokens * self.config.limits.warn_at_fraction)
        if not self.warned and self.total_tokens >= threshold:
            self.warned = True
            return True
        return False

    def snapshot(self) -> dict[str, object]:
        limits = self.config.limits
        return {
            "total_tokens": self.total_tokens,
            "total_token_budget": limits.total_tokens,
            "model_calls": self.model_calls,
            "max_model_calls": limits.max_model_calls,
            "handoffs": self.handoffs,
            "max_handoffs": limits.max_handoffs,
            "estimated_cost_usd": round(self.estimated_cost_usd, 6),
            "per_agent": {
                agent_id: {
                    "tokens": self.per_agent_tokens[agent_id],
                    "budget": agent.token_budget,
                    "calls": self.per_agent_calls[agent_id],
                    "handoffs": self.per_agent_handoffs[agent_id],
                }
                for agent_id, agent in self.config.agents.items()
            },
        }


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)
