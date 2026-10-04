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

  test('Enter submits; Shift+Enter does not (it is left for a new line)', () => {
    const handleSubmit = jest.fn((e) => e.preventDefault());
    render(<ChatComposer value="Hello" onChange={jest.fn()} onSubmit={handleSubmit} disabled={false} />);
    const textarea = screen.getByLabelText(/message/i);

    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(handleSubmit).not.toHaveBeenCalled();

    fireEvent.keyDown(textarea, { key: 'Enter' });
    expect(handleSubmit).toHaveBeenCalledTimes(1);
  });

  test('Enter does not submit empty input or while a request is pending', () => {
    const handleSubmit = jest.fn();
    const { rerender } = render(<ChatComposer value="   " onChange={jest.fn()} onSubmit={handleSubmit} disabled={false} />);
    fireEvent.keyDown(screen.getByLabelText(/message/i), { key: 'Enter' });
    rerender(<ChatComposer value="Hello" onChange={jest.fn()} onSubmit={handleSubmit} disabled />);
    fireEvent.keyDown(screen.getByLabelText(/message/i), { key: 'Enter' });
    expect(handleSubmit).not.toHaveBeenCalled();
  });

  test('passes inputRef to the textarea', () => {
    const inputRef = { current: null };
    render(<ChatComposer value="" onChange={jest.fn()} onSubmit={jest.fn()} disabled={false} inputRef={inputRef} />);
    expect(inputRef.current).toBe(screen.getByLabelText(/message/i));
  });

  test('disables the input and button while a request is pending', () => {
    render(<ChatComposer value="Hello" onChange={jest.fn()} onSubmit={jest.fn()} disabled />);
    expect(screen.getByLabelText(/message/i)).toBeDisabled();
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled();
  });
});
