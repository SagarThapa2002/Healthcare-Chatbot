import { useEffect, useState } from 'react';
import { getAppointments, getProviders } from '../api/client';
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
// backend/chatbot_logic.py's _handle_yes_intent) - the provider's name,
// specialty, and location are resolved from GET /webhook/providers
// instead (see describeProvider below).
//
// This is the fallback display for when that lookup can't resolve the
// id (the providers request failed, or the id isn't in the list): a pure
// reformat of the id that IS present ("dr-patel" -> "Dr Patel") - never
// invented for a legacy record that has no providerId at all.
function formatProviderId(providerId) {
  return providerId
    .split(/[-_]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(' ');
}

// Builds a providerId -> provider lookup once per load, rather than
// searching the list for every card. Tolerates a non-array response and
// entries without an id by simply leaving them out of the lookup.
function indexProviders(providers) {
  const byId = new Map();
  if (Array.isArray(providers)) {
    providers.forEach((provider) => {
      if (provider && provider.id) byId.set(provider.id, provider);
    });
  }
  return byId;
}

// "Dr. Patel · General Practice · Main Clinic" for a known provider, the
// formatted id otherwise. Only called for a truthy providerId.
function describeProvider(providerId, providersById) {
  const provider = providersById.get(providerId);
  if (!provider || !provider.name) return formatProviderId(providerId);
  return [provider.name, provider.specialty, provider.location].filter(Boolean).join(' · ');
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

function AppointmentCard({ appointment, providersById }) {
  const provider = appointment.providerId
    ? describeProvider(appointment.providerId, providersById)
    : null;

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
  const [providersById, setProvidersById] = useState(() => new Map());

  // Both requests run in parallel. Only the appointments request decides
  // the view's status: provider details are an enhancement, so a failed
  // providers request resolves to [] (formatted-id fallback) rather than
  // showing the error state or blocking the list.
  const load = () => {
    setStatus('loading');
    Promise.all([getAppointments(), getProviders().catch(() => [])])
      .then(([data, providers]) => {
        setAppointments(Array.isArray(data) ? data : []);
        setProvidersById(indexProviders(providers));
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
              <AppointmentCard key={appointment.id ?? `${appointment.name}-${appointment.date}-${appointment.time}-${index}`} appointment={appointment} providersById={providersById} />
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
