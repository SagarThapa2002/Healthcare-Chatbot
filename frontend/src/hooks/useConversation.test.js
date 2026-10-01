import { act, renderHook, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { useConversation } from './useConversation';
import Chatbot from '../components/Chatbot';
import { callBackend, startConversation } from '../api/client';

// Only the payload construction is under test here - callBackend itself
// (network/normalization) is mocked entirely, so these tests never touch
// the network and don't need a real backend running.
jest.mock('../api/client', () => ({
  callBackend: jest.fn(),
  startConversation: jest.fn(),
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

  test('an accepted booking start (bookingStage present) activates local booking state', async () => {
    const { result } = renderHook(() => useConversation());

    callBackend.mockResolvedValueOnce(
      envelopeWithText('Sure, may I have your name for the appointment?', 'name')
    );
    await submitMessage(result, 'book an appointment');

    // The next message must be treated as answering the 'name' stage -
    // not routed as a fresh, unrelated intent - proving the local
    // booking state was actually activated by the accepted response.
    callBackend.mockResolvedValueOnce(
      envelopeWithText('Thanks Sagar. Which provider would you like to see?\n1. Dr. Patel...', 'provider')
    );
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar' });
  });

  test('regression: a refused booking start (no bookingStage) does NOT activate local booking state', async () => {
    const { result } = renderHook(() => useConversation());

    // Matches chatbot_logic.py's _handle_book_appointment mutual-exclusion
    // guard: refused because another transaction (cancellation/update) is
    // already pending - reports no bookingStage at all, exactly like the
    // real contract omits it here (see envelopeWithText's own docstring).
    callBackend.mockResolvedValueOnce(
      envelopeWithText(
        'You already have another appointment action waiting for confirmation. '
        + 'Please reply "yes" or "no" to finish that first, then try booking an appointment.',
        undefined,
      )
    );
    await submitMessage(result, 'book an appointment');

    // The next message must NOT be swallowed by a fabricated local
    // booking state - it must route as ordinary, unrelated single-shot
    // intent (e.g. a bare "yes" reaches YesIntent directly, not
    // misread as a name-stage reply).
    callBackend.mockResolvedValueOnce(fakeEnvelope());
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

// Regression for backend-provided suggestion chips: renders the real
// Chatbot (real ChatPanel + real useConversation, with only callBackend
// mocked) so the test goes through an actual chip click rather than
// calling sendMessage directly. Production useConversation.js is unchanged
// - this only proves the existing identifier-stage `{ id }` routing is
// what a chip click reaches.
describe('backend-provided appointment suggestion chips (rendered Chatbot)', () => {
  beforeEach(() => {
    callBackend.mockReset();
  });

  test('clicking a disambiguation chip sends that appointment as `{ id }` through the existing cancellation routing', async () => {
    const candidates = [
      { id: 'b3f2c9a0-1e2d-4b3a-9c1d-8e7f6a5b4c3d', label: '2026-12-28 at 09:00', value: 'b3f2c9a0-1e2d-4b3a-9c1d-8e7f6a5b4c3d' },
      { id: 'c4a3d0b1-2f3e-4c4b-8d2e-9f8a7b6c5d4e', label: '2026-12-30 at 14:00', value: 'c4a3d0b1-2f3e-4c4b-8d2e-9f8a7b6c5d4e' },
    ];
    render(<Chatbot />);

    // 1. Start cancellation -> backend asks for an identifier.
    callBackend.mockResolvedValueOnce(envelopeWithCancellation("What's the ID or name on the appointment?", 'identifier'));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'cancel my appointment' } });
    fireEvent.submit(screen.getByRole('textbox').closest('form'));
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', {}));

    // 2. Reply with a name that matches several appointments -> backend
    // stays at "identifier" and attaches one suggestion per candidate.
    callBackend.mockResolvedValueOnce({
      ...envelopeWithCancellation('I found multiple appointments for Sagar. Please tell me the appointment ID:', 'identifier'),
      messages: [{
        type: 'text',
        content: { text: 'I found multiple appointments for Sagar. Please tell me the appointment ID:' },
        suggestions: candidates,
      }],
    });
    await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Sagar' } });
    fireEvent.submit(screen.getByRole('textbox').closest('form'));
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { name: 'Sagar' }));

    // 3. Click the second chip -> its value goes out as `{ id }`.
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm - cancel it? (yes or no)', 'confirm'));
    fireEvent.click(await screen.findByRole('button', { name: '2026-12-30 at 14:00' }));
    await waitFor(() =>
      expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { id: candidates[1].value })
    );
    expect(callBackend).toHaveBeenCalledTimes(3);

    // The chips belonged to the previous bot message, so they are gone now.
    await waitFor(() => expect(screen.queryByRole('button', { name: '2026-12-28 at 09:00' })).not.toBeInTheDocument());
  });

  test('clicking a provider chip sends its provider id through the existing provider-stage routing and advances to date', async () => {
    const providers = [
      { id: 'dr-patel', label: 'Dr. Patel - General Practice', value: 'dr-patel' },
      { id: 'dr-nguyen', label: 'Dr. Nguyen - Pediatrics', value: 'dr-nguyen' },
    ];
    const typeAndSubmit = async (value) => {
      await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
      fireEvent.change(screen.getByRole('textbox'), { target: { value } });
      fireEvent.submit(screen.getByRole('textbox').closest('form'));
    };
    render(<Chatbot />);

    // 1. Start booking -> backend asks for a name.
    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await typeAndSubmit('book an appointment');
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', {}));

    // 2. Name -> backend asks for a provider and attaches one chip per provider.
    callBackend.mockResolvedValueOnce({
      ...envelopeWithText('Thanks Sagar. Which provider would you like to see?', 'provider'),
      messages: [{
        type: 'text',
        content: { text: 'Thanks Sagar. Which provider would you like to see?' },
        suggestions: providers,
      }],
    });
    await typeAndSubmit('Sagar');
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar' }));

    // 3. Click the second chip -> its value goes out as providerId.
    callBackend.mockResolvedValueOnce(envelopeWithText('What date would you like to see Dr. Nguyen? (YYYY-MM-DD)', 'date'));
    fireEvent.click(await screen.findByRole('button', { name: 'Dr. Nguyen - Pediatrics' }));
    await waitFor(() =>
      expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar', providerId: 'dr-nguyen' })
    );

    // 4. The backend accepted it (bookingStage "date"), so the next reply is
    // parsed as a date and sent alongside the chip's provider id.
    callBackend.mockResolvedValueOnce(envelopeWithText('Here are the available times on 2026-12-29:', 'slot'));
    await typeAndSubmit('2026-12-29');
    await waitFor(() =>
      expect(callBackend).toHaveBeenLastCalledWith(
        'Book Appointment', { name: 'Sagar', providerId: 'dr-nguyen', date: '2026-12-29' }
      )
    );
    expect(callBackend).toHaveBeenCalledTimes(4);
  });

  // Booking confirmation Yes/No chips: the chip values are the same bare
  // "yes"/"no" a user could type, so they reach the existing confirm-stage
  // routing (YesIntent/NoIntent with no parameters - the backend reads the
  // pending booking itself). Drives name -> provider -> date -> slot by
  // typing, then clicks the chip the backend attached to the confirm prompt.
  const YES_NO = [
    { id: 'yes', label: 'Yes', value: 'yes' },
    { id: 'no', label: 'No', value: 'no' },
  ];

  async function renderAtBookingConfirm() {
    const typeAndSubmit = async (value) => {
      await waitFor(() => expect(screen.getByRole('textbox')).not.toBeDisabled());
      fireEvent.change(screen.getByRole('textbox'), { target: { value } });
      fireEvent.submit(screen.getByRole('textbox').closest('form'));
    };
    render(<Chatbot />);

    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name for the appointment?', 'name'));
    await typeAndSubmit('book an appointment');
    callBackend.mockResolvedValueOnce(envelopeWithText('Which provider would you like to see?', 'provider'));
    await typeAndSubmit('Sagar');
    callBackend.mockResolvedValueOnce(envelopeWithText('What date would you like to see Dr. Patel?', 'date'));
    await typeAndSubmit('dr-patel');
    callBackend.mockResolvedValueOnce(envelopeWithText('Here are the available times on 2026-12-28:', 'slot'));
    await typeAndSubmit('2026-12-28');

    const confirmText = 'Please confirm — book appointment with Dr. Patel for Sagar on 2026-12-28 at 10:00? (yes or no)';
    callBackend.mockResolvedValueOnce({
      ...envelopeWithText(confirmText, 'confirm'),
      messages: [{ type: 'text', content: { text: confirmText }, suggestions: YES_NO }],
    });
    await typeAndSubmit('10:00');
    await waitFor(() =>
      expect(callBackend).toHaveBeenLastCalledWith(
        'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00' }
      )
    );
  }

  test('clicking the Yes chip at booking confirmation sends the existing YesIntent', async () => {
    await renderAtBookingConfirm();

    callBackend.mockResolvedValueOnce(envelopeWithText('Your appointment has been booked.', 'booked'));
    fireEvent.click(await screen.findByRole('button', { name: 'Yes' }));
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {}));
    expect(callBackend).toHaveBeenCalledTimes(6);
  });

  test('clicking the No chip at booking confirmation sends the existing NoIntent', async () => {
    await renderAtBookingConfirm();

    callBackend.mockResolvedValueOnce(envelopeWithText('No problem! Appointment booking has been canceled.'));
    fireEvent.click(await screen.findByRole('button', { name: 'No' }));
    await waitFor(() => expect(callBackend).toHaveBeenLastCalledWith('NoIntent', {}));
    expect(callBackend).toHaveBeenCalledTimes(6);
  });
});

