// Recognize a sync that failed because the app's saved YouTube login went stale.
// YouTube answers a signed-out request for a private list (Watch Later, Liked, private
// playlists) with "The playlist does not exist", and the playlist list with HTTP 401.

const LOST = [/\bWL: YouTube said: The playlist does not exist/i, /\bLL: YouTube said: The playlist does not exist/i, /HTTP Error 401/i];

export const LOGIN_LOST =
  "Syncing lost its YouTube login, so Watch Later and private playlists can't be read. On the Mac, run: vm sync (it saves a fresh login for the app).";

export function loginLost(errors: string): boolean {
  return LOST.some((re) => re.test(errors));
}

/** All error text in a last_sync value (a sync_runs row: error plus summary.errors). */
export function syncErrors(lastSync: unknown): string {
  if (!lastSync || typeof lastSync !== 'object') return '';
  const o = lastSync as { error?: unknown; summary?: { errors?: unknown } };
  const list = [o.error, ...(Array.isArray(o.summary?.errors) ? o.summary.errors : [])];
  return list.filter((e): e is string => typeof e === 'string' && e !== '').join('\n');
}
