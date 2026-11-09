export type Tab = 'home' | 'deck' | 'ready' | 'library' | 'actions' | 'train' | 'playlists' | 'status' | 'tags' | 'insights';

/** Screens reached from Home and Library rather than from the tab bar. */
export const EXTRA_TABS: Tab[] = ['tags', 'insights'];

const TABS: { id: Tab; label: string; icon: JSX.Element }[] = [
  {
    id: 'home',
    label: 'Home',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 11l8-7 8 7" />
        <path d="M6 9.5V20h12V9.5" />
        <path d="M10 20v-5h4v5" />
      </svg>
    ),
  },
  {
    id: 'deck',
    label: 'Deck',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="5" y="3" width="14" height="18" rx="3" />
        <path d="M2 7v10M22 7v10" />
      </svg>
    ),
  },
  {
    id: 'ready',
    label: 'Ready',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 13l2-8h12l2 8v6H4z" />
        <path d="M4 13h5l1 2h4l1-2h5" />
      </svg>
    ),
  },
  {
    id: 'library',
    label: 'Library',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5 4h4v16H5zM10 4h4v16h-4zM15.5 5l3.8-1 3.2 15.6-3.8 1z" />
      </svg>
    ),
  },
  {
    id: 'actions',
    label: 'Actions',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <rect x="4" y="4" width="16" height="16" rx="4" />
        <path d="M8.5 12.5l2.5 2.5 5-6" />
      </svg>
    ),
  },
  {
    id: 'train',
    label: 'Train',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M2 9l10-5 10 5-10 5z" />
        <path d="M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5" />
      </svg>
    ),
  },
  {
    id: 'playlists',
    label: 'Playlists',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 6h12M4 11h12M4 16h7" />
        <path d="M15 14.5v5.5l5-2.75z" />
      </svg>
    ),
  },
  {
    id: 'status',
    label: 'Status',
    icon: (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
];

export function TabBar({ tab, onTab, readyCount }: { tab: Tab; onTab(t: Tab): void; readyCount: number }) {
  return (
    <nav className="tabbar" aria-label="Sections">
      {TABS.map((t) => (
        <button
          key={t.id}
          className={`tab${tab === t.id ? ' active' : ''}`}
          onClick={() => onTab(t.id)}
          aria-current={tab === t.id ? 'page' : undefined}
          aria-label={t.id === 'ready' && readyCount ? `Ready, ${readyCount} new` : t.label}
        >
          <span className="tab-icon">
            {t.icon}
            {t.id === 'ready' && readyCount > 0 && <span className="badge">{readyCount > 99 ? '99+' : readyCount}</span>}
          </span>
          <span className="tab-label">{t.label}</span>
        </button>
      ))}
    </nav>
  );
}
