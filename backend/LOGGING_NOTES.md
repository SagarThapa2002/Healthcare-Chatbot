# Server-side logging — design notes and policy (Phase 5.5)

## Current status: metadata-only structured logging, no transcript storage

`webhook.py`'s two previous `print()` calls (`print("Received JSON:", payload)`
and `print("Webhook error:", str(e))`) are gone. All backend logging now goes
through Python's stdlib `logging` module, configured once in `app.py`. No new
dependency was added.

## What is logged

Every log line is metadata only:

- `request_id` — the same id returned to the client in `meta.requestId` (see
  "Request ID architecture" below)
- `intent` — the Dialogflow intent display name (e.g. `"General FAQ"`,
  `"Book Appointment"`) — a category label, not user content
- `success` / policy `category` (e.g. `allowed`, `diagnosis_request`,
  `provider_unavailable`, `unsafe_output_blocked`) — labels from
  `assistant_service`'s fixed set of category constants, never free text
- `provider` — which LLM provider handled a request (`claude` or `mock`)
- `exception_type` — the Python exception **class name** on a failure (e.g.
  `KeyError`, `ProviderAPIError`), never `str(exception)`

## What is never logged

- The raw request body or `queryResult.parameters` (`symptom`, `message`,
  `name`, `date`, `time`)
- Any LLM prompt sent to Claude, or any LLM response text
- `str(exception)` / exception messages, tracebacks, or any other
  exception detail that could echo request content
- API keys or any other environment variable value

These are the same values `backend/assistant_service.py` and
`backend/webhook.py` already refuse to put in an **API response** — this
policy extends that same rule to the **server-side log stream**. Logging
happens only on the server, never in the HTTP response, but the content
restriction is identical: user-supplied text and secrets never appear in
either place.

## No raw transcript storage

This phase does not add conversation transcript storage, in raw or any other
form. Nothing in the current app needs conversation history — messages in
`frontend/src/hooks/useConversation.js` live only in React state and are lost
on refresh, by design, and this project's own stated policy is synthetic/demo
data only (see `backend/LLM_ASSISTANT_NOTES.md`). Persisting transcripts would
create a new PII/health-data storage surface with no corresponding feature
need, so it isn't added here.

## Retention considerations

There is no code-managed log persistence — logs go to stdout/stderr via
`logging.basicConfig`, exactly like the `print()` calls they replace, and
nothing in this codebase writes a log file or configures rotation. Retention
is therefore entirely up to whoever runs the process: if output is ever
redirected to a file or a hosting platform's log aggregator, that operator
should apply their own retention window. Because every log line here is
metadata-only, the retention risk is inherently low — there is no PII or
health content in the log stream to retain in the first place. If persistent
log files are wanted later, `logging.handlers.RotatingFileHandler` (stdlib,
no new dependency) is the natural addition — deliberately not included in
this phase.

## Log level

`LOG_LEVEL` (env var, default `INFO`) controls verbosity via
`logging.basicConfig(level=...)` in `app.py`. Raising or lowering it changes
*how much metadata* is emitted; it never changes *what kind* of content is
eligible to be logged — raw request content and exception text are excluded
at every level, not just at `INFO`.

## Request ID architecture

Previously, `response_model._build_meta()` generated a fresh UUID only when
building the final response, at the very end of request handling — nothing
earlier in the pipeline (including the old `print()` calls) had access to it,
so a log line could never be correlated with the response the client saw.

Now, `webhook.py` generates exactly one `request_id`
(`response_model.new_request_id()`) at the very top of the `webhook()` view,
before anything else runs, and threads it through the whole call chain for
that request:

```
webhook()                                  generates request_id once
    -> handle_webhook_request(payload, request_id)
        -> _handle_general_faq(parameters, request_id)
            -> assistant_service.answer(message, request_id)
    -> response_model.success_response(messages, intent, request_id)
       response_model.error_response(message, request_id=request_id)
```

`response_model._build_meta()` uses the passed-in `request_id` if given, and
only falls back to generating its own when none was supplied — so every
existing caller/test that builds a response without a `request_id` keeps
working exactly as before. The result: every log line for a request carries
the exact same id as that request's `meta.requestId`, so a failure seen in an
API response can be matched to its server-side log line without ever needing
to log content.

## Backward compatibility

Every function that gained a `request_id` parameter
(`response_model.success_response`, `response_model.error_response`,
`chatbot_logic.handle_webhook_request`, `chatbot_logic._handle_general_faq`,
`assistant_service.answer`) defaults it to `None`. Existing callers and tests
that don't pass one behave exactly as before this phase.
