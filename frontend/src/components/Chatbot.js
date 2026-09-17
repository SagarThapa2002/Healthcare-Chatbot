import React, { useState } from 'react';
import './Chatbot.css';

// Simple keyword-based routing for messages that are NOT part of an
// in-progress booking. Not real NLU - see README/notes.
const SYMPTOM_PATTERN = /\b(symptom|headache|fever|pain|cough|dizzy|nausea|sick|hurts|ache)\b/i;

function detectIntent(message) {
  const msg = message.trim().toLowerCase();
  if (msg === 'yes') return 'YesIntent';
  if (msg === 'no') return 'NoIntent';
  if (msg.includes('book')) return 'Book Appointment';
  if (msg.includes('cancel')) return 'Cancel Appointment';
  if (msg.includes('update')) return 'Update Appointment';
  if (msg.includes('view')) return 'View Appointments';
  if (SYMPTOM_PATTERN.test(msg)) return 'Symptom Check';
  return 'General FAQ';
}

// Intents that mean "the user has switched to a different task" while a
// booking is in progress. Deliberately excludes 'Book Appointment' (already
// booking - not a new task) and 'General FAQ' (the default fallback for any
// unparseable text, which should just re-prompt, not cancel the booking).
const INTERRUPTION_INTENTS = ['Symptom Check', 'Cancel Appointment', 'View Appointments', 'Update Appointment'];

// --- date / time parsing -----------------------------------------------

const MONTHS = {
  january: 1, jan: 1, february: 2, feb: 2, march: 3, mar: 3, april: 4, apr: 4,
  may: 5, june: 6, jun: 6, july: 7, jul: 7, august: 8, aug: 8,
  september: 9, sep: 9, sept: 9, october: 10, oct: 10,
  november: 11, nov: 11, december: 12, dec: 12,
};

function pad2(n) {
  return String(n).padStart(2, '0');
}

// Builds an ISO date string, rejecting calendar-invalid dates (e.g. 31 April)
// by round-tripping through a real Date object.
function makeIsoDate(year, month, day) {
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) {
    return null;
  }
  return `${year}-${pad2(month)}-${pad2(day)}`;
}

// Supports YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, and "26 December 2026"
// (with an optional ordinal suffix, e.g. "26th December 2026"). Searches
// within the given text rather than requiring the whole string to be a
// date, so it works both for a dedicated date reply and for a date
// mentioned inside a longer sentence.
function parseDate(text) {
  let m = text.match(/(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return makeIsoDate(+m[1], +m[2], +m[3]);

  m = text.match(/(\d{1,2})[/-](\d{1,2})[/-](\d{4})/);
  if (m) return makeIsoDate(+m[3], +m[2], +m[1]);

  m = text.match(/(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})/i);
  if (m) {
    const month = MONTHS[m[2].toLowerCase()];
    if (month) return makeIsoDate(+m[3], month, +m[1]);
  }

  return null;
}

// Supports 24-hour "10:00"/"10:30", and 12-hour "10am"/"10:30am"/"2pm".
// Same "search within text" approach as parseDate.
function parseTime(text) {
  let m = text.match(/(\d{1,2}):(\d{2})\s*([APap][Mm])?/);
  if (m) {
    let hour = +m[1];
    const minute = +m[2];
    const ampm = m[3] ? m[3].toLowerCase() : null;
    if (minute > 59) return null;
    if (ampm) {
      if (hour < 1 || hour > 12) return null;
      hour = ampm === 'am' ? (hour === 12 ? 0 : hour) : (hour === 12 ? 12 : hour + 12);
    } else if (hour > 23) {
      return null;
    }
    return `${pad2(hour)}:${pad2(minute)}`;
  }

  m = text.match(/(\d{1,2})\s*([APap][Mm])/);
  if (m) {
    let hour = +m[1];
    const ampm = m[2].toLowerCase();
    if (hour < 1 || hour > 12) return null;
    hour = ampm === 'am' ? (hour === 12 ? 0 : hour) : (hour === 12 ? 12 : hour + 12);
    return `${pad2(hour)}:00`;
  }

  return null;
}

// Names aren't validated against a real format - just enough to reject
// obviously-wrong answers (empty, absurdly long, or containing digits).
function isValidName(text) {
  const s = text.trim();
  return s.length > 0 && s.length <= 60 && !/\d/.test(s);
}

// Tries to pull name/date/time all out of one message, e.g.
// "book appointment for Sagar on 26 December 2026 at 10am".
// The name must be capitalized to be distinguishable from surrounding
// words like "on"/"at" - see the report's limitations section.
function extractInitialBookingFields(message) {
  const fields = {};
  const nameMatch = message.match(/(?:for|name is)\s+([A-Z][a-zA-Z'-]*(?:\s+[A-Z][a-zA-Z'-]*)*)/);
  if (nameMatch && isValidName(nameMatch[1])) fields.name = nameMatch[1].trim();
  const date = parseDate(message);
  if (date) fields.date = date;
  const time = parseTime(message);
  if (time) fields.time = time;
  return fields;
}

// --- booking conversation state ------------------------------------------

const EMPTY_BOOKING = { active: false, name: null, date: null, time: null };

// The field currently being collected, derived from what's already known -
// there's no separate "stage" variable that could drift out of sync with
// the actual data.
function bookingStage(booking) {
  if (!booking.active) return null;
  if (!booking.name) return 'name';
  if (!booking.date) return 'date';
  if (!booking.time) return 'time';
  return 'confirm';
}

function bookingParams(booking) {
  const params = {};
  if (booking.name) params.name = booking.name;
  if (booking.date) params.date = booking.date;
  if (booking.time) params.time = booking.time;
  return params;
}

async function callBackend(intent, parameters) {
  const response = await fetch('http://127.0.0.1:5000/webhook/webhook', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ queryResult: { intent: { displayName: intent }, parameters } }),
  });
  const data = await response.json();
  return data.fulfillmentText;
}

function Chatbot() {
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

  return (
    <div className="chat-container">
      <div className="chat-header">Healthcare Chatbot</div>
      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.sender}`}>
            <div className="text">{msg.text}</div>
          </div>
        ))}
        {isTyping && <div className="message bot"><div className="text typing">Bot is typing...</div></div>}
      </div>
      <form className="chat-input" onSubmit={sendMessage}>
        <input
          type="text"
          value={userInput}
          onChange={(e) => setUserInput(e.target.value)}
          placeholder="Type your message..."
        />
        <button type="submit">Send</button>
      </form>
    </div>
  );
}

export default Chatbot;
