import {
  EMPTY_BOOKING,
  bookingStage,
  bookingParams,
  extractInitialBookingFields,
} from './booking';

describe('EMPTY_BOOKING', () => {
  test('is inactive with a null providerId alongside the other null fields', () => {
    expect(EMPTY_BOOKING).toEqual({ active: false, name: null, providerId: null, date: null, time: null });
  });
});

describe('bookingStage', () => {
  test('returns null when no booking is active', () => {
    expect(bookingStage(EMPTY_BOOKING)).toBeNull();
  });

  test('progresses through name -> provider -> date -> slot -> confirm', () => {
    expect(bookingStage({ active: true, name: null, providerId: null, date: null, time: null })).toBe('name');
    expect(bookingStage({ active: true, name: 'Sagar', providerId: null, date: null, time: null })).toBe('provider');
    expect(bookingStage({ active: true, name: 'Sagar', providerId: 'dr-patel', date: null, time: null })).toBe('date');
    expect(
      bookingStage({ active: true, name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: null })
    ).toBe('slot');
    expect(
      bookingStage({ active: true, name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00' })
    ).toBe('confirm');
  });
});

describe('bookingParams', () => {
  test('only includes fields that are populated', () => {
    expect(bookingParams({ name: 'Sagar', providerId: null, date: null, time: null })).toEqual({ name: 'Sagar' });
  });

  test('includes providerId once selected, independent of date/time', () => {
    expect(bookingParams({ name: 'Sagar', providerId: 'dr-patel', date: null, time: null })).toEqual({
      name: 'Sagar', providerId: 'dr-patel',
    });
  });

  test('includes all fields once populated', () => {
    expect(bookingParams({ name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00' })).toEqual({
      name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00',
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

  test('never extracts a providerId from free text, even when a provider name is mentioned', () => {
    const fields = extractInitialBookingFields(
      'book appointment for Sagar with Dr. Patel on 26 December 2026 at 10am'
    );
    expect(fields.providerId).toBeUndefined();
  });
});
