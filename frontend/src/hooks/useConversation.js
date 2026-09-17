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

function useConversation() {
  const [messages, setMessages] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [booking, setBooking] = useState(EMPTY_BOOKING);

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!userInput.trim()) return;

    const text = userInput;
    setMessages(prev => [...prev, { sender: 'user', text }]);
    setUserInput('');
    setIsTyping(true);

    const say = (botText) => setMessages(prev => [...prev, { sender: 'bot', text: botText }]);

    try {
      const stage = bookingStage(booking);

      if (stage) {
        const answer = text.trim().toLowerCase();

        if (stage === 'confirm' && answer === 'yes') {
          say(await callBackend('YesIntent', {}));
          setBooking(EMPTY_BOOKING);
          return;
        }
        if (stage === 'confirm' && answer === 'no') {
          say(await callBackend('NoIntent', {}));
          setBooking(EMPTY_BOOKING);
          return;
        }

        // Requirement 13: a clear switch to a different task cancels the
        // pending booking instead of corrupting it with a bad field value.
        const otherIntent = detectIntent(text);
        if (INTERRUPTION_INTENTS.includes(otherIntent)) {
          setBooking(EMPTY_BOOKING);
          const parameters = otherIntent === 'Symptom Check' ? { symptom: text } : {};
          const reply = await callBackend(otherIntent, parameters);
          say(`(Cancelled your in-progress booking.) ${reply}`);
          return;
        }

        if (stage === 'name') {
          if (!isValidName(text)) {
            say("That doesn't look like a name - could you tell me your name?");
            return;
          }
          const next = { ...booking, name: text.trim() };
          setBooking(next);
          say(await callBackend('Book Appointment', bookingParams(next)));
          return;
        }

        if (stage === 'date') {
          const date = parseDate(text);
          if (!date) {
            say('I couldn\'t understand that date. Try a format like 2026-12-26, 26-12-2026, or "26 December 2026".');
            return;
          }
          const next = { ...booking, date };
          setBooking(next);
          say(await callBackend('Book Appointment', bookingParams(next)));
          return;
        }

        if (stage === 'time') {
          const time = parseTime(text);
          if (!time) {
            say('I couldn\'t understand that time. Try a format like 10:00, 10:30am, or 2pm.');
            return;
          }
          const next = { ...booking, time };
          setBooking(next);
          say(await callBackend('Book Appointment', bookingParams(next)));
          return;
        }

        // stage === 'confirm', but the answer wasn't yes/no/an interruption.
        say('Please reply "yes" to confirm the appointment, or "no" to cancel it.');
        return;
      }

      // No booking in progress - ordinary single-shot routing.
      const intent = detectIntent(text);
      if (intent === 'Book Appointment') {
        const fields = extractInitialBookingFields(text);
        const next = { active: true, name: fields.name || null, date: fields.date || null, time: fields.time || null };
        setBooking(next);
        say(await callBackend('Book Appointment', bookingParams(next)));
      } else {
        const parameters = intent === 'Symptom Check' ? { symptom: text } : {};
        say(await callBackend(intent, parameters));
      }
    } catch (err) {
      console.error(err);
      say('Sorry, an error occurred.');
    } finally {
      setIsTyping(false);
    }
  };

  return { messages, userInput, setUserInput, isTyping, sendMessage };
}

export { useConversation };
