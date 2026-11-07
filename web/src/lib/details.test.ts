import { describe, expect, it } from 'vitest';
import { actionLabel, byline, compactNumber, formatPosted, formatYmd, normalizeAnalysis, savedBadge, savedLine, signalLabel } from './format';
import { deckUrl } from './api';
import { EventBuffer, type TouchEvent } from './events';
import { MemoryStorage } from './queue';
import { NetworkError } from './api';

describe('formatPosted', () => {
  it('shows date and time for exact times, in local time', () => {
    const iso = '2025-03-04T14:15:00+00:00';
    const expected = new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
    expect(formatPosted(iso, true)).toBe(expected);
  });

  it('shows the date only, without shifting the day, for date-only values', () => {
    expect(formatPosted('2024-01-01', false)).toBe('Jan 1, 2024');
  });

  it('is empty for missing or junk values', () => {
    expect(formatPosted(null, false)).toBe('');
    expect(formatPosted('nope', true)).toBe('');
  });
});

describe('byline', () => {
  it('joins posted and channel', () => {
    expect(byline({ posted_at: '2024-01-01', posted_exact: false, channel: 'Lenny' })).toEqual({
      posted: 'Jan 1, 2024',
      by: 'Lenny',
    });
  });
  it('copes with missing fields', () => {
    expect(byline({ posted_at: null, posted_exact: false, channel: null })).toEqual({ posted: '', by: '' });
  });
});

describe('compactNumber', () => {
  it('abbreviates', () => {
    expect(compactNumber(950)).toBe('950');
    expect(compactNumber(12_345)).toBe('12K');
    expect(compactNumber(1_250_000)).toBe('1.3M');
    expect(compactNumber(null)).toBe('');
  });
});

describe('actionLabel', () => {
  it('names each touch', () => {
    expect(actionLabel('keep')).toBe('Kept');
    expect(actionLabel('prioritize')).toBe('Kept, analyze first');
    expect(actionLabel('archive')).toBe('Archived');
    expect(actionLabel('flip')).toBe('Flipped the card');
    expect(actionLabel('open')).toBe('Opened on YouTube');
    expect(actionLabel('info')).toBe('Viewed info');
    expect(actionLabel('other')).toBe('other');
  });
});

describe('EventBuffer', () => {
  function setup() {
    const sent: TouchEvent[][] = [];
    let online = true;
    const storage = new MemoryStorage();
    const transport = async (events: TouchEvent[]) => {
      if (!online) throw new NetworkError();
      sent.push(events);
    };
    const buf = new EventBuffer({ storage, transport, key: 't' });
    return { buf, sent, storage, setOnline: (v: boolean) => (online = v) };
  }

  it('sends tracked events once and clears them', async () => {
    const { buf, sent } = setup();
    buf.track('flip', 'yt:a');
    buf.track('info', 'yt:b');
    expect(buf.length).toBe(2);
    await buf.flush();
    expect(sent).toHaveLength(1);
    expect(sent[0].map((e) => [e.kind, e.item_id])).toEqual([
      ['flip', 'yt:a'],
      ['info', 'yt:b'],
    ]);
    expect(new Set(sent[0].map((e) => e.client_id)).size).toBe(2);
    expect(buf.length).toBe(0);
    await buf.flush();
    expect(sent).toHaveLength(1);
  });

  it('keeps events while offline and survives a reload', async () => {
    const { buf, sent, storage, setOnline } = setup();
    setOnline(false);
    buf.track('open', 'yt:a');
    await buf.flush();
    expect(buf.length).toBe(1);
    const reloaded = new EventBuffer({
      storage,
      transport: async (e) => {
        sent.push(e);
      },
      key: 't',
    });
    expect(reloaded.length).toBe(1);
    await reloaded.flush();
    expect(sent[0][0].kind).toBe('open');
  });

  it('keeps events tracked during a flush', async () => {
    const { buf, sent } = setup();
    buf.track('flip', 'yt:a');
    const p = buf.flush();
    buf.track('flip', 'yt:b');
    await p;
    expect(buf.length).toBe(1);
    await buf.flush();
    expect(sent.flat().map((e) => e.item_id)).toEqual(['yt:a', 'yt:b']);
  });

  it('caps the buffer so a long offline spell cannot grow it forever', () => {
    const { buf } = setup();
    for (let i = 0; i < EventBuffer.MAX + 10; i++) buf.track('flip', `yt:${i}`);
    expect(buf.length).toBe(EventBuffer.MAX);
  });
});

