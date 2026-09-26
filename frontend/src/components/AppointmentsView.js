import { useEffect, useState } from 'react';
import { getAppointments } from '../api/client';
import ErrorBanner from './chat/ErrorBanner';

// Appointment records are never deleted, only status-flagged (see
// backend/chatbot_logic.py's _is_active) - a missing `status` still
// counts as active (true for every legacy record), and only an explicit
// "cancelled" excludes one from this view. Mirrors
// _handle_view_appointments' own filtering exactly, so the chat-based
// "view my appointments" answer and this tab never disagree.
function isActive(appointment) {
  return appointment.status !== 'cancelled';
}

// Appointments only ever store an opaque providerId (see
// backend/chatbot_logic.py's _handle_yes_intent) - there is no provider
// name field on the record, and no GET /webhook/providers endpoint to
// resolve one. This is a pure display reformat of the id that IS present
// ("dr-patel" -> "Dr Patel") - never a lookup, and never invented for a
// legacy record that has no providerId at all (see the `provider &&`
// guard below, where this is only ever called on a truthy id).
function formatProviderId(providerId) {
  return providerId
    .split(/[-_]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(' ');
}

function LoadingState() {
  return (
    <div role="status" className="flex flex-col items-center gap-3 px-4 py-10 text-center">
      <span className="sr-only">Loading appointments</span>
      <span
        aria-hidden="true"
        className="flex items-center gap-1 rounded-lg border border-border bg-surface px-3 py-2.5"
      >
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted motion-reduce:animate-none" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:150ms] motion-reduce:animate-none" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:300ms] motion-reduce:animate-none" />
      </span>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-border bg-surface p-6 text-center">
      <p className="text-sm text-muted">You don't have any upcoming appointments.</p>
    </div>
  );
}

function AppointmentCard({ appointment }) {
  const provider = appointment.providerId ? formatProviderId(appointment.providerId) : null;

  return (
    <li className="rounded-lg border border-border bg-surface p-4">
      <p className="font-semibold text-text">{appointment.name}</p>
      <p className="mt-1 text-sm text-muted">
        {appointment.date} at {appointment.time}
      </p>
      {provider && <p className="mt-1 text-sm text-muted">Provider: {provider}</p>}
      {appointment.id && <p className="mt-1 text-xs text-muted">ID: {appointment.id}</p>}
    </li>
  );
}

function AppointmentsView() {
  const [status, setStatus] = useState('loading'); // 'loading' | 'error' | 'ready'
  const [appointments, setAppointments] = useState([]);

  const load = () => {
    setStatus('loading');
    getAppointments()
      .then((data) => {
        setAppointments(Array.isArray(data) ? data : []);
        setStatus('ready');
      })
      .catch(() => {
        setStatus('error');
      });
  };

  useEffect(load, []);

  const activeAppointments = appointments.filter(isActive);

  return (
    <section aria-label="Appointments" className="flex flex-col gap-4">
      <h2 className="text-base font-semibold text-text">Your Appointments</h2>

      {status === 'loading' && <LoadingState />}

      {status === 'error' && (
        <div>
          <ErrorBanner message="Sorry, we couldn't load your appointments right now." />
          <button
            type="button"
            onClick={load}
            className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text transition-colors hover:border-primary hover:text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            Retry
          </button>
        </div>
      )}

      {status === 'ready' && (
        activeAppointments.length === 0 ? (
          <EmptyState />
        ) : (
          <ul className="flex flex-col gap-3">
            {activeAppointments.map((appointment, index) => (
              <AppointmentCard key={appointment.id ?? `${appointment.name}-${appointment.date}-${appointment.time}-${index}`} appointment={appointment} />
            ))}
          </ul>
        )
      )}

      <p className="text-sm text-muted">
        To book, update, or cancel an appointment, chat with the assistant on the Chat tab.
      </p>
    </section>
  );
}

export default AppointmentsView;
