import { detectIntent, INTERRUPTION_INTENTS } from './intent';

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
