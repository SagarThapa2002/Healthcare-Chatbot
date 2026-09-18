// Normalizes whatever the backend actually sent into one stable envelope
// shape the rest of the frontend can rely on:
//
//   { success, error, messages: [{ type, content, suggestions }], context, meta }
//
// Handles three cases:
//   1. The Phase 4 structured contract - passed through with defensive
//      defaults for any optional field a given backend response omits.
//   2. The legacy { fulfillmentText } shape - synthesized into a single
//      text message, so the backend can be migrated incrementally.
//   3. Anything else (missing/malformed JSON, a thrown network error) -
//      a safe fallback envelope, so the UI never receives undefined where
//      it expects an array.
//
// An unknown message `type` is passed through as-is rather than dropped;
// it's up to the renderer to fall back gracefully for a type it doesn't
// recognize (see MessageBubble.js).

const SCHEMA_VERSION = '1.0';
const FALLBACK_ERROR_TEXT = 'Sorry, an error occurred.';

function normalizeMessage(rawMessage) {
  if (!rawMessage || typeof rawMessage !== 'object') {
    return { type: 'text', content: { text: FALLBACK_ERROR_TEXT }, suggestions: [] };
  }
  const type = typeof rawMessage.type === 'string' ? rawMessage.type : 'text';
  const content = rawMessage.content && typeof rawMessage.content === 'object' ? rawMessage.content : {};
  const suggestions = Array.isArray(rawMessage.suggestions) ? rawMessage.suggestions : [];
  return { type, content, suggestions };
}

function fallbackEnvelope(text) {
  return {
    success: false,
    error: { code: 'CLIENT_ERROR', message: text },
    messages: [{ type: 'text', content: { text }, suggestions: [] }],
    context: null,
    meta: { schemaVersion: SCHEMA_VERSION, requestId: null, timestamp: null },
  };
}

function normalizeResponse(raw) {
  if (!raw || typeof raw !== 'object') {
    return fallbackEnvelope(FALLBACK_ERROR_TEXT);
  }

  // Case 1: already the structured Phase 4 contract.
  if (Array.isArray(raw.messages)) {
    return {
      success: raw.success !== false,
      error: raw.error ?? null,
      messages: raw.messages.map(normalizeMessage),
      context: raw.context ?? null,
      meta: {
        schemaVersion: raw.meta?.schemaVersion ?? SCHEMA_VERSION,
        requestId: raw.meta?.requestId ?? null,
        timestamp: raw.meta?.timestamp ?? null,
      },
    };
  }

  // Case 2: legacy shape, temporarily supported during migration.
  if (typeof raw.fulfillmentText === 'string') {
    return {
      success: true,
      error: null,
      messages: [{ type: 'text', content: { text: raw.fulfillmentText }, suggestions: [] }],
      context: null,
      meta: { schemaVersion: SCHEMA_VERSION, requestId: null, timestamp: null },
    };
  }

  // Case 3: unrecognized shape entirely.
  return fallbackEnvelope(FALLBACK_ERROR_TEXT);
}

export { normalizeResponse, FALLBACK_ERROR_TEXT };
