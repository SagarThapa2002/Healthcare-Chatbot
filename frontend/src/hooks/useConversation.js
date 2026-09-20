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

        if (stage === 'time') {
          const time = parseTime(text);
          if (!time) {
            sayText('I couldn\'t understand that time. Try a format like 10:00, 10:30am, or 2pm.');
            return;
          }
          const next = { ...booking, time };
          setBooking(next);
          sayEnvelope(await callBackend('Book Appointment', bookingParams(next)));
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
        const next = { active: true, name: fields.name || null, date: fields.date || null, time: fields.time || null };
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
