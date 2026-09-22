# Security

## Local-first boundary

The server binds to `127.0.0.1` by default. This is an intentional security boundary: the API has no authentication and should not be exposed directly to a network. Changing the host to `0.0.0.0` requires adding authentication and reviewing browser-origin protections first.

Ollama requests remain local by default. Selecting OpenAI or another remote compatible provider sends prompts and compact shared state to that provider; the UI makes the selected provider visible on each agent card and model-call event.

## Secrets

- API keys are read from environment variables named in server-side configuration.
- `.env` is ignored by Git; `.env.example` contains placeholders only.
- The public configuration response removes key-variable names as a small defense against unnecessary metadata disclosure.
- Keys are never placed in events, workspaces, persisted transcripts, error bodies, or browser storage.

## Untrusted model output

Model output is untrusted. The backend validates JSON shape and known agent targets. Workspace values are converted to strings, whitespace-normalized, length-limited, and deduplicated. The browser uses `textContent` for messages and a small text-only Markdown renderer for exhibitions, preventing model-produced HTML from executing.

## HTTP surface

Static paths are allow-listed. JSON bodies are capped at 1 MB. Responses disable MIME sniffing and caching. Runtime configuration accepts only known agents and providers, and model names cannot be empty.

The local server currently has no CSRF token because it is intended only for loopback use. A networked deployment must add origin checks, authentication, CSRF protection, TLS, rate limiting, and stricter persistence permissions.

## Transcript privacy

Complete public transcripts are stored under `.tiny-museum/runs/` and ignored by Git. They may still contain the user's topic and model-produced text. Delete those files when they are no longer wanted. Hidden chain-of-thought is neither requested nor stored.

## Cancellation

Manual cancellation emits a public intervention event and calls AutoGen's active `CancellationToken`. The application also checks its own cancellation flag before every turn, so no further handoff begins after cancellation.
