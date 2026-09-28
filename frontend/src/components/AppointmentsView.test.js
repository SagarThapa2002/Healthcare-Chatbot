import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import AppointmentsView from './AppointmentsView';
import { getAppointments, getProviders } from '../api/client';

// getAppointments/getProviders (the network/JSON boundary) are mocked entirely, matching
// this project's existing convention for testing components/hooks that
// call into api/client.js (see useConversation.test.js) - these tests
// never touch the network and don't need a real backend running.
jest.mock('../api/client', () => ({
  getAppointments: jest.fn(),
  getProviders: jest.fn(),
}));

const PROVIDERS = [
  { id: 'dr-patel', name: 'Dr. Patel', specialty: 'General Practice', location: 'Main Clinic' },
  { id: 'dr-okafor', name: 'Dr. Okafor', specialty: 'Dermatology', location: 'North Clinic' },
];

describe('AppointmentsView', () => {
  beforeEach(() => {
    getAppointments.mockReset();
    getProviders.mockReset();
    // Default: no provider details, so tests that don't care about the
    // lookup exercise the formatted-id fallback, exactly as before.
    getProviders.mockResolvedValue([]);
  });

  test('renders the Appointments region and heading', async () => {
    getAppointments.mockResolvedValue([]);
    render(<AppointmentsView />);

    expect(screen.getByRole('region', { name: 'Appointments' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Your Appointments' })).toBeInTheDocument();

    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(1));
  });

  test('requests appointments through the API client on mount', async () => {
    getAppointments.mockResolvedValue([]);
    render(<AppointmentsView />);

    await waitFor(() => expect(getAppointments).toHaveBeenCalledTimes(1));
  });

  test('shows an accessible loading state while the request is pending', async () => {
    let resolveRequest;
    getAppointments.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve; }));
    render(<AppointmentsView />);

    expect(screen.getByRole('status')).toBeInTheDocument();

    resolveRequest([]);
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  test('renders a successful appointment list with date, time, provider, and id', async () => {
    getAppointments.mockResolvedValue([
      { id: 'abc-123', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
    ]);
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByText('Sagar')).toBeInTheDocument());
    expect(screen.getByText('2026-12-28 at 09:00')).toBeInTheDocument();
    expect(screen.getByText('Provider: Dr Patel')).toBeInTheDocument();
    expect(screen.getByText('ID: abc-123')).toBeInTheDocument();
  });

  test('shows a clear empty state when there are no active appointments', async () => {
    getAppointments.mockResolvedValue([]);
    render(<AppointmentsView />);

    await waitFor(() =>
      expect(screen.getByText("You don't have any upcoming appointments.")).toBeInTheDocument()
    );
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  test('shows a calm error state, never a raw exception, when the request fails', async () => {
    getAppointments.mockRejectedValue(new Error('Network error: ECONNREFUSED at 127.0.0.1:5000'));
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent("Sorry, we couldn't load your appointments right now.");
    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  test('retry re-requests appointments and can recover into a successful list', async () => {
    getAppointments.mockRejectedValueOnce(new Error('boom'));
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(getAppointments).toHaveBeenCalledTimes(1);

    getAppointments.mockResolvedValueOnce([
      { id: 'xyz-9', name: 'Sagar', date: '2026-12-30', time: '14:00' },
    ]);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getByText('Sagar')).toBeInTheDocument());
    expect(getAppointments).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  test('cancelled appointments are excluded from the active list', async () => {
    getAppointments.mockResolvedValue([
      { id: '1', name: 'Active One', date: '2026-12-28', time: '09:00', status: 'booked' },
      { id: '2', name: 'Cancelled One', date: '2026-12-29', time: '10:00', status: 'cancelled' },
    ]);
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByText('Active One')).toBeInTheDocument());
    expect(screen.queryByText('Cancelled One')).not.toBeInTheDocument();
  });

  test('a legacy appointment with no providerId renders without fabricated provider text', async () => {
    getAppointments.mockResolvedValue([
      { name: 'sagar', date: '2026-09-18', time: '10:00' },
    ]);
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByText('sagar')).toBeInTheDocument());
    expect(screen.getByText('2026-09-18 at 10:00')).toBeInTheDocument();
    expect(screen.queryByText(/Provider:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ID:/)).not.toBeInTheDocument();
  });

  test('a missing status field still counts as active (legacy convention, matches backend _is_active)', async () => {
    getAppointments.mockResolvedValue([
      { name: 'sagar', date: '2026-09-18', time: '10:00' },
    ]);
    render(<AppointmentsView />);

    await waitFor(() => expect(screen.getByText('sagar')).toBeInTheDocument());
  });

  describe('provider details', () => {
    test('shows the provider name, specialty, and location for a known providerId', async () => {
      getAppointments.mockResolvedValue([
        { id: 'a1', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
        { id: 'a2', name: 'Alex', date: '2026-12-29', time: '11:00', providerId: 'dr-okafor' },
      ]);
      getProviders.mockResolvedValue(PROVIDERS);
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('Sagar')).toBeInTheDocument());
      expect(screen.getByText('Provider: Dr. Patel · General Practice · Main Clinic')).toBeInTheDocument();
      expect(screen.getByText('Provider: Dr. Okafor · Dermatology · North Clinic')).toBeInTheDocument();
    });

    test('falls back to the formatted id, with no error state, when the providers request fails', async () => {
      getAppointments.mockResolvedValue([
        { id: 'a1', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
      ]);
      getProviders.mockRejectedValue(new Error('Failed to load providers (status 500)'));
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('Sagar')).toBeInTheDocument());
      expect(screen.getByText('Provider: Dr Patel')).toBeInTheDocument();
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
    });

    test('falls back to the formatted id for a providerId that is not in the providers list', async () => {
      getAppointments.mockResolvedValue([
        { id: 'a1', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-unknown' },
      ]);
      getProviders.mockResolvedValue(PROVIDERS);
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('Sagar')).toBeInTheDocument());
      expect(screen.getByText('Provider: Dr Unknown')).toBeInTheDocument();
    });

    test('a legacy appointment with no providerId still shows no provider line when providers load', async () => {
      getAppointments.mockResolvedValue([
        { name: 'sagar', date: '2026-09-18', time: '10:00' },
      ]);
      getProviders.mockResolvedValue(PROVIDERS);
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('sagar')).toBeInTheDocument());
      expect(screen.queryByText(/Provider:/)).not.toBeInTheDocument();
    });

    test('tolerates a non-array providers response by falling back to the formatted id', async () => {
      getAppointments.mockResolvedValue([
        { id: 'a1', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
      ]);
      getProviders.mockResolvedValue({ unexpected: true });
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('Provider: Dr Patel')).toBeInTheDocument());
    });

    test('requests providers once per load, not once per appointment', async () => {
      getAppointments.mockResolvedValue([
        { id: 'a1', name: 'One', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
        { id: 'a2', name: 'Two', date: '2026-12-29', time: '10:00', providerId: 'dr-patel' },
        { id: 'a3', name: 'Three', date: '2026-12-30', time: '11:00', providerId: 'dr-okafor' },
      ]);
      getProviders.mockResolvedValue(PROVIDERS);
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByText('Three')).toBeInTheDocument());
      expect(getProviders).toHaveBeenCalledTimes(1);
    });

    test('an appointments failure still shows the error state, and retry reloads both', async () => {
      getAppointments.mockRejectedValueOnce(new Error('boom'));
      getProviders.mockResolvedValue(PROVIDERS);
      render(<AppointmentsView />);

      await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
      expect(getProviders).toHaveBeenCalledTimes(1);

      getAppointments.mockResolvedValueOnce([
        { id: 'a1', name: 'Sagar', date: '2026-12-28', time: '09:00', providerId: 'dr-patel' },
      ]);
      fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

      await waitFor(() =>
        expect(screen.getByText('Provider: Dr. Patel · General Practice · Main Clinic')).toBeInTheDocument()
      );
      expect(getAppointments).toHaveBeenCalledTimes(2);
      expect(getProviders).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
  });
});
