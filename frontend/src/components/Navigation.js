const NAV_ITEMS = [
  { id: 'chat', label: 'Chat' },
  { id: 'appointments', label: 'Appointments' },
  { id: 'about', label: 'About / Help', badge: 'Preview' },
];

function Navigation({ activeView, onNavigate }) {
  return (
    <nav aria-label="Main" className="border-b border-border bg-surface">
      <div className="mx-auto w-full max-w-4xl px-4 sm:px-6 lg:px-8">
        <ul className="-mb-px flex gap-1 overflow-x-auto">
          {NAV_ITEMS.map((item) => {
            const isActive = activeView === item.id;
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onNavigate(item.id)}
                  aria-current={isActive ? 'page' : undefined}
                  className={[
                    'flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm transition-colors',
                    'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary',
                    isActive
                      ? 'border-primary font-semibold text-primary'
                      : 'border-transparent font-medium text-muted hover:border-border hover:text-text',
                  ].join(' ')}
                >
                  {item.label}
                  {item.badge && (
                    <span className="rounded-full border border-border bg-background px-2 py-0.5 text-xs font-normal text-muted">
                      {item.badge}
                    </span>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </nav>
  );
}

export default Navigation;
