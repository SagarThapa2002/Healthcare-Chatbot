import { parseDate, parseTime, makeIsoDate } from './dateTime';

describe('makeIsoDate', () => {
  test('formats a valid date', () => {
    expect(makeIsoDate(2026, 12, 26)).toBe('2026-12-26');
  });

  test('rejects a calendar-invalid date', () => {
    expect(makeIsoDate(2026, 4, 31)).toBeNull();
  });
});

describe('parseDate', () => {
  test('parses ISO format (YYYY-MM-DD)', () => {
    expect(parseDate('2026-12-26')).toBe('2026-12-26');
  });

  test('parses DD-MM-YYYY', () => {
    expect(parseDate('26-12-2026')).toBe('2026-12-26');
  });

  test('parses DD/MM/YYYY', () => {
    expect(parseDate('26/12/2026')).toBe('2026-12-26');
  });

  test('parses "26th December 2026" with ordinal suffix', () => {
    expect(parseDate('26th December 2026')).toBe('2026-12-26');
  });

  test('finds a date within a longer sentence', () => {
    expect(parseDate('book appointment for Sagar on 26 December 2026 at 10am')).toBe('2026-12-26');
  });

  test('returns null for unparseable text', () => {
    expect(parseDate('whenever works for you')).toBeNull();
  });
});

describe('parseTime', () => {
  test('parses 24-hour time', () => {
    expect(parseTime('10:30')).toBe('10:30');
  });

  test('parses 12-hour time with am/pm', () => {
    expect(parseTime('10:30am')).toBe('10:30');
    expect(parseTime('2pm')).toBe('14:00');
    expect(parseTime('12am')).toBe('00:00');
    expect(parseTime('12pm')).toBe('12:00');
  });

  test('returns null for an invalid 24-hour value', () => {
    expect(parseTime('25:00')).toBeNull();
  });

  test('returns null for unparseable text', () => {
    expect(parseTime('not a time')).toBeNull();
  });
});
