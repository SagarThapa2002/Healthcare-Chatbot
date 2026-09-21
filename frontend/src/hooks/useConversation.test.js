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

// Builds a fake Cancel Appointment (or its yes/no confirmation) envelope
// with a given `cancellationStage`, matching
// backend/response_model.py's success_response(..., cancellation_stage=...)
// contract exactly - `cancellationStage` is omitted from `context` when
// not given, the same way the real contract omits it. This is the ONLY
// signal these tests use to drive the flow forward - never suggestions,
// never message text.
function envelopeWithCancellation(text, cancellationStage) {
  return {
    success: true,
    error: null,
    messages: [{ type: 'text', content: { text }, suggestions: [] }],
    context: { intent: 'Cancel Appointment', ...(cancellationStage ? { cancellationStage } : {}) },
    meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
  };
}

describe('cancellation flow (Phase 6.1 Slice A - frontend, context.cancellationStage only)', () => {
  beforeEach(() => {
    callBackend.mockReset();
  });

  test('starting cancellation stores "identifier" - the next reply is routed as a cancellation identifier, not a fresh intent', async () => {
    const { result } = renderHook(() => useConversation());

    callBackend.mockResolvedValueOnce(
      envelopeWithCancellation("Sure - what's the ID or name on the appointment you'd like to cancel?", 'identifier')
    );
    await submitMessage(result, 'cancel my appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', {});

    callBackend.mockResolvedValueOnce(
      envelopeWithCancellation('Please confirm — cancel the appointment for Sagar on 2026-12-28 at 09:00? (yes or no)', 'confirm')
    );
    // Free text that would otherwise be classified as General FAQ must
    // still be routed back into the cancellation flow, as a `name`.
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { name: 'Sagar' });
  });

  test('a UUID-shaped identifier reply is sent as `id`, not `name` - without the frontend matching it against any appointment', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');

    const uuid = 'b3f2c9a0-1e2d-4b3a-9c1d-8e7f6a5b4c3d';
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'confirm'));
    await submitMessage(result, uuid);
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { id: uuid });
  });

  test('identifier response advancing to "confirm": a bare "yes" reaches YesIntent (no separate confirmation API)', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');

    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');

    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Your appointment ... has been cancelled.', 'cancelled'));
    await submitMessage(result, 'yes');
    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });

  test('confirm "yes" reaching "cancelled" resets local state - the next message is ordinary single-shot routing', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('... has been cancelled.', 'cancelled'));
    await submitMessage(result, 'yes');

    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('confirm "no" is sent via the existing NoIntent mechanism and resets local state per the backend response', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');

    // _handle_cancel_confirm_no returns cancellation_stage=None (declining
    // doesn't advance to any named stage) - the fake envelope below omits
    // it, exactly like the real contract does.
    callBackend.mockResolvedValueOnce(envelopeWithCancellation("No problem! I've left that appointment unchanged.", undefined));
    await submitMessage(result, 'no');
    expect(callBackend).toHaveBeenLastCalledWith('NoIntent', {});

    // Local state must have been cleared - the next message is ordinary
    // routing, not misread as still awaiting a confirm/identifier reply.
    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('a missing cancellationStage does not cause an inferred state transition (fail closed)', async () => {
    const { result } = renderHook(() => useConversation());

    // No cancellationStage at all in the response context - e.g. the
    // "not found" path in _handle_cancel_appointment, which returns None.
    callBackend.mockResolvedValueOnce(envelopeWithCancellation("I couldn't find an appointment for Someone to cancel.", undefined));
    await submitMessage(result, 'cancel my appointment');

    // The next message must be routed as an ordinary fresh intent, not
    // treated as an "identifier" or "confirm" reply.
    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('an in-progress cancellation does not affect a subsequent, independent booking flow', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithCancellation("I couldn't find an appointment for Ghost to cancel.", undefined));
    await submitMessage(result, 'Ghost');

    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await submitMessage(result, 'book an appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', {});

    callBackend.mockResolvedValueOnce(
      envelopeWithText('Thanks Sagar. Which provider would you like to see?\n1. Dr. Patel...', 'provider')
    );
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar' });
  });

  test('normal YesIntent/NoIntent behavior is unchanged when there is no pending cancellation (no booking either)', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'yes');
    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});

    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'no');
    expect(callBackend).toHaveBeenLastCalledWith('NoIntent', {});
  });

  test('regression: Cancel Appointment interrupting an active booking still stores cancellationStage - the next reply stays in the cancellation flow', async () => {
    const { result } = renderHook(() => useConversation());

    // Get a booking into progress (stage: 'name').
    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await submitMessage(result, 'book an appointment');

    // Interrupt it with a cancellation.
    callBackend.mockResolvedValueOnce(
      envelopeWithCancellation("Sure - what's the ID or name on the appointment you'd like to cancel?", 'identifier')
    );
    await submitMessage(result, 'cancel my appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', {});

    // The next free-text reply must stay in the cancellation flow (sent
    // as `name`), not be routed as General FAQ or as booking's own
    // 'name' stage input.
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { name: 'Sagar' });
  });
});

// Builds a fake Update Appointment (or its yes/no confirmation) envelope
// with a given `updateStage`, matching backend/response_model.py's
// success_response(..., update_stage=...) contract exactly -
// `updateStage` is omitted from `context` when not given, the same way
// the real contract omits it.
function envelopeWithUpdate(text, updateStage) {
  return {
    success: true,
    error: null,
    messages: [{ type: 'text', content: { text }, suggestions: [] }],
    context: { intent: 'Update Appointment', ...(updateStage ? { updateStage } : {}) },
    meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
  };
}