describe('conversation session lifecycle', () => {
  beforeEach(() => {
    callBackend.mockReset();
    callBackend.mockResolvedValue(fakeEnvelope());
    startConversation.mockClear();
  });

  test('a conversation is started once per mount, not once per request', async () => {
    const { result, rerender, unmount } = renderHook(() => useConversation());
    expect(startConversation).toHaveBeenCalledTimes(1);

    await submitMessage(result, 'What is a balanced diet?');
    await submitMessage(result, 'yes');
    await submitMessage(result, 'no');
    rerender();

    expect(callBackend).toHaveBeenCalledTimes(3);
    expect(startConversation).toHaveBeenCalledTimes(1);

    unmount();
    renderHook(() => useConversation());
    expect(startConversation).toHaveBeenCalledTimes(2);
  });
});

// Interrupting a booking at CONFIRM: the backend already holds the pending
// booking, so the frontend discards it with NoIntent {} before switching task.
// Earlier stages hold no backend pending state and send no NoIntent.
describe('interrupting a booking discards the backend pending booking only at CONFIRM', () => {
  const DISCARD_REPLY = 'No problem! Appointment booking has been canceled.';

  beforeEach(() => {
    callBackend.mockReset();
  });

  async function bookThroughToConfirmStage(result) {
    await bookThroughToSlotStage(result);
    callBackend.mockResolvedValueOnce(envelopeWithText('Please confirm (yes or no)', 'confirm'));
    await submitMessage(result, '10:00');
  }

  function intentsSent() {
    return callBackend.mock.calls.map(([intent]) => intent);
  }

  function botTexts(result) {
    return result.current.messages.filter((m) => m.sender === 'bot').map((m) => m.content.text);
  }

  test.each([
    ['View Appointments', 'view my appointments', {}],
    ['Symptom Check', 'I have a headache', { symptom: 'I have a headache' }],
    ['Cancel Appointment', 'cancel my appointment', {}],
    ['Update Appointment', 'update my appointment', {}],
  ])('at CONFIRM, %s sends NoIntent {} first, then the interrupting intent', async (intent, message, params) => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToConfirmStage(result);
    const before = callBackend.mock.calls.length;

    callBackend
      .mockResolvedValueOnce(envelopeWithText(DISCARD_REPLY))
      .mockResolvedValueOnce(envelopeWithText('Interrupting reply'));
    await submitMessage(result, message);

    expect(callBackend.mock.calls.slice(before)).toEqual([['NoIntent', {}], [intent, params]]);
    // The discard's reply is never shown; only the prefixed interruption reply is.
    expect(botTexts(result)).not.toContain(DISCARD_REPLY);
    expect(botTexts(result).at(-1)).toBe('(Cancelled your in-progress booking.) Interrupting reply');
  });

  test('the interrupting intent is sent only after NoIntent has completed', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToConfirmStage(result);
    const before = callBackend.mock.calls.length;

    let finishDiscard;
    callBackend
      .mockReturnValueOnce(new Promise((resolve) => { finishDiscard = resolve; }))
      .mockResolvedValueOnce(envelopeWithText('Here are your appointments.'));

    act(() => {
      result.current.setUserInput('view my appointments');
    });
    let sending;
    act(() => {
      sending = result.current.sendMessage({ preventDefault: () => {} });
    });
    await act(async () => {
      await Promise.resolve();
    });
    expect(callBackend.mock.calls.slice(before)).toEqual([['NoIntent', {}]]);

    await act(async () => {
      finishDiscard(envelopeWithText(DISCARD_REPLY));
      await sending;
    });
    expect(intentsSent().slice(before)).toEqual(['NoIntent', 'View Appointments']);
  });

  test('a later bare "yes" is a plain YesIntent {} once the booking was interrupted at CONFIRM', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToConfirmStage(result);
    callBackend
      .mockResolvedValueOnce(envelopeWithText(DISCARD_REPLY))
      .mockResolvedValueOnce(envelopeWithText('Here are your appointments.'));
    await submitMessage(result, 'view my appointments');

    callBackend.mockResolvedValueOnce(envelopeWithText('There is no appointment pending confirmation.'));
    await submitMessage(result, 'yes');
    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });

  test.each([
    ['name', async (result) => {
      callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name?', 'name'));
      await submitMessage(result, 'book an appointment');
    }],
    ['provider', bookThroughToProviderStage],
    ['date', async (result) => {
      await bookThroughToProviderStage(result);
      callBackend.mockResolvedValueOnce(envelopeWithText('What date?', 'date'));
      await submitMessage(result, 'dr-patel');
    }],
    ['slot', bookThroughToSlotStage],
  ])('at the %s stage, an interruption sends no NoIntent', async (_stage, reachStage) => {
    const { result } = renderHook(() => useConversation());
    await reachStage(result);
    const before = callBackend.mock.calls.length;

    callBackend.mockResolvedValueOnce(envelopeWithText('Here are your appointments.'));
    await submitMessage(result, 'view my appointments');

    expect(callBackend.mock.calls.slice(before)).toEqual([['View Appointments', {}]]);
    expect(intentsSent()).not.toContain('NoIntent');
    expect(botTexts(result).at(-1)).toBe('(Cancelled your in-progress booking.) Here are your appointments.');
  });

  test('if NoIntent fails (rejects), the interrupting intent is not sent and nothing claims a cancellation', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToConfirmStage(result);
    const before = callBackend.mock.calls.length;

    callBackend.mockRejectedValueOnce(new Error('network down'));
    const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    await submitMessage(result, 'view my appointments');
    errorSpy.mockRestore();

    expect(callBackend.mock.calls.slice(before)).toEqual([['NoIntent', {}]]);
    expect(botTexts(result).at(-1)).toBe('Sorry, an error occurred.');
    expect(botTexts(result).some((t) => t.includes('Cancelled your in-progress booking'))).toBe(false);

    // The booking is still at CONFIRM locally, matching the backend: "yes" confirms it.
    callBackend.mockResolvedValueOnce(envelopeWithText('Booked.', 'booked'));
    await submitMessage(result, 'yes');
    expect(callBackend).toHaveBeenLastCalledWith('YesIntent', {});
  });

  test('if NoIntent reports success: false, the interrupting intent is not sent and nothing claims a cancellation', async () => {
    const { result } = renderHook(() => useConversation());
    await bookThroughToConfirmStage(result);
    const before = callBackend.mock.calls.length;

    callBackend.mockResolvedValueOnce({
      success: false,
      error: { code: 'INTERNAL_ERROR', message: 'Oops, something went wrong on the server.' },
      messages: [],
      context: null,
      meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
    });
    await submitMessage(result, 'view my appointments');

    expect(callBackend.mock.calls.slice(before)).toEqual([['NoIntent', {}]]);
    expect(botTexts(result).at(-1)).toBe('Oops, something went wrong on the server.');
    expect(botTexts(result).some((t) => t.includes('Cancelled your in-progress booking'))).toBe(false);
  });

  test('regression: an abandoned booking is never confirmed by a later "yes" (modelled backend pending state)', async () => {
    // A minimal stand-in for the backend's per-conversation pending booking:
    // written at CONFIRM, discarded by NoIntent, consumed by YesIntent.
    let pending = null;
    const booked = [];
    callBackend.mockImplementation(async (intent, params) => {
      if (intent === 'Book Appointment') {
        const stage = !params.name ? 'name' : !params.providerId ? 'provider'
          : !params.date ? 'date' : !params.time ? 'slot' : 'confirm';
        if (stage === 'confirm') pending = { ...params };
        return envelopeWithText(`stage ${stage}`, stage);
      }
      if (intent === 'NoIntent') {
        pending = null;
        return envelopeWithText('discarded');
      }
      if (intent === 'YesIntent') {
        if (!pending) return envelopeWithText('There is no appointment pending confirmation.');
        booked.push(pending);
        pending = null;
        return envelopeWithText('Booked.', 'booked');
      }
      return envelopeWithText(`${intent} reply`);
    });

    const { result } = renderHook(() => useConversation());
    for (const message of ['book an appointment', 'Sagar', 'dr-patel', '2026-12-28', '10:00']) {
      await submitMessage(result, message);
    }
    expect(pending).toEqual({ name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28', time: '10:00' });

    await submitMessage(result, 'view my appointments');
    expect(pending).toBeNull();

    await submitMessage(result, 'yes');
    expect(booked).toEqual([]);
    expect(intentsSent().slice(-3)).toEqual(['NoIntent', 'View Appointments', 'YesIntent']);
  });
});

