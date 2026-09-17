import {
  EMPTY_BOOKING,
  bookingStage,
  bookingParams,
  extractInitialBookingFields,
} from './booking';

describe('bookingStage', () => {
  test('returns null when no booking is active', () => {
    expect(bookingStage(EMPTY_BOOKING)).toBeNull();
  });

  test('progresses through name -> date -> time -> confirm', () => {
    expect(bookingStage({ active: true, name: null, date: null, time: null })).toBe('name');
    expect(bookingStage({ active: true, name: 'Sagar', date: null, time: null })).toBe('date');
    expect(bookingStage({ active: true, name: 'Sagar', date: '2026-12-26', time: null })).toBe('time');
    expect(bookingStage({ active: true, name: 'Sagar', date: '2026-12-26', time: '10:00' })).toBe('confirm');
  });
});

describe('bookingParams', () => {
  test('only includes fields that are populated', () => {
    expect(bookingParams({ name: 'Sagar', date: null, time: null })).toEqual({ name: 'Sagar' });
  });

  test('includes all fields once populated', () => {
    expect(bookingParams({ name: 'Sagar', date: '2026-12-26', time: '10:00' })).toEqual({
      name: 'Sagar', date: '2026-12-26', time: '10:00',
    });
  });
});

describe('extractInitialBookingFields', () => {
  test('extracts name, date, and time from a single sentence', () => {
    const fields = extractInitialBookingFields('book appointment for Sagar on 26 December 2026 at 10am');
    expect(fields).toEqual({ name: 'Sagar', date: '2026-12-26', time: '10:00' });
  });

  test('returns an empty object when nothing matches', () => {
    expect(extractInitialBookingFields('book an appointment')).toEqual({});
  });

  test('does not extract a lowercase word as a name', () => {
    expect(extractInitialBookingFields('book an appointment for tomorrow')).toEqual({});
  });
});
