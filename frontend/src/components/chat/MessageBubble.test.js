import { render, screen } from '@testing-library/react';
import MessageBubble from './MessageBubble';

describe('MessageBubble', () => {
  test('labels a user message distinctly from an assistant message', () => {
    render(<MessageBubble message={{ sender: 'user', text: 'Hello' }} />);
    expect(screen.getByRole('group', { name: /you said/i })).toHaveTextContent('Hello');
  });

  test('renders a structured text message from the assistant', () => {
    render(
      <MessageBubble
        message={{ sender: 'bot', type: 'text', content: { text: 'Hi there' }, suggestions: [] }}
      />
    );
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent('Hi there');
  });

  test('renders a validation_error message using the same presentation as text', () => {
    render(
      <MessageBubble
        message={{
          sender: 'bot',
          type: 'validation_error',
          content: { text: "That doesn't look like a date." },
          suggestions: [],
        }}
      />
    );
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent(
      "That doesn't look like a date."
    );
  });

  test('renders a booking_confirmation message text', () => {
    render(
      <MessageBubble
        message={{
          sender: 'bot',
          type: 'booking_confirmation',
          content: {
            text: 'Your appointment is booked.',
            appointment: { name: 'Sagar', date: '2026-12-26', time: '10:00' },
          },
          suggestions: [],
        }}
      />
    );
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent(
      'Your appointment is booked.'
    );
  });

  test('falls back gracefully for an unknown message type instead of crashing', () => {
    render(
      <MessageBubble message={{ sender: 'bot', type: 'mystery_type', content: {}, suggestions: [] }} />
    );
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent(
      "I received a response I can't display yet."
    );
  });
});
