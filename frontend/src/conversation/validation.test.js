import { isValidName } from './validation';

describe('isValidName', () => {
  test('accepts a normal name', () => {
    expect(isValidName('Sagar Thapa')).toBe(true);
  });

  test('rejects an empty/whitespace-only string', () => {
    expect(isValidName('   ')).toBe(false);
  });

  test('rejects names containing digits', () => {
    expect(isValidName('Sagar2')).toBe(false);
  });

  test('rejects names over 60 characters', () => {
    expect(isValidName('a'.repeat(61))).toBe(false);
  });

  test('accepts a name at exactly the 60 character limit', () => {
    expect(isValidName('a'.repeat(60))).toBe(true);
  });
});
