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

export { MONTHS, pad2, makeIsoDate, parseDate, parseTime };
