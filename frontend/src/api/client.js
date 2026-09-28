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

async function callBackend(intent, parameters) {
  const response = await fetch(`${API_BASE_URL}/webhook/webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queryResult: { intent: { displayName: intent }, parameters } }),
  });
  const data = await response.json();
  return normalizeResponse(data);
}

// GET /webhook/appointments returns the raw appointment array as-is (see
// backend/webhook.py's get_appointments()) - no envelope, so unlike
// callBackend above this never goes through normalizeResponse. Throws on
// a non-OK response so callers can distinguish "request failed" from "no
// appointments" (an empty array is a valid, successful response).
async function getAppointments() {
  const response = await fetch(`${API_BASE_URL}/webhook/appointments`);
  if (!response.ok) {
    throw new Error(`Failed to load appointments (status ${response.status})`);
  }
  return response.json();
}

// GET /webhook/providers returns the raw provider array as-is (see
// backend/webhook.py's get_providers() and docs/openapi.yaml) - no
// envelope, same as getAppointments above, and throws on a non-OK
// response the same way.
async function getProviders() {
  const response = await fetch(`${API_BASE_URL}/webhook/providers`);
  if (!response.ok) {
    throw new Error(`Failed to load providers (status ${response.status})`);
  }
  return response.json();
}

export { callBackend, getAppointments, getProviders, resolveApiBaseUrl };
