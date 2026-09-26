import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import App from './App';
import { getAppointments } from './api/client';

// getAppointments is mocked so navigating to the Appointments tab never
// makes a real network call in these tests - matching this project's
// existing convention for testing anything that calls into api/client.js
// (see hooks/useConversation.test.js). The other 3 tests below never
// navigate away from the default Chat view, so this has no effect on them.
jest.mock('./api/client', () => ({
  callBackend: jest.fn(),
  getAppointments: jest.fn(),
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
