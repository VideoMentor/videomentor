import { describe, expect, it } from 'vitest';
import { loginLost, syncErrors } from './syncHealth';

describe('loginLost', () => {
  it('spots a stale YouTube login in sync errors', () => {
    expect(loginLost('watch_later: ERROR: [youtube:tab] WL: YouTube said: The playlist does not exist.')).toBe(true);
    expect(loginLost('playlist list: ERROR: [youtube:tab] playlists: Unable to download API page: HTTP Error 401: Unauthorized')).toBe(true);
  });
  it('leaves other failures alone', () => {
    expect(loginLost('Interesting: ERROR: [youtube:tab] PLabc: YouTube said: The playlist does not exist.')).toBe(false);
    expect(loginLost('')).toBe(false);
    expect(loginLost('network timeout')).toBe(false);
  });
});

describe('syncErrors', () => {
  it('gathers the error and summary errors of a sync row', () => {
    expect(syncErrors({ error: 'a', summary: { errors: ['b', 3, ''] } })).toBe('a\nb');
    expect(syncErrors(null)).toBe('');
    expect(syncErrors('2026-11-07')).toBe('');
  });
});
