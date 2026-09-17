// Names aren't validated against a real format - just enough to reject
// obviously-wrong answers (empty, absurdly long, or containing digits).
function isValidName(text) {
  const s = text.trim();
  return s.length > 0 && s.length <= 60 && !/\d/.test(s);
}

export { isValidName };
