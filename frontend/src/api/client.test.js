import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { webcrypto } from 'crypto';
import { getProviders, resolveApiBaseUrl } from './client';
import Chatbot from '../components/Chatbot';

// fetch is mocked entirely - these tests never touch the network and
// don't need a real backend running.
describe('getProviders', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    delete global.fetch;
  });

  test('requests GET /webhook/providers and returns the raw provider array', async () => {
    const providers = [
      { id: 'dr-patel', name: 'Dr. Patel', specialty: 'General Practice', location: 'Main Clinic' },
    ];
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(providers) });

    await expect(getProviders()).resolves.toEqual(providers);
    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith('http://127.0.0.1:5000/webhook/providers', { signal: expect.any(AbortSignal) });
  });

  test('throws on a non-OK response rather than returning an error body', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500, json: jest.fn() });

    await expect(getProviders()).rejects.toThrow('Failed to load providers (status 500)');
  });
});

describe('resolveApiBaseUrl', () => {
  test('falls back to the local backend when unset', () => {
    expect(resolveApiBaseUrl(undefined)).toBe('http://127.0.0.1:5000');
  });

  test('falls back to the local backend for an empty string', () => {
    expect(resolveApiBaseUrl('')).toBe('http://127.0.0.1:5000');
  });

  test('falls back to the local backend for a whitespace-only value', () => {
    expect(resolveApiBaseUrl('   ')).toBe('http://127.0.0.1:5000');
  });

  test('trims surrounding whitespace', () => {
    expect(resolveApiBaseUrl('  https://api.example.com  ')).toBe('https://api.example.com');
  });

  test('removes one trailing slash', () => {
    expect(resolveApiBaseUrl('https://api.example.com/')).toBe('https://api.example.com');
  });

  test('removes multiple trailing slashes', () => {
    expect(resolveApiBaseUrl('https://api.example.com///')).toBe('https://api.example.com');
  });

  test('leaves a normal production URL unchanged', () => {
    expect(resolveApiBaseUrl('https://api.example.com')).toBe('https://api.example.com');
  });
});

// API_BASE_URL is read once, when client.js is first loaded - so each test
// loads a fresh copy of the module with REACT_APP_API_BASE_URL set (or
// unset) exactly as it would be at build time. The original value is
// always restored, so nothing leaks into other tests.
function loadClientWith(baseUrl) {
  const original = process.env.REACT_APP_API_BASE_URL;
  if (baseUrl === undefined) {
    delete process.env.REACT_APP_API_BASE_URL;
  } else {
    process.env.REACT_APP_API_BASE_URL = baseUrl;
  }
  try {
    let client;
    jest.isolateModules(() => {
      client = require('./client');
    });
    return client;
  } finally {
    if (original === undefined) {
      delete process.env.REACT_APP_API_BASE_URL;
    } else {
      process.env.REACT_APP_API_BASE_URL = original;
    }
  }
}