describe('update flow (Phase 6.1 Slice B - frontend, context.updateStage only)', () => {
  beforeEach(() => {
    callBackend.mockReset();
  });

  test('starting update stores "identifier" - the next reply is routed as an update identifier, not a fresh intent', async () => {
    const { result } = renderHook(() => useConversation());

    callBackend.mockResolvedValueOnce(
      envelopeWithUpdate("Sure - what's the ID or name on the appointment you'd like to update?", 'identifier')
    );
    await submitMessage(result, 'update my appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', {});

    callBackend.mockResolvedValueOnce(
      envelopeWithUpdate('Got it - what would you like to change?', 'fields')
    );
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar' });
  });

  test('a UUID-shaped identifier reply is sent as `id`, not `name`', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');

    const uuid = 'b3f2c9a0-1e2d-4b3a-9c1d-8e7f6a5b4c3d';
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'fields'));
    await submitMessage(result, uuid);
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { id: uuid });
  });

  test('fields stage: a recognized date is sent as `date`, alongside the captured identifier', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What would you like to change?', 'fields'));
    await submitMessage(result, 'Sagar');

    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar', date: '2026-12-30' });
  });

  test('fields stage: a recognized time is sent as `time`, alongside the captured identifier', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What would you like to change?', 'fields'));
    await submitMessage(result, 'Sagar');

    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '14:00');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar', time: '14:00' });
  });

  test('fields stage: a reply containing both a date and a time sends both', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What would you like to change?', 'fields'));
    await submitMessage(result, 'Sagar');

    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30 at 14:00');
    expect(callBackend).toHaveBeenLastCalledWith(
      'Update Appointment', { name: 'Sagar', date: '2026-12-30', time: '14:00' }
    );
  });

  test('fields stage: neither a date nor a time recognized - no backend call, state remains "fields"', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What would you like to change?', 'fields'));
    await submitMessage(result, 'Sagar');

    callBackend.mockClear();
    await submitMessage(result, 'not a date or a time');
    expect(callBackend).not.toHaveBeenCalled();

    // State must still be "fields" - the next, valid reply is still
    // treated as answering it, not routed as a fresh intent.
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar', date: '2026-12-30' });
  });

  test('confirm "yes" reaches YesIntent (no separate confirmation API)', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'fields'));
    await submitMessage(result, 'Sagar');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30');

    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Your appointment has been updated.', 'updated'));
    await submitMessage(result, 'yes');
    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });

  test('confirm "no" reaches NoIntent and resets local state per the backend response', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'fields'));
    await submitMessage(result, 'Sagar');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30');

    // _handle_update_confirm_no returns update_stage=None.
    callBackend.mockResolvedValueOnce(envelopeWithUpdate("No problem! I've left that appointment unchanged.", undefined));
    await submitMessage(result, 'no');
    expect(callBackend).toHaveBeenLastCalledWith('NoIntent', {});

    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('"updated" resets local state - the next message is ordinary single-shot routing', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'fields'));
    await submitMessage(result, 'Sagar');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm... (yes or no)', 'confirm'));
    await submitMessage(result, '2026-12-30');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Your appointment has been updated.', 'updated'));
    await submitMessage(result, 'yes');

    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('a missing updateStage does not cause an inferred state transition (fail closed)', async () => {
    const { result } = renderHook(() => useConversation());

    // No updateStage at all in the response context - e.g. the "not
    // found" path in _handle_update_appointment, which returns None.
    callBackend.mockResolvedValueOnce(envelopeWithUpdate("I couldn't find an appointment for Someone to update.", undefined));
    await submitMessage(result, 'update my appointment');

    callBackend.mockResolvedValueOnce(fakeEnvelope());
    await submitMessage(result, 'hello there');
    expect(callBackend).toHaveBeenLastCalledWith('General FAQ', { message: 'hello there' });
  });

  test('an in-progress update does not affect a subsequent, independent booking flow', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate("I couldn't find an appointment for Ghost to update.", undefined));
    await submitMessage(result, 'Ghost');

    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await submitMessage(result, 'book an appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', {});
  });

  test('an in-progress update does not affect an independent cancellation flow', async () => {
    const { result } = renderHook(() => useConversation());
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('...', 'identifier'));
    await submitMessage(result, 'update my appointment');
    callBackend.mockResolvedValueOnce(envelopeWithUpdate("I couldn't find an appointment for Ghost to update.", undefined));
    await submitMessage(result, 'Ghost');

    callBackend.mockResolvedValueOnce(envelopeWithCancellation('...', 'identifier'));
    await submitMessage(result, 'cancel my appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', {});
  });

  test('regression: Update Appointment interrupting an active booking still stores updateStage - the next reply stays in the update flow', async () => {
    const { result } = renderHook(() => useConversation());

    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await submitMessage(result, 'book an appointment');

    callBackend.mockResolvedValueOnce(
      envelopeWithUpdate("Sure - what's the ID or name on the appointment you'd like to update?", 'identifier')
    );
    await submitMessage(result, 'update my appointment');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', {});

    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What would you like to change?', 'fields'));
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar' });
  });
});
