import { useState } from 'react';
import Header from './Header';
import Navigation from './Navigation';
import SafetyBanner from './SafetyBanner';
import Chatbot from './Chatbot';
import AppointmentsPlaceholder from './AppointmentsPlaceholder';
import AboutPlaceholder from './AboutPlaceholder';

const VIEWS = {
  chat: Chatbot,
  appointments: AppointmentsPlaceholder,
  about: AboutPlaceholder,
};

function AppShell() {
  const [activeView, setActiveView] = useState('chat');
  const ActiveView = VIEWS[activeView] || Chatbot;

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
      <main id="main-content" className="mx-auto w-full max-w-4xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
        <ActiveView />
      </main>
      <SafetyBanner />
    </div>
  );
}

export default AppShell;
