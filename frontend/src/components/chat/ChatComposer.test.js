import { render, screen, fireEvent } from '@testing-library/react';
import ChatComposer from './ChatComposer';

describe('ChatComposer', () => {
  test('reports text changes via onChange', () => {
    const handleChange = jest.fn();
    render(<ChatComposer value="" onChange={handleChange} onSubmit={jest.fn()} disabled={false} />);
    fireEvent.change(screen.getByLabelText(/message/i), { target: { value: 'Hi' } });
    expect(handleChange).toHaveBeenCalledWith('Hi');
  });

  test('disables the Send button when the input is empty or whitespace-only', () => {
    render(<ChatComposer value="   " onChange={jest.fn()} onSubmit={jest.fn()} disabled={false} />);
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });

  test('calls onSubmit when Send is clicked with valid input', () => {
    const handleSubmit = jest.fn((e) => e.preventDefault());
    render(<ChatComposer value="Hello" onChange={jest.fn()} onSubmit={handleSubmit} disabled={false} />);
    fireEvent.click(screen.getByRole('button', { name: /send/i }));
    expect(handleSubmit).toHaveBeenCalled();
  });

  test('disables the input and button while a request is pending', () => {
    render(<ChatComposer value="Hello" onChange={jest.fn()} onSubmit={jest.fn()} disabled />);
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });
});
