import { useState } from 'react';
import { detectIntent, INTERRUPTION_INTENTS } from '../conversation/intent';
import { parseDate, parseTime } from '../conversation/dateTime';
import { isValidName } from '../conversation/validation';
import {
  EMPTY_BOOKING,
  bookingStage,
  bookingParams,
  extractInitialBookingFields,
} from '../conversation/booking';
import { callBackend } from '../api/client';

// Prefixes the display text of an envelope's first message, leaving every
// other field (type, suggestions, context, meta, success, error) untouched.
// Used only for the "switched task while a booking was pending" case below.
function prefixFirstMessage(envelope, prefix) {
  if (envelope.messages.length === 0) return envelope;
  const [first, ...rest] = envelope.messages;
  return {
    ...envelope,
    messages: [
      { ...first, content: { ...first.content, text: `${prefix}${first.content.text}` } },
      ...rest,
    ],
  };
}

// The literal shape of an appointment id (str(uuid.uuid4()) - see
// backend/chatbot_logic.py's _handle_yes_intent and
// backend/response_model.py's _new_request_id, the same convention). Used
// only to pick which of the backend's two independent lookup keys (`id`
// vs `name` - see _handle_cancel_appointment's own docstring) an
// identifier-stage reply is sent under. This recognizes a fixed, stable
// SYNTAX only - it never searches, matches, or disambiguates appointment
// data, so it does not reproduce the backend's own lookup logic.
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Derives the next local update state from an Update Appointment (or its
// yes/no confirmation) response - `stage` reads only context.updateStage,
// never suggestions/prose/message count (same structural-authority
// pattern as cancellationStage). Unlike cancellation, the backend has no
// persisted memory of *which* appointment is being updated until the
// pending-update file is written at the "confirm" stage (see
// backend/chatbot_logic.py's _handle_update_appointment) - so while the
// stage is "fields", every reply must still resend the original id/name
// alongside the new date/time, or the backend has nothing to match
// against. `identifier` is only kept across "fields"/"confirm" (where it
// may still be needed to re-send, or is simply harmless to keep); it's
// cleared on any other stage (including a fresh "identifier" prompt,
// where the next reply will supply and capture a new one).
function deriveUpdateState(envelope, identifier) {
  const stage = envelope.context?.updateStage ?? null;
  const keepIdentifier = stage === 'fields' || stage === 'confirm';
  return { stage, identifier: keepIdentifier ? identifier : null };
}

function useConversation() {
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [booking, setBooking] = useState(EMPTY_BOOKING);
  // The cancellation flow's ENTIRE local state: which stage the backend
  // last reported it's waiting on. Unlike `booking`, there are no field
  // values to accumulate turn over turn (every cancellation reply is a
  // single-shot forward to the backend), so this is just one value - and
  // it is set ONLY from context.cancellationStage on a response, never
  // inferred from suggestions, message text, or any other field (see
  // response_model.success_response's docstring: cancellationStage is the
  // sole structural authority for this flow, the same role bookingStage
  // plays for booking).
  const [cancellationStage, setCancellationStage] = useState(null);
  // The update flow's local state: which stage the backend last reported
  // it's waiting on, plus (while relevant) the id/name captured at the
  // "identifier" stage - see deriveUpdateState's own comment for why this
  // one flow needs slightly more than a bare stage value.
  const [update, setUpdate] = useState({ stage: null, identifier: null });

  // For plain client-side prompts (validation messages, etc.) that never
  // went through the backend, so they render with the same shape as a
  // real structured message.
  const sayText = (text) =>
    setMessages(prev => [...prev, { sender: 'bot', type: 'text', content: { text }, suggestions: [] }]);

  // For a normalized backend envelope (see api/normalizeResponse.js):
  // appends one bot message per entry in envelope.messages, or a single
  // fallback message using the envelope's own error text if the backend
  // reported a genuine failure (messages: []).
  const sayEnvelope = (envelope) => {
    const toShow = envelope.messages.length > 0
      ? envelope.messages
      : [{ type: 'text', content: { text: envelope.error?.message || 'Sorry, an error occurred.' }, suggestions: [] }];
    setMessages(prev => [
      ...prev,
      ...toShow.map((m) => ({ sender: 'bot', type: m.type, content: m.content, suggestions: m.suggestions })),
    ]);
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!userInput.trim()) return;

    const text = userInput;
    setMessages(prev => [...prev, { sender: 'user', text }]);
    setUserInput('');
    setIsTyping(true);

    try {
      const stage = bookingStage(booking);

      if (stage) {
        const answer = text.trim().toLowerCase();

        if (stage === 'confirm' && answer === 'yes') {
          sayEnvelope(await callBackend('YesIntent', {}));
          setBooking(EMPTY_BOOKING);
          return;
        }
        if (stage === 'confirm' && answer === 'no') {
          sayEnvelope(await callBackend('NoIntent', {}));
          setBooking(EMPTY_BOOKING);
          return;
        }

        // Requirement 13: a clear switch to a different task cancels the
        // pending booking instead of corrupting it with a bad field value.
        const otherIntent = detectIntent(text);
        if (INTERRUPTION_INTENTS.includes(otherIntent)) {
          setBooking(EMPTY_BOOKING);
          const parameters = otherIntent === 'Symptom Check' ? { symptom: text } : {};
          const envelope = await callBackend(otherIntent, parameters);
          // An interruption into Cancel Appointment or Update Appointment
          // starts that flow exactly like its own plain (non-interrupting)
          // entry point below does - read only from
          // context.cancellationStage/updateStage, never from
          // suggestions/prose/message count. Symptom Check and View
          // Appointments are unaffected - neither ever sets either of
          // these.
          if (otherIntent === 'Cancel Appointment') {
            const nextStage = envelope.context?.cancellationStage;
            if (nextStage === 'identifier' || nextStage === 'confirm' || nextStage === 'cancelled') {
              setCancellationStage(nextStage);
            }
          } else if (otherIntent === 'Update Appointment') {
            const nextStage = envelope.context?.updateStage;
            if (['identifier', 'fields', 'confirm', 'updated'].includes(nextStage)) {
              setUpdate({ stage: nextStage, identifier: null });
            }
          }
          sayEnvelope(prefixFirstMessage(envelope, '(Cancelled your in-progress booking.) '));
          return;
        }

        if (stage === 'name') {
          if (!isValidName(text)) {
            sayText("That doesn't look like a name - could you tell me your name?");
            return;
          }
          const next = { ...booking, name: text.trim() };
          setBooking(next);
          sayEnvelope(await callBackend('Book Appointment', bookingParams(next)));
          return;
        }

        // Provider validity is entirely a backend concern
        // (provider_repository.py / availability_service.py) - the
        // frontend has no provider list and no matching rules of its own,
        // so it only guards against an empty reply and forwards whatever
        // the user typed exactly as given (an id, a name, or a number
        // from the backend's displayed list).
        //
        // The attempted choice is sent, but only committed to local state
        // if the backend's response proves it actually advanced past this
        // stage - context.bookingStage is the backend's own structural
        // report of which stage it's still waiting on (see
        // response_model.success_response's docstring), so this never
        // has to infer acceptance from response text or `success` (which
        // only means the request was processed, not that the provider
        // was valid). Checked against the exact expected next stage
        // ('date'), not merely "not 'provider'" - so an unexpected,
        // unknown, or future stage value fails closed (treated as
        // rejected) rather than accidentally counting as acceptance. If
        // the backend is still at 'provider' (rejected), `booking` is
        // left exactly as it was, so the next reply is still correctly
        // treated as another provider attempt - not misread as a date,
        // which is the exact bug this closes.
        if (stage === 'provider') {
          if (!text.trim()) {
            sayText("Please tell me which provider you'd like to see.");
            return;
          }
          const attempted = { ...booking, providerId: text.trim() };
          const envelope = await callBackend('Book Appointment', bookingParams(attempted));
          const reportedStage = envelope.context?.bookingStage;
          const providerAccepted = reportedStage === 'date';
          setBooking(providerAccepted ? attempted : booking);
          sayEnvelope(envelope);
          return;
        }

        if (stage === 'date') {
          const date = parseDate(text);
          if (!date) {
            sayText('I couldn\'t understand that date. Try a format like 2026-12-26, 26-12-2026, or "26 December 2026".');
            return;
          }
          const next = { ...booking, date };
          setBooking(next);
          sayEnvelope(await callBackend('Book Appointment', bookingParams(next)));
          return;
        }

        // Slot validity (does this time exist, is it still free) is
        // entirely a backend concern (availability_service.py) - the
        // frontend never computes or checks availability itself, so it
        // only guards against an empty reply and forwards whatever the
        // user typed exactly as given (an exact HH:MM value, or a number
        // from the backend's displayed slot list - parseTime() is
        // deliberately not used here, since a bare number like "2" is a
        // valid slot choice but not a valid time).
        //
        // Same commit-only-on-confirmed-advance pattern as the provider
        // stage above: the attempted slot is sent, but only kept in local
        // state if context.bookingStage proves it was accepted. Checked
        // against the exact expected next stage ('confirm'), not merely
        // "not 'slot'" - so an unexpected, unknown, or future stage value
        // fails closed (treated as rejected) rather than accidentally
        // counting as acceptance. Otherwise `booking` is left unchanged,
        // so the next reply is still treated as another slot attempt -
        // not misread as a yes/no confirmation reply, which would
        // otherwise leave the user stuck.
        if (stage === 'slot') {
          if (!text.trim()) {
            sayText("Please tell me which time you'd like, or reply with its number from the list.");
            return;
          }
          const attempted = { ...booking, time: text.trim() };
          const envelope = await callBackend('Book Appointment', bookingParams(attempted));
          const reportedStage = envelope.context?.bookingStage;
          const slotAccepted = reportedStage === 'confirm';
          setBooking(slotAccepted ? attempted : booking);
          sayEnvelope(envelope);
          return;
        }

        // stage === 'confirm', but the answer wasn't yes/no/an interruption.
        sayText('Please reply "yes" to confirm the appointment, or "no" to cancel it.');
        return;
      }

      // Cancellation's local state machine: reached only when no booking
      // is in progress (the check above always returns first), so an
      // active booking is never affected by cancellation state and vice
      // versa. Mirrors booking's own "stage truthy -> this reply answers
      // that flow" shape, but with exactly the two stages that need a
      // reply from the user - "cancelled" needs no further input and is
      // simply the value cancellationStage is set to (see below), never
      // branched on here.
      if (cancellationStage === 'confirm') {
        const answer = text.trim().toLowerCase();

        if (answer === 'yes') {
          const envelope = await callBackend('YesIntent', {});
          setCancellationStage(envelope.context?.cancellationStage ?? null);
          sayEnvelope(envelope);
          return;
        }
        if (answer === 'no') {
          const envelope = await callBackend('NoIntent', {});
          setCancellationStage(envelope.context?.cancellationStage ?? null);
          sayEnvelope(envelope);
          return;
        }

        sayText('Please reply "yes" to confirm the cancellation, or "no" to keep the appointment.');
        return;
      }

      if (cancellationStage === 'identifier') {
        if (!text.trim()) {
          sayText("Please tell me the ID or name of the appointment you'd like to cancel.");
          return;
        }

        const trimmed = text.trim();
        const parameters = UUID_PATTERN.test(trimmed) ? { id: trimmed } : { name: trimmed };
        const envelope = await callBackend('Cancel Appointment', parameters);
        setCancellationStage(envelope.context?.cancellationStage ?? null);
        sayEnvelope(envelope);
        return;
      }

      // Update's local state machine: same "reached only when no booking
      // is in progress" placement as cancellation above, and independent
      // of it (booking/cancellation/update are mutually exclusive on the
      // backend - see chatbot_logic.py's PENDING_UPDATE_FILE comment - so
      // in practice at most one of cancellationStage/update.stage is ever
      // non-null at a time).
      if (update.stage === 'confirm') {
        const answer = text.trim().toLowerCase();

        if (answer === 'yes') {
          const envelope = await callBackend('YesIntent', {});
          setUpdate(deriveUpdateState(envelope, update.identifier));
          sayEnvelope(envelope);
          return;
        }
        if (answer === 'no') {
          const envelope = await callBackend('NoIntent', {});
          setUpdate(deriveUpdateState(envelope, update.identifier));
          sayEnvelope(envelope);
          return;
        }

        sayText('Please reply "yes" to confirm the update, or "no" to keep the appointment as is.');
        return;
      }

      if (update.stage === 'fields') {
        // Lightweight routing only, using the SAME date/time parsers
        // booking already uses - never a new parser, never a lookup
        // against appointment data. Backend validation (format, and
        // provider availability) remains authoritative either way; this
        // only decides whether there's anything worth sending yet.
        const date = parseDate(text);
        const time = parseTime(text);

        if (!date && !time) {
          sayText(
            "I didn't catch a new date or time - could you give me a date (e.g. 2026-12-26) "
            + "and/or a time (e.g. 14:00)?"
          );
          return;
        }

        const parameters = { ...update.identifier };
        if (date) parameters.date = date;
        if (time) parameters.time = time;
        const envelope = await callBackend('Update Appointment', parameters);
        setUpdate(deriveUpdateState(envelope, update.identifier));
        sayEnvelope(envelope);
        return;
      }

      if (update.stage === 'identifier') {
        if (!text.trim()) {
          sayText("Please tell me the ID or name of the appointment you'd like to update.");
          return;
        }

        const trimmed = text.trim();
        const identifierParams = UUID_PATTERN.test(trimmed) ? { id: trimmed } : { name: trimmed };
        const envelope = await callBackend('Update Appointment', identifierParams);
        setUpdate(deriveUpdateState(envelope, identifierParams));
        sayEnvelope(envelope);
        return;
      }

      // No booking, cancellation, or update in progress - ordinary
      // single-shot routing.
      const intent = detectIntent(text);
      if (intent === 'Book Appointment') {
        const fields = extractInitialBookingFields(text);
        const next = {
          active: true,
          name: fields.name || null,
          // Never extracted from free text - see
          // extractInitialBookingFields's own docstring in booking.js.
          providerId: null,
          date: fields.date || null,
          time: fields.time || null,
        };
        setBooking(next);
        sayEnvelope(await callBackend('Book Appointment', bookingParams(next)));
      } else {
        // General FAQ is the sole "none confidence" / unclassified fallback
        // in classifyIntent (see conversation/intent.js) - sending the raw
        // text only for that case, and only here, lets the backend's LLM
        // routing (chatbot_logic.py's General FAQ branch) see the actual
        // question without introducing a second intent classifier or
        // changing what's sent for any other intent.
        let parameters = {};
        if (intent === 'Symptom Check') {
          parameters = { symptom: text };
        } else if (intent === 'General FAQ') {
          parameters = { message: text };
        }
        const envelope = await callBackend(intent, parameters);
        if (intent === 'Cancel Appointment') {
          setCancellationStage(envelope.context?.cancellationStage ?? null);
        } else if (intent === 'Update Appointment') {
          setUpdate(deriveUpdateState(envelope, null));
        }
        sayEnvelope(envelope);
      }
    } catch (err) {
      console.error(err);
      sayText('Sorry, an error occurred.');
    } finally {
      setIsTyping(false);
    }
  };

  return { messages, userInput, setUserInput, isTyping, sendMessage };
}

export { useConversation };
