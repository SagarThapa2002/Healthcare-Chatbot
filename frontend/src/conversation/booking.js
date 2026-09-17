import { parseDate, parseTime } from './dateTime';
import { isValidName } from './validation';

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

export { EMPTY_BOOKING, bookingStage, bookingParams, extractInitialBookingFields };
