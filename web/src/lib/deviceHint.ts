// iPad Safari presents itself to websites as a Mac, so the server can't tell them apart.
// A Mac browser with a multi-touch screen is an iPad: say so once, so Status > Paired
// devices labels it correctly.
import { api } from './api';

export function looksLikeIpad(nav: { userAgent: string; maxTouchPoints?: number }): boolean {
  return /Macintosh/.test(nav.userAgent) && (nav.maxTouchPoints ?? 0) > 1;
}

let sent = false;

export function reportDevice(): void {
  if (sent || typeof navigator === 'undefined' || !looksLikeIpad(navigator)) return;
  sent = true;
  api.deviceHint('iPad').catch(() => {
    sent = false; // try again the next time the app reaches the server
  });
}
