# Architecture

## Goals

The architecture uses AutoGen AgentChat while keeping the application-level rules explicit. A learner can follow an object from browser submission, through native AutoGen tool calls and handoffs, into shared state, and finally to Curator approval.

## Runtime flow

1. The browser posts a topic to `POST /api/runs`.
2. `RunRegistry` creates an isolated `SwarmRun` with copied configuration.
3. `autogen_swarm.build_team` creates four AutoGen `AssistantAgent`s and one AgentChat `Swarm`.
4. The opening assignment goes to Curiosity Scout. This is only the starting participant, not a fixed pipeline.
5. The active agent calls a structured AutoGen handoff tool, or the Curator calls the explicit `approve_exhibition` tool.
6. AutoGen emits `ToolCallRequestEvent`, `ToolCallExecutionEvent`, and `HandoffMessage`; the application translates each into a public UI event.
7. The application records usage, applies workspace updates, validates the chosen handoff, and resumes the same AutoGen team with compact shared state.
8. Only the Curator's explicit approval tool containing a final exhibition and safe visual plan completes the run. The browser renders the plan as an SVG miniature. Two Curator rejections are allowed; further review stops for human attention.
9. Every public event is streamed over SSE and persisted as JSON at termination.

## Components

### `tiny_museum/autogen_swarm.py`

Defines AutoGen agents, public structured handoff tools, independent model clients, token-limited model contexts, the AgentChat `Swarm`, and the deterministic offline AutoGen client.

### `tiny_museum/run.py`

Runs one bounded AutoGen turn at a time. It translates native AutoGen events, owns normalized event emission, validates handoffs, applies budgets, handles cancellation, enforces Curator-only completion, and persists transcripts.

### `tiny_museum/budget.py`

The application-level ledger. Limits are checked before every call and recorded after every response. It also tracks per-agent usage, costs, calls, global handoffs, and repeated pair handoffs.

### `tiny_museum/workspace.py`

The compact shared state: facts, connections, narrative material, concerns, Curator feedback, and the final exhibition. Updates are deduplicated and bounded per response.

### AutoGen model clients

Each agent gets an independent AutoGen `ChatCompletionClient`. Ollama and other compatible services use `OpenAIChatCompletionClient`; this satisfies AutoGen's model-independent protocol. Future Anthropic or Gemini clients can be selected without changing the browser or run ledger.

### `tiny_museum/server.py`

A standard-library threaded HTTP server. It serves static assets, a small JSON API, and one SSE stream per observed run. Each run itself executes in a background thread so cancellation and observation remain responsive.

### `tiny_museum/static/`

A framework-free browser client. It renders events with text-safe DOM operations, agent state, workspace changes, budget meters, statistics, configuration, and the final Curator-approved exhibition.

## Event model

Every `SwarmEvent` includes the common normalized fields required by the UI:

- agent and event type;
- public message and decision summary;
- handoff target and public reason;
- tool-call metadata;
- input and output token usage;
- whether usage is estimated;
- estimated cost;
- a snapshot of metrics, agent status, and shared workspace.

The event model intentionally contains no private scratchpad or chain-of-thought field.

## Concurrency and isolation

Runs are independent background threads with their own asyncio loop, AutoGen team, ledgers, workspaces, model clients, event lists, and copied configuration. A condition variable wakes SSE clients when a new public event arrives. Runtime model changes affect new runs only.

## Why one turn at a time

AutoGen owns agent execution and handoff semantics. The application deliberately sets `Swarm(max_turns=1)` and resumes the same stateful team after validating each result. This gives application code a hard checkpoint for token budgets, maximum calls, pair-repeat loops, the Curator reserve, and human cancellation without replacing AutoGen's model-selected routing.

The resumption message is a real AutoGen `HandoffMessage`. It contains compact workspace state and recent relevant public messages. Specialists use a 6,000-token context ceiling; the Curator uses a 3,000-token ceiling to prevent repeated reviews from exhausting its personal budget.
