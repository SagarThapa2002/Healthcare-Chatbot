import { act, renderHook } from '@testing-library/react';
import { useConversation } from './useConversation';
import { callBackend } from '../api/client';

// Only the payload construction is under test here - callBackend itself
// (network/normalization) is mocked entirely, so these tests never touch
// the network and don't need a real backend running.
jest.mock('../api/client', () => ({
  callBackend: jest.fn(),
}));

function fakeEnvelope() {
  return {
    success: true,
    error: null,
    messages: [{ type: 'text', content: { text: 'ok' }, suggestions: [] }],
    context: null,
    meta: { schemaVersion: '1.0', requestId: null, timestamp: null },
  };
}

async function submitMessage(result, text) {
  act(() => {
    result.current.setUserInput(text);
  });
  await act(async () => {
    await result.current.sendMessage({ preventDefault: () => {} });
  });
}

describe('useConversation payload construction (frontend-to-backend wiring)', () => {
  beforeEach(() => {
    callBackend.mockReset();
    callBackend.mockResolvedValue(fakeEnvelope());
  });

  test('sends parameters.message for an unclassified General FAQ question', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'What is a balanced diet?');

    expect(callBackend).toHaveBeenCalledWith('General FAQ', { message: 'What is a balanced diet?' });
  });

  test('still sends the existing parameters.symptom shape for a symptom message', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'I have a headache');

    expect(callBackend).toHaveBeenCalledWith('Symptom Check', { symptom: 'I have a headache' });
  });

  test('Book Appointment payload is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'book an appointment');

    expect(callBackend).toHaveBeenCalledWith('Book Appointment', {});
  });

  test('Cancel Appointment payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'cancel my appointment');

    expect(callBackend).toHaveBeenCalledWith('Cancel Appointment', {});
  });

  test('Update Appointment payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'update my appointment');

    expect(callBackend).toHaveBeenCalledWith('Update Appointment', {});
  });

  test('View Appointments payload is unchanged (no message field added)', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'view my appointments');

    expect(callBackend).toHaveBeenCalledWith('View Appointments', {});
  });

  test('a bare "yes" with no booking in progress is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'yes');

    expect(callBackend).toHaveBeenCalledWith('YesIntent', {});
  });

  test('a bare "no" with no booking in progress is unchanged', async () => {
    const { result } = renderHook(() => useConversation());

    await submitMessage(result, 'no');

    expect(callBackend).toHaveBeenCalledWith('NoIntent', {});
  });
});
