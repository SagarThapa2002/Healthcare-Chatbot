import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';
import { callBackend, getAppointments, getProviders, startConversation } from './api/client';

// getAppointments/getProviders are mocked so navigating to the Appointments tab never
// makes a real network call in these tests - matching this project's
// existing convention for testing anything that calls into api/client.js
// (see hooks/useConversation.test.js). The other 3 tests below never
// navigate away from the default Chat view, so this has no effect on them.
jest.mock('./api/client', () => ({
  callBackend: jest.fn(),
  startConversation: jest.fn(),
  getAppointments: jest.fn(),
  getProviders: jest.fn(),
}));

describe('App', () => {
  test('renders the Healthcare Chatbot branding', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /healthcare chatbot/i })).toBeInTheDocument();
  });

  test('renders the main navigation with a Chat entry', () => {
    render(<App />);
    expect(screen.getByRole('navigation', { name: /main/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Chat' })).toBeInTheDocument();
  });

  test('shows Chat as the active view by default', () => {
    render(<App />);
    const chatTab = screen.getByRole('button', { name: 'Chat' });
    expect(chatTab).toHaveAttribute('aria-current', 'page');
    // The chatbot's own composer should be rendered since Chat is the default view.
    expect(screen.getByPlaceholderText(/type your message/i)).toBeInTheDocument();
  });
});

describe('App navigation (Appointments, About, and back to Chat)', () => {
  beforeEach(() => {
    getAppointments.mockReset();
    getAppointments.mockResolvedValue([]);
    getProviders.mockReset();
    getProviders.mockResolvedValue([]);
  });

  test('navigating to Appointments renders the real Appointments view and requests data via the API client', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: 'Appointments' }));

    expect(screen.getByRole('heading', { name: 'Your Appointments' })).toBeInTheDocument();
    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(1));
    // No longer a placeholder: the "Coming soon" badge and old placeholder
    // copy must both be gone.
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });

  test('existing About navigation still works', () => {
    render(<App />);

    // The About tab's accessible name includes its "Preview" badge text
    // (see Navigation.js), so this matches on the label prefix rather
    // than the exact full string.
    fireEvent.click(screen.getByRole('button', { name: /^about \/ help/i }));

    expect(screen.getByRole('heading', { name: 'About this prototype' })).toBeInTheDocument();
  });

  test('existing Chat navigation still works after visiting other tabs', async () => {
    render(<App />);

    fireEvent.click(screen.getByRole('button', { name: 'Appointments' }));
    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: /^about \/ help/i }));
    expect(screen.getByRole('heading', { name: 'About this prototype' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    expect(screen.getByPlaceholderText(/type your message/i)).toBeInTheDocument();
  });
});

// Chat stays mounted (hidden) while another tab is active, so its
// conversation, in-progress flows and session survive tab switches.
describe('Chat conversation survives tab switches', () => {
  function envelope(text, context = {}) {
    return {
      success: true,
      error: null,
      messages: [{ type: 'text', content: { text }, suggestions: [] }],
      context: { intent: 'x', ...context },
      meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
    };
  }

  async function say(value) {
    const input = screen.getByPlaceholderText(/type your message/i);
    await waitFor(() => expect(input).not.toBeDisabled());
    fireEvent.change(input, { target: { value } });
    fireEvent.submit(input.closest('form'));
    await waitFor(() => expect(input).not.toBeDisabled());
  }

  // Message bubbles only - the newest reply is also mirrored into the
  // screen-reader live region, which these checks are not about.
  const bubble = (text, who = 'Assistant said') => screen.getByText(text, { selector: `[aria-label="${who}"]` });

  async function visitAppointmentsAndReturn() {
    fireEvent.click(screen.getByRole('button', { name: 'Appointments' }));
    expect(await screen.findByRole('heading', { name: 'Your Appointments' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
  }

  beforeEach(() => {
    callBackend.mockReset();
    startConversation.mockClear();
    getAppointments.mockReset();
    getAppointments.mockResolvedValue([]);
    getProviders.mockReset();
    getProviders.mockResolvedValue([]);
  });

  test('a sent message and its reply are still shown after Chat → Appointments → Chat', async () => {
    callBackend.mockResolvedValueOnce(envelope('A balanced diet includes a variety of foods.'));
    render(<App />);
    await say('What is a balanced diet?');
    expect(bubble('A balanced diet includes a variety of foods.')).toBeVisible();

    await visitAppointmentsAndReturn();

    expect(bubble('What is a balanced diet?', 'You said')).toBeVisible();
    expect(bubble('A balanced diet includes a variety of foods.')).toBeVisible();
  });

  test('an in-progress booking continues after a tab switch instead of restarting', async () => {
    callBackend
      .mockResolvedValueOnce(envelope('Sure, may I have your name?', { bookingStage: 'name' }))
      .mockResolvedValueOnce(envelope('Which provider would you like to see?', { bookingStage: 'provider' }))
      .mockResolvedValueOnce(envelope('What date would you like?', { bookingStage: 'date' }))
      .mockResolvedValueOnce(envelope('Here are the available times.', { bookingStage: 'slot' }));
    render(<App />);
    await say('book an appointment');
    await say('Sagar');
    await say('dr-patel');

    await visitAppointmentsAndReturn();
    await say('2026-12-28');

    expect(callBackend).toHaveBeenLastCalledWith(
      'Book Appointment', { name: 'Sagar', providerId: 'dr-patel', date: '2026-12-28' }
    );
    expect(callBackend).toHaveBeenCalledTimes(4);
  });

  test('the conversation session is started once across several tab switches', async () => {
    render(<App />);
    expect(startConversation).toHaveBeenCalledTimes(1);

    await visitAppointmentsAndReturn();
    fireEvent.click(screen.getByRole('button', { name: /^about \/ help/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    await visitAppointmentsAndReturn();

    expect(startConversation).toHaveBeenCalledTimes(1);
  });

  test('Chat is hidden while another tab is active and visible again on return', async () => {
    render(<App />);
    const input = screen.getByPlaceholderText(/type your message/i);
    expect(input).toBeVisible();
    expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Appointments' }));
    await screen.findByRole('heading', { name: 'Your Appointments' });
    expect(input).not.toBeVisible();
    expect(screen.queryByRole('region', { name: 'Chat' })).not.toBeInTheDocument(); // out of the accessibility tree
    expect(input).toBeInTheDocument(); // still mounted
    // jsdom has no Tailwind CSS, so check directly that no display utility
    // (which would override [hidden]) sits on the hidden wrapper.
    expect(input.closest('[hidden]')).not.toHaveClass('flex');

    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    expect(input).toBeVisible();
    expect(screen.getByRole('region', { name: 'Chat' })).toBeInTheDocument();
  });

  test('Appointments still re-fetches its data on every visit', async () => {
    render(<App />);
    await visitAppointmentsAndReturn();
    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(1));
    await visitAppointmentsAndReturn();
    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(2));
  });

  test('About still works while the conversation is kept', async () => {
    callBackend.mockResolvedValueOnce(envelope('Hello there.'));
    render(<App />);
    await say('hi');

    fireEvent.click(screen.getByRole('button', { name: /^about \/ help/i }));
    expect(screen.getByRole('heading', { name: 'About this prototype' })).toBeInTheDocument();
    expect(bubble('Hello there.')).not.toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Chat' }));
    expect(screen.queryByRole('heading', { name: 'About this prototype' })).not.toBeInTheDocument();
    expect(bubble('Hello there.')).toBeVisible();
  });
});
