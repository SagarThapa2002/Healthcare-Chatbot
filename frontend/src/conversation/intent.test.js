import { detectIntent, classifyIntent, CONFIDENCE, INTERRUPTION_INTENTS } from './intent';

describe('detectIntent', () => {
  test('detects yes/no', () => {
    expect(detectIntent('yes')).toBe('YesIntent');
    expect(detectIntent('no')).toBe('NoIntent');
  });

  test('detects booking keyword', () => {
    expect(detectIntent('I want to book an appointment')).toBe('Book Appointment');
  });

  test('detects cancel/update/view keywords', () => {
    expect(detectIntent('cancel my appointment')).toBe('Cancel Appointment');
    expect(detectIntent('update my appointment')).toBe('Update Appointment');
    expect(detectIntent('view my appointments')).toBe('View Appointments');
  });

  test('detects symptom keywords', () => {
    expect(detectIntent('I have a headache')).toBe('Symptom Check');
    expect(detectIntent('feeling dizzy')).toBe('Symptom Check');
  });

  test('falls back to General FAQ', () => {
    expect(detectIntent('hello there')).toBe('General FAQ');
  });

  test('exposes interruption intents', () => {
    expect(INTERRUPTION_INTENTS).toEqual([
      'Symptom Check', 'Cancel Appointment', 'View Appointments', 'Update Appointment',
    ]);
  });
});

describe('classifyIntent', () => {
  test('returns the {intent, confidence, reason} shape', () => {
    const result = classifyIntent('yes');
    expect(Object.keys(result).sort()).toEqual(['confidence', 'intent', 'reason']);
    expect(typeof result.intent).toBe('string');
    expect(typeof result.confidence).toBe('string');
    expect(typeof result.reason).toBe('string');
  });

  test('CONFIDENCE is a closed set of exactly high/medium/low/none', () => {
    expect(Object.values(CONFIDENCE).sort()).toEqual(['high', 'low', 'medium', 'none']);
  });

  describe('high confidence: exact full-message matches', () => {
    test('"yes" is an exact match', () => {
      expect(classifyIntent('yes')).toEqual({
        intent: 'YesIntent',
        confidence: CONFIDENCE.HIGH,
        reason: 'exact match: "yes"',
      });
    });

    test('"no" is an exact match', () => {
      expect(classifyIntent('no')).toEqual({
        intent: 'NoIntent',
        confidence: CONFIDENCE.HIGH,
        reason: 'exact match: "no"',
      });
    });

    test('is case/whitespace insensitive, still exact', () => {
      const result = classifyIntent('  YES  ');
      expect(result.intent).toBe('YesIntent');
      expect(result.confidence).toBe(CONFIDENCE.HIGH);
    });

    test('"yes please" is not an exact match and falls through to no match', () => {
      // Documents an existing gap: only the literal word "yes" is
      // recognized, at high confidence. A natural variation like "yes
      // please" does not match any rule and falls all the way to the
      // General FAQ fallback.
      const result = classifyIntent('yes please');
      expect(result.intent).toBe('General FAQ');
      expect(result.confidence).toBe(CONFIDENCE.NONE);
    });
  });

  describe('medium confidence: word-boundary keyword matches', () => {
    test.each([
      ['I have a headache', 'headache'],
      ['feeling dizzy', 'dizzy'],
      ['I have a fever', 'fever'],
    ])('"%s" -> Symptom Check at medium confidence (matched "%s")', (message, keyword) => {
      const result = classifyIntent(message);
      expect(result.intent).toBe('Symptom Check');
      expect(result.confidence).toBe(CONFIDENCE.MEDIUM);
      expect(result.reason).toContain(keyword);
    });
  });

  describe('low confidence: unanchored substring matches', () => {
    test.each([
      ['I want to book an appointment', 'Book Appointment', 'book'],
      ['cancel my appointment', 'Cancel Appointment', 'cancel'],
      ['update my appointment', 'Update Appointment', 'update'],
      ['view my appointments', 'View Appointments', 'view'],
    ])('"%s" -> %s at low confidence', (message, expectedIntent, keyword) => {
      const result = classifyIntent(message);
      expect(result.intent).toBe(expectedIntent);
      expect(result.confidence).toBe(CONFIDENCE.LOW);
      expect(result.reason).toContain(keyword);
    });
  });

  describe('none confidence: no rule matched', () => {
    test('falls back to General FAQ', () => {
      expect(classifyIntent('hello there')).toEqual({
        intent: 'General FAQ',
        confidence: CONFIDENCE.NONE,
        reason: 'no rule matched - defaulted to General FAQ',
      });
    });
  });

  describe('known, pre-existing ambiguities (documented here, not fixed in this phase)', () => {
    test('substring false positive: "overview" contains "view"', () => {
      const result = classifyIntent('a quick overview of my recent visits');
      expect(result.intent).toBe('View Appointments');
      expect(result.confidence).toBe(CONFIDENCE.LOW);
    });

    test('substring false positive: "reupdate" contains "update"', () => {
      const result = classifyIntent('I want to reupdate my details');
      expect(result.intent).toBe('Update Appointment');
      expect(result.confidence).toBe(CONFIDENCE.LOW);
    });

    test('cancel/symptom collision: cancel is checked before the symptom pattern', () => {
      const result = classifyIntent('cancel my appointment because I have a fever');
      expect(result.intent).toBe('Cancel Appointment');
      expect(result.confidence).toBe(CONFIDENCE.LOW);
    });
  });

  describe('compatibility with detectIntent', () => {
    test.each([
      'yes',
      'no',
      'yes please',
      'I want to book an appointment',
      'cancel my appointment',
      'update my appointment',
      'view my appointments',
      'I have a headache',
      'feeling dizzy',
      'hello there',
      'a quick overview of my recent visits',
      'cancel my appointment because I have a fever',
    ])('detectIntent(%j) matches classifyIntent(...).intent', (message) => {
      expect(detectIntent(message)).toBe(classifyIntent(message).intent);
    });
  });
});
