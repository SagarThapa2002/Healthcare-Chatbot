import { render, screen } from '@testing-library/react';
import ErrorBanner from './ErrorBanner';

describe('ErrorBanner', () => {
  test('renders nothing when there is no error message', () => {
    const { container } = render(<ErrorBanner message={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  test('renders an alert with the error message when present', () => {
    render(<ErrorBanner message="Something went wrong." />);
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.');
  });
});
