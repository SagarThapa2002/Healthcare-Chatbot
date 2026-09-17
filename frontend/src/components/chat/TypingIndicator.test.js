import { render, screen } from '@testing-library/react';
import TypingIndicator from './TypingIndicator';

test('announces that the assistant is typing', () => {
  render(<TypingIndicator />);
  expect(screen.getByRole('status')).toHaveTextContent(/assistant is typing/i);
});
