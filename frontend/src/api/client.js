import { normalizeResponse } from './normalizeResponse';

async function callBackend(intent, parameters) {
  const response = await fetch('http://127.0.0.1:5000/webhook/webhook', {
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
  const response = await fetch('http://127.0.0.1:5000/webhook/appointments');
  if (!response.ok) {
    throw new Error(`Failed to load appointments (status ${response.status})`);
  }
  return response.json();
}

export { callBackend, getAppointments };
