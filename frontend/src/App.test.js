import { render, screen } from '@testing-library/react';
import App from './App';

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
