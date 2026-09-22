# Roadmap

## Current vertical slice

- Four independently configured AutoGen `AssistantAgent`s.
- AutoGen AgentChat `Swarm` with model-selected `HandoffMessage`s and public reasons.
- Curator rejection, revision, approval, and sole completion authority.
- Compact shared workspace plus complete public transcript.
- Ollama and OpenAI-compatible AutoGen model clients.
- SSE browser UI with live events, budgets, statuses, statistics, configuration, and final exhibition.
- Application-level token, call, handoff, pair-loop, reserve, context, and cancellation guards.
- Offline deterministic demo and unit-testable coordination core.

## Near term

1. Add provider capability discovery and friendlier model compatibility diagnostics.
2. Add structured retry/repair for malformed JSON, charged against the same call and token budgets.
3. Add a small allow-listed research tool system with visible tool-call and tool-result events.
4. Add export to standalone HTML and print-ready PDF.
5. Add run history and replay from persisted transcript files.
6. Improve relevant-event selection with deterministic tagging rather than recency alone.

## Framework status

AutoGen AgentChat 0.7.5 is installed in the project-local Python 3.11 environment and is now the active swarm runtime. Local Ollama tool calling has been verified with `qwen3:30b-instruct`.

## Later

- Anthropic and Gemini provider adapters.
- Per-model tokenizer plugins for tighter preflight accounting.
- Optional SQLite persistence with retention controls.
- Multi-run comparison and exhibit remixing.
- Human “approve this fact” or “redirect this handoff” interventions.
- Accessibility audit, keyboard-first transcript controls, and localization.

## Explicit non-goals for the first release

- exposing private model reasoning;
- autonomous internet browsing without visible, allow-listed tools;
- silent fallback from local to paid providers;
- unbounded self-reflection or indefinite agent loops;
- production internet hosting without authentication and a security review.
