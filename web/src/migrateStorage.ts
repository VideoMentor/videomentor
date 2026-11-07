// Imported first in main.tsx: runs before any module reads saved preferences.
import { migrateLegacyKeys } from './state/legacyKeys';

try {
  migrateLegacyKeys(window.localStorage, Object.keys(window.localStorage));
} catch {
  // Storage blocked (private mode): nothing to carry over.
}
