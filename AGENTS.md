# Tiny Museum Swarm contributor guide

## Product invariants

- Preserve genuine model-selected handoffs. Do not replace the swarm with a fixed sequential pipeline.
- Only the Museum Curator may declare a run complete.
- Every handoff must emit a public decision summary and a public handoff reason.
- Never expose or claim to expose hidden chain-of-thought. Store and display only public messages, structured decisions, tool events, and operational metadata.
- Enforce token, call, handoff, pair-repeat, and context limits in application code.
- Keep the full public transcript for people while sending compact shared state and only recent relevant events to models.
- Provider-specific behavior belongs behind the provider adapter interface.
- Secrets come from environment variables and must never appear in config files, logs, events, or browser responses.

## Engineering style

- Prefer standard-library Python and small, readable modules.
- Keep coordination logic explicit enough for a learner to trace.
- Add tests for guardrails and state transitions when changing orchestration behavior.
- Use `python -m unittest discover -s tests` for the test suite.
- Use `python -m tiny_museum --demo` for an offline smoke test, or `python -m tiny_museum` with Ollama running.

## Documentation

- Update the focused document under `docs/` when changing architecture, protocol, budgets, providers, security, or roadmap behavior.
- Call out compatibility limitations directly; do not silently downgrade required behavior.
