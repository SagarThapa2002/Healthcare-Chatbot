import { act, renderHook } from '@testing-library/react';
import { useConversation } from './useConversation';
import { callBackend } from '../api/client';

// Only the payload construction is under test here - callBackend itself
// (network/normalization) is mocked entirely, so these tests never touch
// the network and don't need a real backend running.
jest.mock('../api/client', () => ({
  callBackend: jest.fn(),
}));

function fakeEnvelope() {
  return {
    success: true,
    error: null,
    messages: [{ type: 'text', content: { text: 'ok' }, suggestions: [] }],
    context: null,
    meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
  };
}

async function submitMessage(result, text) {
  act(() => {
    result.current.setUserInput(text);
  });
  await act(async () => {
    await result.current.sendMessage({ preventDefault: () => {} });
  });
}

describe('useConversation payload construction (frontend-to-backend wiring)', () => {
  beforeEach(() => {
    callBackend.mockReset();
    callBackend.mockResolvedValue(fakeEnvelope());
  });

  test('sends parameters.message for an unclassified General FAQ question', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'What is a balanced diet?');

    expect(callBackend).toHaveBeenCalledWith('General FAQ', { message: 'What is a balanced diet?' });
  });

  test('still sends the existing parameters.symptom shape for a symptom message', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'I have a headache');

    expect(callBackend).toHaveBeenCalledWith('Symptom Check', { symptom: 'I have a headache' });
  });

  test('Book Appointment payload is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'book an appointment');

    expect(callBackend).toHaveBeenCalledWith('Book Appointment', {});
  });

  test('Cancel Appointment payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'cancel my appointment');

    expect(callBackend).toHaveBeenCalledWith('Cancel Appointment', {});
  });

  test('Update Appointment payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'update my appointment');

    expect(callBackend).toHaveBeenCalledWith('Update Appointment', {});
  });

  test('View Appointments payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'view my appointments');

    expect(callBackend).toHaveBeenCalledWith('View Appointments', {});
  });

  test('a bare "yes" with no booking in progress is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'yes');

    expect(callBackend).toHaveBeenCalledWith('YesIntent', {});
  });

  test('a bare "no" with no booking in progress is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'no');

    expect(callBackend).toHaveBeenCalledWith('NoIntent', {});
  });
});

// Builds a fake backend text-message envelope with custom text and an
// optional `bookingStage`, matching backend/response_model.py's
// success_response(..., booking_stage=...) contract - lets these tests
// drive the multi-turn booking flow forward exactly like the real backend
// does (see backend/chatbot_logic.py's _handle_book_appointment), without
// needing a real backend running. `bookingStage` is omitted from
// `context` when not given, exactly like the real contract omits it for
// non-booking intents.
function envelopeWithText(text, bookingStage) {
  return {
    success: true,
    error: null,
    messages: [{ type: 'text', content: { text }, suggestions: [] }],
    context: { intent: 'Book Appointment', ...(bookingStage ? { bookingStage } : {}) },
    meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
  };
}

// Drives the flow up to (but not including) the provider reply - used by
// every test that needs to start at the 'provider' stage.
async function bookThroughToProviderStage(result) {
  callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
  await submitMessage(result, 'book an appointment');
  callBackend.mockResolvedValueOnce(
    envelopeWithText('Thanks Sagar. Which provider would you like to see?\n1. Dr. Patel...', 'provider')
  );
  await submitMessage(result, 'Sagar');
}

// Drives the flow up to (but not including) the slot reply - used by
// every test that needs to start at the 'slot' stage. Assumes a valid
// provider ('dr-patel') and date ('2026-12-28') are both accepted.
async function bookThroughToSlotStage(result) {
  await bookThroughToProviderStage(result);
  callBackend.mockResolvedValueOnce(
    envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
  );
  await submitMessage(result, 'dr-patel');
  callBackend.mockResolvedValueOnce(
    envelopeWithText('Here are the available times on 2026-12-28:\n1. 09:00\n2. 09:30', 'slot')
  );
  await submitMessage(result, '2026-12-28');
}

