import { getProviders } from './client';

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
