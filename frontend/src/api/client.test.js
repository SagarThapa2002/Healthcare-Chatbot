import { getProviders, resolveApiBaseUrl } from './client';

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
    expect(global.fetch).toHaveBeenCalledWith('http://127.0.0.1:5000/webhook/providers');
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
    });
  });

  test('getAppointments requests /webhook/appointments', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });

    await client.getAppointments();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(`${expectedBase}/webhook/appointments`);
  });

  test('getProviders requests /webhook/providers', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve([]) });

    await client.getProviders();

    expect(global.fetch).toHaveBeenCalledTimes(1);
    expect(global.fetch).toHaveBeenCalledWith(`${expectedBase}/webhook/providers`);
  });
});

test('loading the client with an override does not leak the variable into later tests', () => {
  const before = process.env.REACT_APP_API_BASE_URL;
  loadClientWith('https://api.example.com');
  expect(process.env.REACT_APP_API_BASE_URL).toBe(before);
});
