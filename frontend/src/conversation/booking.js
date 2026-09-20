import { parseDate, parseTime } from './dateTime';
import { isValidName } from './validation';

const EMPTY_BOOKING = { active: false, name: null, providerId: null, date: null, time: null };

// The field currently being collected, derived from what's already known -
// there's no separate "stage" variable that could drift out of sync with
// the actual data. Phase 6.1 Slice 3 Step 4: inserts 'provider' between
// 'name' and 'date', and renames the final collected field's stage from
// 'time' to 'slot' - the field itself is still stored as `time` (that's
// exactly what the backend's Book Appointment parameters call it), only
// the STAGE label changes, to reflect that its value now comes from the
// backend's calculated-availability slot list, not a freely-typed time.
function bookingStage(booking) {
  if (!booking.active) return null;
  if (!booking.name) return 'name';
  if (!booking.providerId) return 'provider';
  if (!booking.date) return 'date';
  if (!booking.time) return 'slot';
  return 'confirm';
}

function bookingParams(booking) {
  const params = {};
  if (booking.name) params.name = booking.name;
  if (booking.providerId) params.providerId = booking.providerId;
  if (booking.date) params.date = booking.date;
  if (booking.time) params.time = booking.time;
  return params;
}

// Tries to pull name/date/time all out of one message, e.g.
// "book appointment for Sagar on 26 December 2026 at 10am".
// The name must be capitalized to be distinguishable from surrounding
// words like "on"/"at" - see the report's limitations section.
//
// Deliberately never attempts to extract a providerId here: the frontend
// has no provider list or provider-matching rules of its own (the backend
// is the sole authority - see provider_repository.py /
// availability_service.py), so there is no reliable, duplication-free way
// to recognize a provider name inside free text. Provider selection is
// always collected as its own explicit step instead.
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