// Leaving a cancellation or update before CONFIRM. The backend holds no
// pending state at these steps, so "no" and task switches are handled
// locally: no request for "no", and a task switch is routed normally instead
// of being sent as an appointment name or re-prompted.
describe('leaving cancel/update flows before confirmation', () => {
  const LEFT_UNCHANGED = "Okay, I've left your appointment unchanged.";
  const APPOINTMENT_ID = '11111111-1111-4111-8111-111111111111';

  beforeEach(() => {
    callBackend.mockReset();
    callBackend.mockResolvedValue(fakeEnvelope());
  });

  async function reachCancelIdentifier(result) {
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('What is the ID or name?', 'identifier'));
    await submitMessage(result, 'cancel my appointment');
  }

  async function reachUpdateIdentifier(result) {
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What is the ID or name?', 'identifier'));
    await submitMessage(result, 'update my appointment');
  }

  async function reachUpdateFields(result) {
    await reachUpdateIdentifier(result);
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('What new date or time?', 'fields'));
    await submitMessage(result, 'Sagar');
  }

  function callsSince(before) {
    return callBackend.mock.calls.slice(before);
  }

  function lastBotText(result) {
    return result.current.messages.filter((m) => m.sender === 'bot').at(-1).content.text;
  }

  // After leaving a flow, a plain name must be routed as ordinary input
  // (General FAQ), not as that flow's identifier or fields reply.
  async function expectFlowLeft(result) {
    const before = callBackend.mock.calls.length;
    await submitMessage(result, 'Sagar');
    expect(callsSince(before)).toEqual([['General FAQ', { message: 'Sagar' }]]);
  }

  const SWITCHES = {
    book: ['book an appointment', 'Book Appointment', {}],
    view: ['view my appointments', 'View Appointments', {}],
    symptom: ['I have a headache', 'Symptom Check', { symptom: 'I have a headache' }],
    cancel: ['cancel my appointment', 'Cancel Appointment', {}],
    update: ['update my appointment', 'Update Appointment', {}],
  };

  // --- update: fields step ---

  test('update fields: "no" leaves the flow locally, with no backend request', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'no');

    expect(callsSince(before)).toEqual([]);
    expect(lastBotText(result)).toBe(LEFT_UNCHANGED);
    await expectFlowLeft(result);
  });

  test.each(['book', 'view', 'symptom', 'cancel'])('update fields: the %s request switches task', async (key) => {
    const [message, intent, params] = SWITCHES[key];
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, message);

    expect(callsSince(before)).toEqual([[intent, params]]);
  });

  test('update fields: "update my appointment" stays in the update flow', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'update my appointment');
    expect(callsSince(before)).toEqual([]); // the existing local re-prompt

    await submitMessage(result, '2026-12-30');
    expect(callsSince(before)).toEqual([['Update Appointment', { name: 'Sagar', date: '2026-12-30' }]]);
  });

  test('update fields: text that is neither a date/time nor a task switch still re-prompts', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'not a date or a time');

    expect(callsSince(before)).toEqual([]);
    expect(lastBotText(result)).toMatch(/I didn't catch a new date or time/);
  });

  test('update fields: a valid date and time are still sent with the identifier', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, '2026-12-30 14:00');

    expect(callsSince(before)).toEqual([['Update Appointment', { name: 'Sagar', date: '2026-12-30', time: '14:00' }]]);
  });

  // --- cancel: identifier step ---

  test.each(['book', 'view', 'symptom', 'update'])('cancel identifier: the %s request switches task instead of becoming a name', async (key) => {
    const [message, intent, params] = SWITCHES[key];
    const { result } = renderHook(() => useConversation());
    await reachCancelIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, message);

    expect(callsSince(before)).toEqual([[intent, params]]);
    expect(callBackend).not.toHaveBeenCalledWith('Cancel Appointment', { name: message });
  });

  test('cancel identifier: after a switch to viewing, the cancellation flow is left', async () => {
    const { result } = renderHook(() => useConversation());
    await reachCancelIdentifier(result);
    await submitMessage(result, 'view my appointments');
    await expectFlowLeft(result);
  });

  test('cancel identifier: "cancel my appointment" stays in the cancellation flow', async () => {
    const { result } = renderHook(() => useConversation());
    await reachCancelIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'cancel my appointment');

    expect(callsSince(before)).toEqual([['Cancel Appointment', { name: 'cancel my appointment' }]]);
  });

  test('cancel identifier: "no" leaves the flow locally, with no backend request', async () => {
    const { result } = renderHook(() => useConversation());
    await reachCancelIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'no');

    expect(callsSince(before)).toEqual([]);
    expect(lastBotText(result)).toBe(LEFT_UNCHANGED);
    await expectFlowLeft(result);
  });

  test('cancel identifier: a name and a UUID are still sent as name and id', async () => {
    const { result } = renderHook(() => useConversation());
    await reachCancelIdentifier(result);
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Which one?', 'identifier'));
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { name: 'Sagar' });

    await submitMessage(result, APPOINTMENT_ID);
    expect(callBackend).toHaveBeenLastCalledWith('Cancel Appointment', { id: APPOINTMENT_ID });
  });

  // --- update: identifier step ---

  test.each(['book', 'view', 'symptom', 'cancel'])('update identifier: the %s request switches task instead of becoming a name', async (key) => {
    const [message, intent, params] = SWITCHES[key];
    const { result } = renderHook(() => useConversation());
    await reachUpdateIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, message);

    expect(callsSince(before)).toEqual([[intent, params]]);
    expect(callBackend).not.toHaveBeenCalledWith('Update Appointment', { name: message });
  });

  test('update identifier: "update my appointment" stays in the update flow', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'update my appointment');

    expect(callsSince(before)).toEqual([['Update Appointment', { name: 'update my appointment' }]]);
  });

  test('update identifier: "no" leaves the flow locally, with no backend request', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateIdentifier(result);
    const before = callBackend.mock.calls.length;

    await submitMessage(result, 'no');

    expect(callsSince(before)).toEqual([]);
    expect(lastBotText(result)).toBe(LEFT_UNCHANGED);
    await expectFlowLeft(result);
  });

  test('update identifier: a name and a UUID are still sent as name and id', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateIdentifier(result);
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Which one?', 'identifier'));
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { name: 'Sagar' });

    await submitMessage(result, APPOINTMENT_ID);
    expect(callBackend).toHaveBeenLastCalledWith('Update Appointment', { id: APPOINTMENT_ID });
  });

  // --- regression and unchanged confirm steps ---

  test('regression: the update-fields trap - "no" and a new task both get the user out', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateFields(result);
    const reprompts = () => result.current.messages.filter((m) => /I didn't catch a new date or time/.test(m.content?.text ?? '')).length;

    await submitMessage(result, 'no');
    expect(reprompts()).toBe(0);
    expect(lastBotText(result)).toBe(LEFT_UNCHANGED);

    await reachUpdateFields(result);
    const before = callBackend.mock.calls.length;
    callBackend.mockResolvedValueOnce(envelopeWithText('Sure, may I have your name?', 'name'));
    await submitMessage(result, 'book an appointment');
    expect(callsSince(before)).toEqual([['Book Appointment', {}]]);
    expect(reprompts()).toBe(0);

    // The booking flow is now active: the next reply is its name, not an update field.
    callBackend.mockResolvedValueOnce(envelopeWithText('Which provider?', 'provider'));
    await submitMessage(result, 'Sagar');
    expect(callBackend).toHaveBeenLastCalledWith('Book Appointment', { name: 'Sagar' });
  });

  test('confirm steps are unchanged: a task request only re-prompts, and "no" still sends NoIntent', async () => {
    const { result } = renderHook(() => useConversation());
    await reachUpdateIdentifier(result);
    callBackend.mockResolvedValueOnce(envelopeWithUpdate('Please confirm (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');

    let before = callBackend.mock.calls.length;
    await submitMessage(result, 'book an appointment');
    expect(callsSince(before)).toEqual([]);
    expect(lastBotText(result)).toMatch(/reply "yes" to confirm the update/);

    await submitMessage(result, 'no');
    expect(callsSince(before)).toEqual([['NoIntent', {}]]);

    await reachCancelIdentifier(result);
    callBackend.mockResolvedValueOnce(envelopeWithCancellation('Please confirm (yes or no)', 'confirm'));
    await submitMessage(result, 'Sagar');
    before = callBackend.mock.calls.length;
    await submitMessage(result, 'view my appointments');
    expect(callsSince(before)).toEqual([]);
    await submitMessage(result, 'no');
    expect(callsSince(before)).toEqual([['NoIntent', {}]]);
  });
});
