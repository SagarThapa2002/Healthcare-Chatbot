import { render, screen, fireEvent, within } from '@testing-library/react';
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

  test('renders the error banner directly above the composer, outside the scrolling message list', () => {
    const messages = Array.from({ length: 30 }, (_, i) => (
      { sender: 'bot', type: 'text', content: { text: `Message ${i}` }, suggestions: [] }
    ));
    render(
      <ChatPanel
        messages={messages}
        userInput=""
        setUserInput={jest.fn()}
        isTyping={false}
        sendMessage={jest.fn()}
        error="We couldn't reach the server."
      />
    );
    const alert = screen.getByRole('alert');
    const form = screen.getByRole('textbox').closest('form');
    expect(alert.nextElementSibling).toBe(form);
    expect(alert.parentElement).toBe(form.parentElement);
    expect(within(alert.parentElement).queryAllByRole('group', { name: /assistant said/i })).toHaveLength(0);
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

describe('ChatPanel backend-provided suggestions', () => {
  const CANDIDATES = [
    { id: 'a1b2c3d4-0000-4000-8000-000000000001', label: '2026-10-05 at 09:30', value: 'a1b2c3d4-0000-4000-8000-000000000001' },
    { id: 'a1b2c3d4-0000-4000-8000-000000000002', label: '2026-10-07 at 14:00', value: 'a1b2c3d4-0000-4000-8000-000000000002' },
  ];

  function disambiguationMessage(suggestions = CANDIDATES) {
    return {
      sender: 'bot',
      type: 'text',
      content: { text: 'I found multiple appointments for Sagar. Please tell me the appointment ID:' },
      suggestions,
    };
  }

  function renderPanel(props) {
    return render(
      <ChatPanel userInput="" setUserInput={jest.fn()} isTyping={false} sendMessage={jest.fn()} {...props} />
    );
  }

  test('renders one chip per suggestion on the latest bot message, labelled from suggestion.label', () => {
    renderPanel({ messages: [{ sender: 'user', text: 'cancel for Sagar' }, disambiguationMessage()] });

    const group = screen.getByRole('group', { name: 'Suggested messages' });
    const chips = within(group).getAllByRole('button');
    expect(chips).toHaveLength(2);
    expect(chips.map((chip) => chip.textContent)).toEqual(['2026-10-05 at 09:30', '2026-10-07 at 14:00']);
    // The raw id is the submitted value, never the visible label.
    expect(within(group).queryByText(CANDIDATES[0].value)).not.toBeInTheDocument();
  });

  test('selecting a chip submits suggestion.value through the existing suggestion/send path', () => {
    const sendMessage = jest.fn((e) => e.preventDefault());
    const setUserInput = jest.fn();
    const messages = [disambiguationMessage()];

    const { rerender } = render(
      <ChatPanel messages={messages} userInput="" setUserInput={setUserInput} isTyping={false} sendMessage={sendMessage} />
    );

    fireEvent.click(screen.getByRole('button', { name: '2026-10-07 at 14:00' }));
    expect(setUserInput).toHaveBeenCalledWith(CANDIDATES[1].value);
    expect(sendMessage).not.toHaveBeenCalled();

    // Simulates the parent re-rendering once userInput state updates, as in
    // the starter-chip test above.
    rerender(
      <ChatPanel
        messages={messages}
        userInput={CANDIDATES[1].value}
        setUserInput={setUserInput}
        isTyping={false}
        sendMessage={sendMessage}
      />
    );
    expect(sendMessage).toHaveBeenCalledTimes(1);
  });

  test('suggestions on an older bot message are not rendered once a later message exists', () => {
    renderPanel({
      messages: [
        disambiguationMessage(),
        { sender: 'user', text: CANDIDATES[0].value },
        { sender: 'bot', type: 'text', content: { text: 'Cancel this appointment? (yes/no)' }, suggestions: [] },
      ],
    });

    expect(screen.queryByRole('group', { name: 'Suggested messages' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '2026-10-05 at 09:30' })).not.toBeInTheDocument();
  });

  test("suggestions disappear as soon as the user's reply becomes the latest message", () => {
    renderPanel({ messages: [disambiguationMessage(), { sender: 'user', text: CANDIDATES[0].value }], isTyping: true });

    expect(screen.queryByRole('group', { name: 'Suggested messages' })).not.toBeInTheDocument();
  });

  test('chips are disabled while a reply is being processed (isTyping)', () => {
    renderPanel({ messages: [disambiguationMessage()], isTyping: true });

    const chips = within(screen.getByRole('group', { name: 'Suggested messages' })).getAllByRole('button');
    chips.forEach((chip) => expect(chip).toBeDisabled());
  });

  test('a latest bot message with empty or missing suggestions renders no chip group', () => {
    const { rerender } = renderPanel({ messages: [disambiguationMessage([])] });
    expect(screen.queryByRole('group', { name: 'Suggested messages' })).not.toBeInTheDocument();

    const { suggestions, ...withoutSuggestions } = disambiguationMessage();
    rerender(
      <ChatPanel messages={[withoutSuggestions]} userInput="" setUserInput={jest.fn()} isTyping={false} sendMessage={jest.fn()} />
    );
    expect(screen.queryByRole('group', { name: 'Suggested messages' })).not.toBeInTheDocument();
  });

  test('starter chips still render when there are no messages, and no backend chips appear alongside them', () => {
    renderPanel({ messages: [] });

    const groups = screen.getAllByRole('group', { name: 'Suggested messages' });
    expect(groups).toHaveLength(1);
    expect(within(groups[0]).getByRole('button', { name: 'Book an appointment' })).toBeInTheDocument();
  });
});