describe.each([
  ['no REACT_APP_API_BASE_URL (default)', undefined, 'http://127.0.0.1:5000'],
  ['REACT_APP_API_BASE_URL=https://api.example.com', 'https://api.example.com', 'https://api.example.com'],
  ['REACT_APP_API_BASE_URL with whitespace and trailing slashes', '  https://api.example.com///  ', 'https://api.example.com'],
])('API requests with %s', (_label, configured, expectedBase) => {
  let client;

  beforeEach(() => {
    global.fetch = jest.fn();
    client = loadClientWith(configured);
  });

  afterEach(() => {
    delete global.fetch;
  });

  test('callBackend POSTs the unchanged payload to /webhook/webhook', async () => {
    global.fetch.mockResolvedValue({ json: () => Promise.resolve({ fulfillmentText: 'ok' }) });

    await client.callBackend('Book Appointment', { name: 'Sagar' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(`${expectedBase}/webhook/webhook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        queryResult: { intent: { displayName: 'Book Appointment' }, parameters: { name: 'Sagar' } },
      }),
      signal: expect.any(AbortSignal),
    });
  });

  test('getAppointments requests /webhook/appointments', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });

    await client.getAppointments();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(`${expectedBase}/webhook/appointments`, { signal: expect.any(AbortSignal) });
  });

  test('getProviders requests /webhook/providers', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });

    await client.getProviders();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(`${expectedBase}/webhook/providers`, { signal: expect.any(AbortSignal) });
  });
});

test('loading the client with an override does not leak the variable into later tests', () => {
  const before = process.env.REACT_APP_API_BASE_URL;
  loadClientWith('https://api.example.com');
  expect(process.env.REACT_APP_API_BASE_URL).toBe(before);
});

// --- conversation session -------------------------------------------------
//
// The Jest environment (jsdom) has no `crypto`, so each test installs exactly
// the crypto API it needs and removes it afterwards. The client holds the
// current session in module state, so each test loads a fresh copy.

const SESSION_1 = 'd1571ac7-5e55-4a1d-9c1e-000000000001';
const SESSION_2 = 'd1571ac7-5e55-4a1d-9c1e-000000000002';
const V4_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

function installCrypto(api) {
  Object.defineProperty(globalThis, 'crypto', { value: api, configurable: true, writable: true });
}

function removeCrypto() {
  delete globalThis.crypto;
}

function freshClient() {
  let client;
  jest.isolateModules(() => {
    client = require('./client');
  });
  return client;
}

function sentBodies() {
  return global.fetch.mock.calls.map(([, options]) => JSON.parse(options.body));
}

describe('conversation session on webhook requests', () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({ json: () => Promise.resolve({ fulfillmentText: 'ok' }) });
  });

  afterEach(() => {
    delete global.fetch;
    removeCrypto();
  });

  test('crypto.randomUUID() provides the session, sent top-level next to an unchanged queryResult', async () => {
    installCrypto({ randomUUID: jest.fn(() => SESSION_1) });
    const client = freshClient();
    client.startConversation();

    await client.callBackend('Book Appointment', { name: 'Sagar' });

    const [, options] = global.fetch.mock.calls[0];
    expect(options.body).toBe(JSON.stringify({
      session: SESSION_1,
      queryResult: { intent: { displayName: 'Book Appointment' }, parameters: { name: 'Sagar' } },
    }));
    const body = JSON.parse(options.body);
    expect(body.queryResult).toEqual({ intent: { displayName: 'Book Appointment' }, parameters: { name: 'Sagar' } });
    expect(body.queryResult).not.toHaveProperty('session');
  });

  test('every request in one conversation reuses the same session, generated once', async () => {
    const randomUUID = jest.fn(() => SESSION_1);
    installCrypto({ randomUUID });
    const client = freshClient();
    client.startConversation();

    await client.callBackend('Book Appointment', {});
    await client.callBackend('YesIntent', {});
    await client.callBackend('View Appointments', {});

    expect(sentBodies().map((b) => b.session)).toEqual([SESSION_1, SESSION_1, SESSION_1]);
    expect(randomUUID).toHaveBeenCalledTimes(1);
  });

  test('starting a new conversation gives a new session', async () => {
    installCrypto({ randomUUID: jest.fn().mockReturnValueOnce(SESSION_1).mockReturnValueOnce(SESSION_2) });
    const client = freshClient();

    client.startConversation();
    await client.callBackend('Book Appointment', {});
    client.startConversation();
    await client.callBackend('Book Appointment', {});

    expect(sentBodies().map((b) => b.session)).toEqual([SESSION_1, SESSION_2]);
  });

  test('without randomUUID, getRandomValues() produces a valid v4 UUID', async () => {
    installCrypto({ getRandomValues: (array) => webcrypto.getRandomValues(array) });
    const client = freshClient();
    client.startConversation();

    await client.callBackend('Book Appointment', {});

    expect(sentBodies()[0].session).toMatch(V4_UUID);
  });

  test('the getRandomValues() fallback sets the v4 version and RFC 4122 variant bits', async () => {
    installCrypto({ getRandomValues: (array) => array.fill(0xff) });
    const client = freshClient();
    client.startConversation();

    await client.callBackend('Book Appointment', {});

    expect(sentBodies()[0].session).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff');
  });

  test('with no usable crypto, no session field is sent', async () => {
    removeCrypto();
    const client = freshClient();
    client.startConversation();

    await client.callBackend('Book Appointment', { name: 'Sagar' });

    expect(global.fetch.mock.calls[0][1].body).toBe(JSON.stringify({
      queryResult: { intent: { displayName: 'Book Appointment' }, parameters: { name: 'Sagar' } },
    }));
  });

  test('before any conversation starts, no session field is sent', async () => {
    installCrypto({ randomUUID: jest.fn(() => SESSION_1) });
    const client = freshClient();

    await client.callBackend('Book Appointment', {});

    expect(sentBodies()[0]).not.toHaveProperty('session');
  });

  test('response and error handling are unchanged when a session is sent', async () => {
    installCrypto({ randomUUID: jest.fn(() => SESSION_1) });
    const client = freshClient();
    client.startConversation();

    global.fetch.mockResolvedValueOnce({ json: () => Promise.resolve({ fulfillmentText: 'hello' }) });
    const legacy = await client.callBackend('General FAQ', {});
    expect(legacy.messages[0].content.text).toBe('hello');

    global.fetch.mockResolvedValueOnce({ json: () => Promise.resolve(null) });
    const malformed = await client.callBackend('General FAQ', {});
    expect(malformed.success).toBe(false);
    expect(malformed.error.code).toBe('CLIENT_ERROR');
  });
});

// The real Chatbot (real useConversation + real client, only fetch mocked):
// one mount is one conversation, across a full booking, cancellation and
// update, and the session never reaches the page.
describe('conversation session across a mounted Chatbot', () => {
  const APPOINTMENT_ID = '11111111-1111-4111-8111-111111111111';

  function envelope(text, context = {}) {
    return {
      success: true,
      error: null,
      messages: [{ type: 'text', content: { text }, suggestions: [] }],
      context: { intent: 'x', ...context },
      meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
    };
  }

  async function say(value) {
    await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
    fireEvent.change(screen.getByRole('textbox'), { target: { value } });
    fireEvent.submit(screen.getByRole('textbox').closest('form'));
    await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
  }

  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    delete global.fetch;
    removeCrypto();
  });

  test('one session per mount, kept through booking, cancellation and update, never rendered', async () => {
    const randomUUID = jest.fn().mockReturnValueOnce(SESSION_1).mockReturnValueOnce(SESSION_2);
    installCrypto({ randomUUID });
    const script = [
      envelope('May I have your name?', { bookingStage: 'name' }),
      envelope('Which provider?', { bookingStage: 'provider' }),
      envelope('What date?', { bookingStage: 'date' }),
      envelope('Available times', { bookingStage: 'slot' }),
      envelope('Please confirm (yes or no)', { bookingStage: 'confirm' }),
      envelope('Your appointment has been booked.', { bookingStage: 'booked' }),
      envelope('What is the ID or name?', { cancellationStage: 'identifier' }),
      envelope('Please confirm the cancellation (yes or no)', { cancellationStage: 'confirm' }),
      envelope('Your appointment has been cancelled.', { cancellationStage: 'cancelled' }),
      envelope('What is the ID or name?', { updateStage: 'identifier' }),
      envelope('What new date or time?', { updateStage: 'fields' }),
      envelope('Please confirm the update (yes or no)', { updateStage: 'confirm' }),
      envelope('Your appointment has been updated.', { updateStage: 'updated' }),
      envelope('Here are your appointments.'),
    ];
    script.forEach((reply) => global.fetch.mockResolvedValueOnce({ json: () => Promise.resolve(reply) }));

    const { unmount } = render(<Chatbot />);
    expect(randomUUID).toHaveBeenCalledTimes(1);

    for (const message of [
      'book an appointment', 'Sagar', 'dr-patel', '2026-12-28', '10:00', 'yes',
      'cancel my appointment', APPOINTMENT_ID, 'yes',
      'update my appointment', APPOINTMENT_ID, '2026-12-30', 'yes',
      'show my appointments',
    ]) {
      await say(message);
    }

    const bodies = sentBodies();
    expect(bodies).toHaveLength(script.length);
    expect(new Set(bodies.map((b) => b.session))).toEqual(new Set([SESSION_1]));
    expect(randomUUID).toHaveBeenCalledTimes(1);
    expect(document.body.innerHTML).not.toContain(SESSION_1);

    // A new mount is a new conversation.
    unmount();
    global.fetch.mockResolvedValueOnce({ json: () => Promise.resolve(envelope('May I have your name?', { bookingStage: 'name' })) });
    render(<Chatbot />);
    await say('book an appointment');
    expect(randomUUID).toHaveBeenCalledTimes(2);
    expect(sentBodies().at(-1).session).toBe(SESSION_2);
    expect(document.body.innerHTML).not.toContain(SESSION_2);
  });
});

// --- request timeout ------------------------------------------------------
//
// Every request is aborted after 35 s. These tests use fake timers (never a
// real 35 s wait) and a fetch stand-in that honours its AbortSignal the way
// the real fetch does: an aborted request rejects with an AbortError.

const TIMEOUT_MS = 35 * 1000;

function abortError() {
  return new DOMException('The operation was aborted.', 'AbortError');
}

// A fetch that never responds until its signal aborts it.
function hangingFetch() {
  return jest.fn((url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(abortError()));
  }));
}

function trackSettled(promise) {
  const state = { settled: false };
  promise.then(() => { state.settled = true; }, () => { state.settled = true; });
  return state;
}

async function flushPromises() {
  for (let i = 0; i < 5; i += 1) {
    // eslint-disable-next-line no-await-in-loop
    await Promise.resolve();
  }
}

describe('request timeout', () => {
  let client;

  beforeEach(() => {
    jest.useFakeTimers();
    client = freshClient();
  });

  afterEach(() => {
    jest.useRealTimers();
    delete global.fetch;
  });

  test('callBackend is aborted after 35 s when fetch never settles, and not before', async () => {
    global.fetch = hangingFetch();
    const request = client.callBackend('Book Appointment', {});
    const state = trackSettled(request);

    jest.advanceTimersByTime(TIMEOUT_MS - 1);
    await flushPromises();
    expect(state.settled).toBe(false);

    jest.advanceTimersByTime(1);
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    const { signal } = global.fetch.mock.calls[0][1];
    expect(signal).toBeInstanceOf(AbortSignal);
    expect(signal.aborted).toBe(true);
    expect(jest.getTimerCount()).toBe(0);
  });

  test('a response whose body never arrives is also aborted after 35 s', async () => {
    global.fetch = jest.fn((url, { signal }) => Promise.resolve({
      ok: true,
      json: () => new Promise((resolve, reject) => {
        if (signal.aborted) reject(abortError()); // as the real fetch does for an already-aborted signal
        signal.addEventListener('abort', () => reject(abortError()));
      }),
    }));
    const request = client.callBackend('Book Appointment', {});
    const state = trackSettled(request);
    await flushPromises(); // headers have arrived; the body read is now stalled

    jest.advanceTimersByTime(TIMEOUT_MS - 1);
    await flushPromises();
    expect(state.settled).toBe(false);

    jest.advanceTimersByTime(1);
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(jest.getTimerCount()).toBe(0);
  });

  test('the timer is cleared after a successful request', async () => {
    global.fetch = jest.fn().mockResolvedValue({ json: () => Promise.resolve({ fulfillmentText: 'ok' }) });

    const envelope = await client.callBackend('Book Appointment', {});

    expect(envelope.messages[0].content.text).toBe('ok');
    expect(jest.getTimerCount()).toBe(0);
    expect(global.fetch.mock.calls[0][1].signal.aborted).toBe(false);
  });

  test('the timer is cleared after a rejected request, and the original error propagates', async () => {
    global.fetch = jest.fn().mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(client.callBackend('Book Appointment', {})).rejects.toThrow('Failed to fetch');
    expect(jest.getTimerCount()).toBe(0);
  });

  test('the timer is cleared after a non-OK response, which still throws the existing error', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500, json: jest.fn() });

    await expect(client.getAppointments()).rejects.toThrow('Failed to load appointments (status 500)');
    await expect(client.getProviders()).rejects.toThrow('Failed to load providers (status 500)');
    expect(jest.getTimerCount()).toBe(0);
  });

  test.each([
    ['getAppointments', '/webhook/appointments'],
    ['getProviders', '/webhook/providers'],
  ])('%s is aborted after 35 s the same way', async (fn, path) => {
    global.fetch = hangingFetch();
    const request = client[fn]();

    jest.advanceTimersByTime(TIMEOUT_MS);
    await expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(global.fetch).toHaveBeenCalledWith(`http://127.0.0.1:5000${path}`, { signal: expect.any(AbortSignal) });
    expect(jest.getTimerCount()).toBe(0);
  });

  test('the session payload is unchanged by the timeout', async () => {
    installCrypto({ randomUUID: jest.fn(() => SESSION_1) });
    client = freshClient();
    client.startConversation();
    global.fetch = jest.fn().mockResolvedValue({ json: () => Promise.resolve({ fulfillmentText: 'ok' }) });

    await client.callBackend('Book Appointment', { name: 'Sagar' });

    const [url, options] = global.fetch.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:5000/webhook/webhook');
    expect(options).toEqual({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session: SESSION_1,
        queryResult: { intent: { displayName: 'Book Appointment' }, parameters: { name: 'Sagar' } },
      }),
      signal: expect.any(AbortSignal),
    });
    removeCrypto();
  });
});

// A timeout at the booking confirmation goes through the hook's existing
// error handling and does not clear the local booking: afterwards the
// booking is still at CONFIRM, as shown by an interruption sending NoIntent
// first (which only happens at CONFIRM).
describe('request timeout during a booking confirmation (rendered Chatbot)', () => {
  function envelope(text, context = {}) {
    return {
      success: true,
      error: null,
      messages: [{ type: 'text', content: { text }, suggestions: [] }],
      context: { intent: 'x', ...context },
      meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
    };
  }

  function reply(body) {
    return Promise.resolve({ json: () => Promise.resolve(body) });
  }

  async function say(value) {
    await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
    fireEvent.change(screen.getByRole('textbox'), { target: { value } });
    fireEvent.submit(screen.getByRole('textbox').closest('form'));
    await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
  }

  function intents() {
    return sentBodies().map((body) => body.queryResult.intent.displayName);
  }

  afterEach(() => {
    jest.useRealTimers();
    delete global.fetch;
  });

  test('a timed-out "yes" shows the timeout alert, re-enables input and keeps the booking at CONFIRM', async () => {
    global.fetch = jest.fn()
      .mockReturnValueOnce(reply(envelope('May I have your name?', { bookingStage: 'name' })))
      .mockReturnValueOnce(reply(envelope('Which provider?', { bookingStage: 'provider' })))
      .mockReturnValueOnce(reply(envelope('What date?', { bookingStage: 'date' })))
      .mockReturnValueOnce(reply(envelope('Available times', { bookingStage: 'slot' })))
      .mockReturnValueOnce(reply(envelope('Please confirm (yes or no)', { bookingStage: 'confirm' })));
    render(<Chatbot />);
    for (const message of ['book an appointment', 'Sagar', 'dr-patel', '2026-12-28', '10:00']) {
      await say(message);
    }

    // "yes" hangs until the 35 s timeout aborts it.
    jest.useFakeTimers();
    global.fetch.mockImplementationOnce((url, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(abortError()));
    }));
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    const input = screen.getByRole('textbox');
    fireEvent.change(input, { target: { value: 'yes' } });
    fireEvent.submit(input.closest('form'));
    await act(async () => {
      await flushPromises();
    });
    expect(input).toBeDisabled();

    await act(async () => {
      jest.advanceTimersByTime(TIMEOUT_MS);
      await flushPromises();
    });
    errorSpy.mockRestore();
    jest.useRealTimers();

    expect(intents().at(-1)).toBe('YesIntent');
    expect(input).not.toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('The server took too long to respond. Please try again.');
    expect(screen.queryByText('Sorry, an error occurred.')).not.toBeInTheDocument();

    // The booking was not cleared: interrupting now still discards the
    // backend pending booking first, which only happens at CONFIRM.
    global.fetch
      .mockReturnValueOnce(reply(envelope('discarded')))
      .mockReturnValueOnce(reply(envelope('Here are your appointments.')));
    await say('view my appointments');
    expect(intents().slice(-2)).toEqual(['NoIntent', 'View Appointments']);
  });
});
