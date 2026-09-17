import { render, screen } from '@testing-library/react';
import MessageBubble from './MessageBubble';

describe('MessageBubble', () => {
  test('labels a user message distinctly from an assistant message', () => {
    render(<MessageBubble message={{ sender: 'user', text: 'Hello' }} />);
    expect(screen.getByRole('group', { name: /you said/i })).toHaveTextContent('Hello');
  });

  test('labels an assistant message distinctly from a user message', () => {
    render(<MessageBubble message={{ sender: 'bot', text: 'Hi there' }} />);
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent('Hi there');
  });
});
