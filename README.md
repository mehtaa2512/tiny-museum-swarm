# Tiny Museum Swarm

Tiny Museum Swarm is a fully local-first learning project where four independently configured agents build a miniature digital museum about an ordinary object or idea. The agents choose who should work next, publish a structured reason for every handoff, share a compact workspace, and remain bounded by hard application-level budgets.

The first vertical slice includes:

- a genuine handoff loop rather than a fixed Researcher → Writer → Verifier pipeline;
- Curiosity Scout, Connection Weaver, Storysmith, and Museum Curator roles;
- Curator rejection, targeted revision, and Curator-only completion;
- AutoGen AgentChat `Swarm` with native `HandoffMessage`, tool-call, and tool-result events;
- Ollama, OpenAI, and generic OpenAI-compatible models through AutoGen model clients;
- a standard-library local Python server with a live SSE browser interface;
- complete public transcript persistence with compact model context;
- global and per-agent token limits, call limits, handoff limits, pair-loop guards, a Curator reserve, cancellation, and safe termination;
- exact provider usage when available, or visibly marked conservative estimates;
- an offline demo provider for testing the full interface without spending tokens.
- one local Z-Image Turbo FP8 illustration generated only after Curator approval.

## Quick start

Requirements: Python 3.11+ and, for real model runs, [Ollama](https://ollama.com/) running locally. A project-local Python 3.11 environment is recommended:

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m tiny_museum
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765), enter something ordinary, and watch the handoffs.

The default configuration expects these installed models:

```text
qwen3:30b-instruct
decision-qwen3:30b-16k
x/z-image-turbo:fp8
```

Current Ollama releases temporarily disable image generation. Tiny Museum therefore keeps the current Ollama service for Qwen and auto-starts the official Ollama 0.32.5 binary in `work/ollama-0.32.5/` on port 11435 only for the final image.

If Ollama is not running, start it in another terminal:

```bash
ollama serve
```

To exercise the complete UI and revision loop without calling a model:

```bash
.venv/bin/python -m tiny_museum --demo
```

The repository pins the tested AutoGen AgentChat and extension packages at `0.7.5`.

## Configuration

Edit `config/agents.json` or copy `config/agents.example.json`. Each agent chooses its own provider and model. Browser changes are runtime-only and affect the next run; they never write secrets to disk.

For hosted providers, copy `.env.example`, set the relevant environment variable in your shell, and update the agent provider. The application reads keys only on the server. It never returns them through the configuration API or stores them in transcripts.

Costs default to zero. For accurate hosted-provider estimates, enter that model's current input and output price per million tokens in the provider configuration.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```

The offline demo is the recommended browser smoke test. Complete public transcripts are written to `.tiny-museum/runs/<run-id>.json` and ignored by Git.

## How to read the project

Start with `tiny_museum/autogen_swarm.py`: it defines the AutoGen agents, structured handoff tools, model clients, and `Swarm`. Then read `tiny_museum/run.py`, which translates AutoGen's event stream into public UI events and applies application guardrails. The browser is plain HTML, CSS, and JavaScript under `tiny_museum/static/`.

More detail lives in:

- [Architecture](docs/ARCHITECTURE.md)
- [Swarm protocol](docs/SWARM_PROTOCOL.md)
- [Budgets and limits](docs/BUDGETS.md)
- [Providers](docs/PROVIDERS.md)
- [Security](docs/SECURITY.md)
- [Roadmap](docs/ROADMAP.md)

## AutoGen implementation

The application uses Microsoft AutoGen AgentChat `Swarm` 0.7.5. Each agent is an `AssistantAgent` with its own model client and token-limited context. Handoffs are genuine AutoGen tool calls producing `HandoffMessage` objects. The application pauses after each bounded AutoGen turn to enforce global, per-agent, call, handoff, pair-repeat, reserve, and cancellation rules before allowing the team to continue.

AutoGen requires tool-capable models for `Swarm`. The installed `qwen3:30b-instruct` model was verified through Ollama's OpenAI-compatible endpoint with a real AutoGen handoff request, execution event, and `HandoffMessage`.
