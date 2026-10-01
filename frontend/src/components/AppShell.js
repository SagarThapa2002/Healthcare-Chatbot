import { useState } from 'react';
import Header from './Header';
import Navigation from './Navigation';
import SafetyBanner from './SafetyBanner';
import Chatbot from './Chatbot';
import AppointmentsView from './AppointmentsView';
import AboutPlaceholder from './AboutPlaceholder';

// Views other than Chat mount only while active, so Appointments re-fetches
// its data on every visit.
const OTHER_VIEWS = {
  appointments: AppointmentsView,
  about: AboutPlaceholder,
};

function AppShell() {
  const [activeView, setActiveView] = useState('chat');
  const OtherView = OTHER_VIEWS[activeView];
  const chatActive = !OtherView;

  return (
    <div className="flex min-h-screen flex-col bg-background font-sans text-text">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to main content
      </a>
      <Header />
      <Navigation activeView={activeView} onNavigate={setActiveView} />
      <main id="main-content" className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-4 py-6 sm:px-6 lg:px-8">
        {/* Chat stays mounted for the page's lifetime - hidden, not unmounted,
            while another tab is active - so its conversation, in-progress
            booking/cancellation/update and session survive tab switches.
            The `hidden` attribute removes it from view and the accessibility
            tree; the flex classes are only applied while visible, because a
            display utility would otherwise override [hidden]. */}
        <div hidden={!chatActive} className={chatActive ? 'flex flex-1 flex-col' : undefined}>
          <Chatbot />
        </div>
        {OtherView && <OtherView />}
      </main>
      <SafetyBanner />
    </div>
  );
}

export default AppShell;
