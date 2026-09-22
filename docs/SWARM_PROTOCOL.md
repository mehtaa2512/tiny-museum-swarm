# Swarm protocol

## Participants

- **Curiosity Scout** develops grounded facts about origin, engineering, history, materials, and unusual details.
- **Connection Weaver** builds defensible links across culture, science, psychology, language, technology, and symbolism.
- **Storysmith** shapes the visitor journey and requests missing material rather than filling gaps with invention.
- **Museum Curator** evaluates support, coherence, and visitor value. This is the only role allowed to complete a run.

## Agent response contract

For continued work, each model calls one of AutoGen's structured handoff tools. The tool arguments are:

```json
{
  "public_message": "A concise, visitor-readable contribution.",
  "decision_summary": "A public summary of what was decided.",
  "handoff_reason": "Why the chosen target should act next.",
  "facts": [],
  "connections": [],
  "narrative": [],
  "concerns": []
}
```

The selected tool name determines the AutoGen handoff target. The tool returns a normalized JSON payload, and AutoGen wraps it in a native `HandoffMessage`. Missing public fields, mismatched targets, invalid JSON, or plain specialist text cause visible safe termination.

Only final Curator approval is plain structured text. It must include `curator_decision: "approve"` and a non-empty Markdown `final_exhibition`.

## Handoffs

A valid handoff is a native AutoGen handoff tool call with a known target other than the current agent and a public reason. The model chooses the tool based on the work, so routes can branch or return to an earlier specialist.

If a model omits or invalidates its target, the guardrail chooses a safe fallback: normally the Curator for review, or Curiosity Scout after an incomplete Curator rejection. If a proposed pair has repeated too often, the guardrail may reroute to another eligible agent and publishes that fact in the handoff reason.

Every handoff increments both the global count and an unordered agent-pair count. This catches `A → B → A → B` loops even when direction alternates.

## Curator authority

Specialists have no completion path. Curator approval is accepted only when it contains a non-empty final exhibition. Curator rejection must use an AutoGen handoff tool targeting the specialist best equipped to repair the stated concern.

## Public observability

The public transcript can contain:

- run opening and assignment events;
- model-call start events;
- normalized agent messages;
- handoffs and reasons;
- Curator rejection and approval;
- tool requests or results when a future executor is enabled;
- budget warnings and reserve activation;
- human cancellation;
- completion or safe termination reason.

“Public” means deliberately produced conclusions and structured operational metadata. The system does not request, store, infer, or claim to expose hidden reasoning.

## Termination

A run stops on the first applicable condition:

- Curator approval with a final exhibition;
- manual cancellation;
- global or per-agent token guard;
- model-call limit;
- handoff or repeated-pair limit;
- provider compatibility, connection, timeout, or response-shape error;
- unexpected internal error, reported without continuing in an unknown state.
