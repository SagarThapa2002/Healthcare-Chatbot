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

export { callBackend };
