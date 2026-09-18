import { normalizeResponse } from './normalizeResponse';

describe('normalizeResponse', () => {
  test('passes through an already-structured response', () => {
    const raw = {
      success: true,
      error: null,
      messages: [{ type: 'text', content: { text: 'Hi' }, suggestions: [] }],
      context: { intent: 'General FAQ' },
      meta: { schemaVersion: '1.0', requestId: 'abc-123', timestamp: '2026-01-01T00:00:00+00:00' },
    };

    const result = normalizeResponse(raw);

    expect(result.success).toBe(true);
    expect(result.error).toBeNull();
    expect(result.messages).toEqual([{ type: 'text', content: { text: 'Hi' }, suggestions: [] }]);
    expect(result.context).toEqual({ intent: 'General FAQ' });
    expect(result.meta).toEqual({
      schemaVersion: '1.0',
      requestId: 'abc-123',
      timestamp: '2026-01-01T00:00:00+00:00',
    });
  });

  test('fills in defaults for a structured response missing optional fields', () => {
    const result = normalizeResponse({ messages: [{ type: 'text', content: { text: 'Hi' } }] });

    expect(result.success).toBe(true);
    expect(result.messages[0].suggestions).toEqual([]);
    expect(result.context).toBeNull();
    expect(result.meta.schemaVersion).toBe('1.0');
  });

  test('carries a genuine backend failure through as success: false', () => {
    const raw = {
      success: false,
      error: { code: 'INTERNAL_ERROR', message: 'Oops, something went wrong on the server.' },
      messages: [],
      context: null,
      meta: { schemaVersion: '1.0', requestId: 'x', timestamp: 'y' },
    };

    const result = normalizeResponse(raw);

    expect(result.success).toBe(false);
    expect(result.error.message).toBe('Oops, something went wrong on the server.');
    expect(result.messages).toEqual([]);
  });

  test('normalizes a legacy fulfillmentText response', () => {
    const result = normalizeResponse({ fulfillmentText: 'Hello there' });

    expect(result.success).toBe(true);
    expect(result.messages).toEqual([{ type: 'text', content: { text: 'Hello there' }, suggestions: [] }]);
  });

  test('normalizes an unknown message type without dropping or crashing', () => {
    const result = normalizeResponse({
      messages: [{ type: 'mystery_type', content: { text: 'Something new' } }],
    });

    expect(result.messages[0].type).toBe('mystery_type');
    expect(result.messages[0].content.text).toBe('Something new');
  });

  test.each([null, undefined, {}, 'a string', 42])(
    'falls back gracefully for a malformed/missing response: %p',
    (raw) => {
      const result = normalizeResponse(raw);
      expect(result.success).toBe(false);
      expect(Array.isArray(result.messages)).toBe(true);
      expect(result.messages).toHaveLength(1);
      expect(result.messages[0].type).toBe('text');
    }
  );
});
