// Which screen the app opens on: a chosen tab, the Home launch screen, or the last one used.
import type { Tab } from '../components/TabBar';
import { readJSON, writeJSON } from './storage';

export type StartChoice = Tab | 'last';

const START_KEY = 'vm.startScreen.v1';
const LAST_KEY = 'vm.lastTab.v1';
const TABS: Tab[] = ['home', 'deck', 'ready', 'library', 'actions', 'train', 'playlists', 'status'];

export const START_CHOICES: { value: StartChoice; label: string }[] = [
  { value: 'home', label: 'Home (logo and shortcuts)' },
  { value: 'deck', label: 'Deck' },
  { value: 'ready', label: 'Ready' },
  { value: 'train', label: 'Train' },
  { value: 'actions', label: 'Actions' },
  { value: 'library', label: 'Library' },
  { value: 'status', label: 'Status' },
  { value: 'last', label: 'Where I left off' },
];

const isTab = (v: unknown): v is Tab => typeof v === 'string' && (TABS as string[]).includes(v);

export function readStartChoice(): StartChoice {
  const v = readJSON<unknown>(START_KEY, 'home');
  return v === 'last' || isTab(v) ? v : 'home';
}

export function saveStartChoice(v: StartChoice): void {
  writeJSON(START_KEY, v);
}

export function rememberTab(tab: Tab): void {
  writeJSON(LAST_KEY, tab);
}

/** The tab to open on launch. "Where I left off" falls back to Home the first time. */
export function initialTab(): Tab {
  const choice = readStartChoice();
  if (choice !== 'last') return choice;
  const last = readJSON<unknown>(LAST_KEY, 'home');
  return isTab(last) ? last : 'home';
}
