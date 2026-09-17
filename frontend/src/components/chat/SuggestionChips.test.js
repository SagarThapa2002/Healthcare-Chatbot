import { render, screen, fireEvent } from '@testing-library/react';
import SuggestionChips from './SuggestionChips';

test('sends the selected suggestion value', () => {
  const handleSelect = jest.fn();
  const suggestions = [{ id: 'book', label: 'Book an appointment', value: 'Book an appointment' }];
  render(<SuggestionChips suggestions={suggestions} onSelect={handleSelect} />);

  fireEvent.click(screen.getByRole('button', { name: 'Book an appointment' }));

  expect(handleSelect).toHaveBeenCalledWith('Book an appointment');
});

test('renders nothing when there are no suggestions', () => {
  const { container } = render(<SuggestionChips suggestions={[]} onSelect={jest.fn()} />);
  expect(container).toBeEmptyDOMElement();
});
