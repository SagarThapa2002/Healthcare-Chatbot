import { useState } from 'react';
import { detectIntent, INTERRUPTION_INTENTS } from '../conversation/intent';
import { parseDate } from '../conversation/dateTime';
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

function useConversation() {
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [booking, setBooking] = useState(EMPTY_BOOKING);

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

      // No booking in progress - ordinary single-shot routing.
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
        sayEnvelope(await callBackend(intent, parameters));
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
