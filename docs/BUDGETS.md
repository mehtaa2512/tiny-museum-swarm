# Budgets and limits

Budgets are enforcement rules in `BudgetLedger`, not suggestions embedded only in prompts.

## Defaults

| Limit | Default |
| --- | ---: |
| Global input + output tokens | 80,000 |
| Curiosity Scout | 20,000 |
| Connection Weaver | 20,000 |
| Storysmith | 20,000 |
| Museum Curator | 20,000 |
| Warning | 70% / 56,000 tokens |
| Exploration closes | 70,000 tokens |
| Curator reserve | 10,000 tokens |
| Model calls | 10 |
| Handoffs | 9 |
| Handoffs between the same pair | 2 |
| Curator rejections | 2 |
| Specialist output per call | 800 tokens |
| Curator output per call | 1,800 tokens |
| Specialist request context | 6,000 tokens |
| Curator request context | 3,000 tokens |

Per-agent budgets must sum to the global budget or configuration loading fails.

## Preflight enforcement

Before a call, the ledger estimates prompt tokens conservatively at roughly one token per three characters. It subtracts that estimate from both global and per-agent remaining budgets, then lowers the provider's output cap to the smallest remaining allowance. A call is refused if fewer than 64 output tokens remain.

This makes the 80,000-token ceiling operational even when a prompt is large. The provider's returned usage is checked again after the response. A provider that violates the requested output cap causes immediate safe termination.

## Reserve behavior

At or beyond 70,000 consumed tokens, no specialist may begin new exploratory work. If a specialist would act, the application emits a public budget warning and forces a counted handoff to the Curator. The remaining 10,000 tokens are not a separate account; they remain subject to the Curator's 20,000-token personal cap and the 80,000 global cap.

## Exact and estimated usage

Ollama exposes `prompt_eval_count` and `eval_count`; OpenAI-compatible APIs commonly expose `prompt_tokens` and `completion_tokens`. Those values are treated as exact provider-reported usage.

When either value is absent, input and output are conservatively estimated from text length. The normalized event sets `usage_is_estimated: true`, and the UI marks the call with a tilde. Estimated usage still counts against every hard limit.

## Cost estimates

Cost is computed from provider configuration:

```text
input_tokens × input_cost_per_million / 1,000,000
+ output_tokens × output_cost_per_million / 1,000,000
```

Local Ollama defaults to zero. Hosted-provider prices intentionally default to zero because pricing varies by model and time; configure current rates before treating the displayed estimate as meaningful.

## Convergence behavior

The Curator approves through an explicit `approve_exhibition` tool. It may reject at most twice. A third rejection, or a repeated rejection that adds no new requirement, stops as `needs_human_review` instead of spending another callback. This preserves model-selected routing during exploration while bounding final review.