describe('playlist and source helpers', () => {
  it('formats YouTube YYYYMMDD dates', () => {
    expect(formatYmd('20261030')).toBe('Oct 30, 2026');
    expect(formatYmd('nope')).toBe('');
  });
  it('builds the thumbnail badge from saved-in labels', () => {
    expect(savedBadge({ saved_in_labels: ['Watch Later', 'Biz ideas'], sources: [] })).toBe('Watch Later +1');
    expect(savedBadge({ saved_in_labels: ['Biz ideas'], sources: [] })).toBe('Biz ideas');
    expect(savedBadge({ saved_in_labels: [], sources: ['youtube:watch_later'] })).toBe('Watch Later');
  });
  it('adds the source to deck URLs except for all', () => {
    expect(deckUrl('main', 10, [], 'all')).toBe('/api/deck?deck=main&n=10');
    expect(deckUrl('main', 10, [], 'pl:PLa')).toBe('/api/deck?deck=main&n=10&source=pl%3APLa');
  });
});

describe('savedLine', () => {
  it('says when and where a video was saved', () => {
    expect(savedLine({ saved_at: '2026-10-30', saved_where: 'Biz ideas' })).toBe('Saved Oct 30, 2026 to Biz ideas');
    expect(savedLine({ saved_at: '2026-10-30', saved_where: null })).toBe('Saved Oct 30, 2026');
    expect(savedLine({ saved_at: null, saved_where: null })).toBe('');
  });
});

describe('analysis and signal', () => {
  it('labels signal guesses and analysis scores differently', () => {
    expect(signalLabel({ signal: 4, signal_source: 'analysis' })).toBe('Signal 4/5');
    expect(signalLabel({ signal: 3, signal_source: 'prep' })).toBe('Signal ~3/5');
    expect(signalLabel({ signal: null, signal_source: null })).toBe('');
  });
  it('reads business-lens analysis fields and tolerates old ones', () => {
    const a = normalizeAnalysis({
      core_idea: 'Anchor first',
      frameworks: [{ name: 'Anchoring', how: 'Say a number first' }, 'junk'],
      try_this_week: ['Open with a number'],
      key_moment: { t: 242, label: 'the anchor' },
      skills: ['Negotiation'],
    });
    expect(a?.core_idea).toBe('Anchor first');
    expect(a?.frameworks).toEqual([{ name: 'Anchoring', how: 'Say a number first' }]);
    expect(a?.key_moment).toEqual({ seconds: 242, label: 'the anchor' });
    const old = normalizeAnalysis({ summary: 'old', learnings: ['x'] });
    expect(old?.core_idea).toBe('');
    expect(old?.key_moment).toBeNull();
  });
});

describe('deck order', () => {
  it('adds sort, direction and start date to the deck URL', () => {
    expect(deckUrl('main', 10, [], 'all', { sort: 'default', dir: 'desc', start: null })).toBe('/api/deck?deck=main&n=10');
    expect(deckUrl('main', 10, [], 'wl', { sort: 'posted', dir: 'asc', start: '2024-03-04' })).toBe(
      '/api/deck?deck=main&n=10&source=wl&sort=posted&dir=asc&start=2024-03-04',
    );
  });
});

describe('byline with collaborators', () => {
  const base = { posted_at: null, posted_exact: false, channel: 'Host Channel' };
  const guest = (name: string) => ({ name, channel_id: null });
  it('names the owner and the channels credited with them', () => {
    expect(byline({ ...base, collaborators: [] }).by).toBe('Host Channel');
    expect(byline({ ...base, collaborators: [guest('Guest Channel')] }).by).toBe('Host Channel with Guest Channel');
    expect(byline({ ...base, collaborators: [guest('A'), guest('B'), guest('C')] }).by).toBe('Host Channel with A, B and C');
  });
});
