import { render, screen, fireEvent } from '@testing-library/react';
import ChatPanel from './ChatPanel';

describe('ChatPanel', () => {
  test('shows the empty state when there are no messages', () => {
    render(
      <ChatPanel messages={[]} userInput="" setUserInput={jest.fn()} isTyping={false} sendMessage={jest.fn()} />
    );
    expect(screen.getByText(/how can i help today/i)).toBeInTheDocument();
  });

  test('renders existing messages instead of the empty state', () => {
    const messages = [
      { sender: 'user', text: 'Hello' },
      { sender: 'bot', type: 'text', content: { text: 'Hi, how can I help?' }, suggestions: [] },
    ];
    render(
      <ChatPanel
        messages={messages}
        userInput=""
        setUserInput={jest.fn()}
        isTyping={false}
        sendMessage={jest.fn()}
      />
    );
    // Use role-based queries here: the latest assistant message is
    // intentionally also mirrored into a hidden aria-live region (see
    // ChatPanel), so a plain getByText would be ambiguous by design.
    expect(screen.getByRole('group', { name: /you said/i })).toHaveTextContent('Hello');
    expect(screen.getByRole('group', { name: /assistant said/i })).toHaveTextContent(
      'Hi, how can I help?'
    );
    expect(screen.queryByText(/how can i help today/i)).not.toBeInTheDocument();
  });

  test('shows the typing indicator while waiting for a response', () => {
    render(
      <ChatPanel messages={[]} userInput="" setUserInput={jest.fn()} isTyping sendMessage={jest.fn()} />
    );
    expect(screen.getByRole('status')).toHaveTextContent(/assistant is typing/i);
  });

  test('shows the error banner when an error is present', () => {
    render(
      <ChatPanel
        messages={[]}
        userInput=""
        setUserInput={jest.fn()}
        isTyping={false}
        sendMessage={jest.fn()}
        error="Sorry, an error occurred."
      />
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Sorry, an error occurred.');
  });

  test('sends a suggestion value through the existing sendMessage flow', () => {
    const sendMessage = jest.fn((e) => e.preventDefault());
    const setUserInput = jest.fn();

    const { rerender } = render(
      <ChatPanel messages={[]} userInput="" setUserInput={setUserInput} isTyping={false} sendMessage={sendMessage} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Book an appointment' }));
    expect(setUserInput).toHaveBeenCalledWith('Book an appointment');
    expect(sendMessage).not.toHaveBeenCalled();

    // Simulates the real parent (Chatbot.js -> useConversation) re-rendering
    // ChatPanel once userInput state actually updates.
    rerender(
      <ChatPanel
        messages={[]}
        userInput="Book an appointment"
        setUserInput={setUserInput}
        isTyping={false}
        sendMessage={sendMessage}
      />
    );

    expect(sendMessage).toHaveBeenCalled();
  });
});
