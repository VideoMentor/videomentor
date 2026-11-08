import { beforeEach, describe, expect, it } from 'vitest';
import { AuthError, NetworkError, api, itemUrl, setFetch } from './api';
import { MemoryOfflineStore, setOfflineStore } from './offlineStore';

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

describe('saved copies for offline use', () => {
  let store: MemoryOfflineStore;
  beforeEach(() => {
    store = new MemoryOfflineStore();
    setOfflineStore(store);
  });

  it('returns the saved copy when the Mac cannot be reached', async () => {
    setFetch(async () => json({ items: [{ id: 'yt:a' }] }));
    expect(await api.ready()).toEqual([{ id: 'yt:a' }]);
    setFetch(async () => {
      throw new TypeError('Failed to fetch');
    });
    expect(await api.ready()).toEqual([{ id: 'yt:a' }]);
    expect(await store.get(itemUrl('yt:none'))).toBeUndefined();
  });

  it('only keeps copies of screens worth reading offline', async () => {
    setFetch(async () => json({ counts: {} }));
    await api.status();
    expect(await store.get('/api/status')).toBeUndefined();
  });

  it('still fails offline when there is no saved copy', async () => {
    setFetch(async () => {
      throw new TypeError('Failed to fetch');
    });
    await expect(api.item('yt:never')).rejects.toBeInstanceOf(NetworkError);
  });

  it('forgets everything when the device is signed out', async () => {
    await store.set('/api/ready', { items: [] });
    setFetch(async () => json({ detail: 'pair' }, 401));
    await expect(api.ready()).rejects.toBeInstanceOf(AuthError);
    expect(await store.get('/api/ready')).toBeUndefined();
  });
});

describe('when the Mac app is down but Tailscale answers', () => {
  it('treats a gateway error like no connection', async () => {
    const store = new MemoryOfflineStore();
    setOfflineStore(store);
    await store.set('/api/ready', { items: [{ id: 'yt:s' }] });
    setFetch(async () => new Response('Bad Gateway', { status: 502 }));
    expect(await api.ready()).toEqual([{ id: 'yt:s' }]);
    await expect(api.item('yt:none')).rejects.toBeInstanceOf(NetworkError);
    setFetch(async () => new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }));
    await expect(api.ready()).rejects.not.toBeInstanceOf(NetworkError); // a working server's error
  });

  it('shows the saved copy after a short wait instead of hanging', async () => {
    const { setOfflineTimeout } = await import('./api');
    const store = new MemoryOfflineStore();
    setOfflineStore(store);
    await store.set('/api/ready', { items: [{ id: 'yt:t' }] });
    setOfflineTimeout(20);
    setFetch(() => new Promise<Response>(() => {})); // never answers
    expect(await api.ready()).toEqual([{ id: 'yt:t' }]);
    setOfflineTimeout(5000);
  });
});

describe('withTimeout', () => {
  it('gives the fallback when a promise never settles', async () => {
    const { withTimeout } = await import('./offlineStore');
    expect(await withTimeout(new Promise(() => {}), 10, 'fallback')).toBe('fallback');
    expect(await withTimeout(Promise.resolve('real'), 10, 'fallback')).toBe('real');
  });
});
