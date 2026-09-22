# Providers

## Model-client interface

AutoGen's `ChatCompletionClient` is the model-independent adapter boundary. The application constructs one client per agent, so providers and models can be mixed inside a single swarm.

AutoGen normalizes model creation, token counting, usage, function calls, and cancellation. Tiny Museum normalizes AutoGen messages into its public `SwarmEvent` contract.

## Ollama

The default provider uses AutoGen's `OpenAIChatCompletionClient` against Ollama's OpenAI-compatible endpoint at `http://127.0.0.1:11434/v1`. Parallel tool calls are disabled because a swarm turn must choose exactly one handoff.

Default assignments:

| Agent | Model |
| --- | --- |
| Curiosity Scout | `qwen3:30b-instruct` |
| Connection Weaver | `qwen3:30b-instruct` |
| Storysmith | `qwen3:30b-instruct` |
| Museum Curator | `decision-qwen3:30b-16k` |

The health endpoint probes only local Ollama and lists visible models. A missing daemon, model, or tool-call capability becomes a visible error; the run never silently switches to a hosted service. `qwen3:30b-instruct` has been verified locally with an actual AutoGen handoff.

After Curator approval, the application calls Ollama's native `/api/generate` endpoint once with `x/z-image-turbo:fp8`. Ollama temporarily removed image generation after 0.32.5, so Tiny Museum keeps the current Ollama service for Qwen and auto-starts an isolated 0.32.5 image sidecar on port 11435. The generated PNG is stored beside the run transcript and shown above the final exhibition. Image failure is reported publicly but does not invalidate the Curator-approved exhibition. Disable this optional step with `image_generation.enabled: false`.

### Tokenizer compatibility note

AutoGen 0.7.5 does not recognize the custom Ollama model name `qwen3:30b-instruct` in its `tiktoken` registry and logs that it is using `cl100k_base` for context estimation. This does not affect Ollama's exact prompt and completion usage returned with each model response. Tiny Museum uses those reported values for the hard ledger and visibly marks estimates whenever exact usage is absent.

## OpenAI

The `openai` entry uses AutoGen's same client with `https://api.openai.com/v1`. Set `OPENAI_API_KEY` in the process environment and configure current model pricing if cost estimates are needed.

## LM Studio, vLLM, and compatible endpoints

The `compatible` entry defaults to `http://127.0.0.1:1234/v1` and reads `OPENAI_COMPATIBLE_API_KEY` when configured. Change the base URL and model per local server. The endpoint must support Chat Completions and JSON-object response mode for this initial slice.

Some “compatible” servers implement only part of the OpenAI API. If the server rejects `response_format`, usage fields, or `max_tokens`, the application reports the provider error clearly instead of guessing at a different protocol.

## Tool compatibility

AutoGen Swarm requires tool calling because handoffs are tools. Provider configuration must set `supports_tools: true`, and the selected model must genuinely produce function calls. An incompatible provider produces a direct compatibility error. The browser displays every handoff tool request and result.

Future research tools should add:

1. a small allow-listed tool registry;
2. provider-specific tool schema translation;
3. argument validation and bounded execution;
4. separate public tool-call and tool-result events;
5. result compaction before returning data to a model.

## Adding Anthropic or Gemini

Construct the relevant AutoGen `ChatCompletionClient` in `create_model_client`. The agents, browser, budget ledger, and event protocol should not change.
