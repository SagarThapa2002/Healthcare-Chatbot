import { normalizeResponse } from './normalizeResponse';

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:5000';

// Normalizes a configured API base URL: surrounding whitespace is trimmed
// and trailing slashes are removed (so a path is never joined as
// "//webhook"). An unset, empty, or whitespace-only value falls back to
// the local development backend.
function resolveApiBaseUrl(raw) {
  const trimmed = (raw ?? '').trim();
  if (!trimmed) return DEFAULT_API_BASE_URL;
  return trimmed.replace(/\/+$/, '');
}

// REACT_APP_API_BASE_URL is inlined by Create React App when `npm start` /
// `npm run build` runs - it is fixed at build time, never read at runtime,
// and ends up in the public JS bundle (so it must never hold a secret).
const API_BASE_URL = resolveApiBaseUrl(process.env.REACT_APP_API_BASE_URL);

// The current chat conversation's session id, set by startConversation()
// when a Chatbot conversation mounts. Sent as the top-level `session` of
// every webhook request so the backend keeps this conversation's pending
// booking/update/cancellation separate from other visitors'. It isolates
// conversations; it is not authentication. Never logged or displayed.
let conversationSession = null;

// A random RFC 4122 v4 UUID, in the exact 8-4-4-4-12 form the backend
// accepts. crypto.randomUUID() needs a secure context (HTTPS or localhost),
// so crypto.getRandomValues() - available everywhere - is the fallback.
// With no crypto at all this returns null and no session is sent, leaving
// the backend's legacy behaviour; Math.random() is never used because a
// guessable id would weaken the isolation.
function newSessionId() {
  const cryptoApi = typeof window !== 'undefined' ? window.crypto : undefined;
  if (cryptoApi && typeof cryptoApi.randomUUID === 'function') {
    return cryptoApi.randomUUID();
  }
  if (cryptoApi && typeof cryptoApi.getRandomValues === 'function') {
    const bytes = cryptoApi.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
    bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  return null;
}

// Starts a new conversation session. Called once per Chatbot mount (see
// useConversation), so the session lasts exactly as long as the chat's own
// conversation state. Chatbot stays mounted across tab switches (see
// AppShell), so in practice that is one session per page load.
function startConversation() {
  conversationSession = newSessionId();
}

// Owner token: one random id per browser, kept in localStorage so it
// survives reloads (unlike the per-page-load session above), and sent as
// the X-Owner-Token header on the chat and appointment requests. The
// backend stores it on newly booked appointments. It is plumbing for an
// ownership boundary that is NOT enforced yet, and it is not
// authentication: anyone holding the value can present it. If localStorage
// is unavailable (blocked, private mode), an in-memory token is used for
// this page load instead.
const OWNER_TOKEN_KEY = 'ownerToken';
const OWNER_TOKEN_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
let memoryOwnerToken = null;

function ownerToken() {
  try {
    const stored = window.localStorage.getItem(OWNER_TOKEN_KEY);
    if (stored && OWNER_TOKEN_PATTERN.test(stored)) return stored;
    const created = newSessionId();
    if (created) window.localStorage.setItem(OWNER_TOKEN_KEY, created);
    return created;
  } catch (err) {
    if (!memoryOwnerToken) memoryOwnerToken = newSessionId();
    return memoryOwnerToken;
  }
}

function ownerHeaders() {
  const token = ownerToken();
  return token ? { 'X-Owner-Token': token } : {};
}

// Longest a request may take, start to finish, before it is aborted - a
// few seconds above the backend's own 30 s limits (LLM call, Gunicorn
// worker), so a slow but legitimate answer is not cut off. Without it a
// stalled connection would leave the chat input disabled indefinitely.
const REQUEST_TIMEOUT_MS = 35 * 1000;

// fetch() with that timeout. The timer covers the whole request including
// reading the body (`read` runs before it is cleared, and the same signal
// aborts a body read in progress), and is always cleared once the request
// settles - resolved, rejected or aborted. A timeout surfaces as the
// rejection fetch raises on abort, through each caller's existing error
// handling; nothing else about the request changes.
async function fetchWithTimeout(url, options, read) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return await read(response);
  } finally {
    clearTimeout(timer);
  }
}

async function callBackend(intent, parameters) {
  const queryResult = { intent: { displayName: intent }, parameters };
  const payload = conversationSession ? { session: conversationSession, queryResult } : { queryResult };
  const data = await fetchWithTimeout(
    `${API_BASE_URL}/webhook/webhook`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...ownerHeaders() },
      body: JSON.stringify(payload),
    },
    (response) => response.json(),
  );
  return normalizeResponse(data);
}

// GET /webhook/appointments returns the raw appointment array as-is (see
// backend/webhook.py's get_appointments()) - no envelope, so unlike
// callBackend above this never goes through normalizeResponse. Throws on
// a non-OK response so callers can distinguish "request failed" from "no
// appointments" (an empty array is a valid, successful response).
async function getAppointments() {
  return fetchWithTimeout(`${API_BASE_URL}/webhook/appointments`, { headers: ownerHeaders() }, (response) => {
    if (!response.ok) {
      throw new Error(`Failed to load appointments (status ${response.status})`);
    }
    return response.json();
  });
}

// GET /webhook/providers returns the raw provider array as-is (see
// backend/webhook.py's get_providers() and docs/openapi.yaml) - no
// envelope, same as getAppointments above, and throws on a non-OK
// response the same way.
async function getProviders() {
  return fetchWithTimeout(`${API_BASE_URL}/webhook/providers`, {}, (response) => {
    if (!response.ok) {
      throw new Error(`Failed to load providers (status ${response.status})`);
    }
    return response.json();
  });
}

export { callBackend, getAppointments, getProviders, resolveApiBaseUrl, startConversation };