describe('provider-aware booking flow (Phase 6.1 Slice 3, Step 4)', () => {
  beforeEach(() => {
    callBackend.mockReset();
  });

  test('name -> provider transition: the reply after a valid name is sent as providerId', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar' });

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'Dr. Patel');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'Dr. Patel' });
  });

  test('provider -> date transition: providerId is preserved and sent alongside the date', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'dr-patel');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'dr-patel' });

    callBackend.mockResolvedValueOnce(
      envelopeWithText('Here are the available times on 2026-12-28:\n1. 09:00', 'slot')
    );
    await submitMessage(result, '2026-12-28');
    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28' }
    );
  });

  test('date -> slot transition: provider and date are preserved and sent alongside the slot choice', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText(
        'Please confirm — book appointment with Dr. Patel for Sagar on 2026-12-28 at 09:00? (yes or no)',
        'confirm'
      )
    );
    await submitMessage(result, '09:00');

    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '09:00' }
    );
  });

  test('slot -> confirmation transition: a bare "yes" after all fields are set sends YesIntent', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);
    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '09:00');

    callBackend.mockResolvedValueOnce(envelopeWithText('Your appointment for Sagar has been booked.', 'booked'));
    await submitMessage(result, 'yes');

    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });

  test('a numeric reply at the slot stage is forwarded as-is, not rejected as an invalid time', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);

    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2');

    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '2' }
    );
  });

  test('date is not parsed while the booking stage is provider', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Ram? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'Dr. ram');

    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'Dr. ram' });
    const lastMessage = result.current.messages[result.current.messages.length - 1];
    expect(lastMessage.content.text.toLowerCase()).not.toMatch(/couldn't understand that date/);
  });

  test('a time-shaped reply at the provider stage is sent as providerId, not parsed as a slot', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(envelopeWithText('...', 'date'));
    await submitMessage(result, '10:00');

    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: '10:00' });
  });

  test('a date-shaped reply at the date stage is still parsed normally (unchanged existing behavior)', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);
    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'dr-patel');

    await submitMessage(result, 'not a date');
    const lastMessage = result.current.messages[result.current.messages.length - 1];
    expect(lastMessage.content.text).toMatch(/couldn't understand that date/);
    // A rejected date must not have been sent to the backend as `date`.
    expect(callBackend).not.toHaveBeenCalledWith(
      'Book Appointment', expect.objectContaining({ date: expect.anything() })
    );
  });

  test('booking completion resets state - the next message routes as an ordinary (non-booking) message', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);
    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '09:00');

    callBackend.mockResolvedValueOnce(envelopeWithText('Your appointment for Sagar has been booked.', 'booked'));
    await submitMessage(result, 'yes');

    callBackend.mockResolvedValueOnce(envelopeWithText('Hi! I can help with...'));
    await submitMessage(result, 'hello there');

    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('regression: "Dr. ram" after the name at the provider stage must not be rejected as an invalid date', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Ram? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'Dr. ram');

    const lastMessage = result.current.messages[result.current.messages.length - 1];
    expect(lastMessage.content.text).not.toBe("I couldn't understand that date. Try a format like 2026-12-26, 26-12-2026, or \"26 December 2026\".");
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'Dr. ram' });
  });

  test('regression: an invalid provider is NOT retained - the next reply is still treated as a provider attempt', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText(
        "Sorry, I didn't recognize that provider. Please choose one from the list:\n1. Dr. Patel...",
        'provider'
      )
    );
    await submitMessage(result, 'Not A Real Doctor');
    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'Not A Real Doctor' }
    );

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'Dr. Patel');

    // The rejected providerId must not have lingered: this retry must be
    // sent as a fresh provider attempt (providerId: 'Dr. Patel'), not
    // misread as a date - which would either send no providerId change
    // at all, or show "I couldn't understand that date" instead.
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'Dr. Patel' });
    const lastMessage = result.current.messages[result.current.messages.length - 1];
    expect(lastMessage.content.text).not.toMatch(/couldn't understand that date/);
  });

  test('a valid provider IS retained across the next message', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToProviderStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText('What date would you like to see Dr. Patel? (YYYY-MM-DD)', 'date')
    );
    await submitMessage(result, 'dr-patel');

    callBackend.mockResolvedValueOnce(envelopeWithText('...', 'slot'));
    await submitMessage(result, '2026-12-28');

    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28' }
    );
  });

  test('regression: an invalid/unavailable slot is NOT retained - the next reply is still treated as a slot attempt', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);

    callBackend.mockResolvedValueOnce(
      envelopeWithText(
        "Sorry, that time isn't available anymore. Here are the current options:\n1. 09:30",
        'slot'
      )
    );
    await submitMessage(result, '10:00');
    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00' }
    );

    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '09:30');

    // The rejected time must not have lingered: "09:30" must be sent as a
    // fresh slot attempt, not misread as a yes/no confirmation reply
    // (which would never call the backend with a `time` key at all, and
    // would instead show the "reply yes or no" fallback message).
    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '09:30' }
    );
  });

  test('a valid slot IS retained across the next message (reaches confirmation)', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToSlotStage(result);

    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '09:00');

    callBackend.mockResolvedValueOnce(envelopeWithText('Your appointment for Sagar has been booked.', 'booked'));
    await submitMessage(result, 'yes');

    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });
});
