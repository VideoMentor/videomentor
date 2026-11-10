import { LOGIN_LOST, loginLost, syncErrors } from '../lib/syncHealth';
import { PACK_SIZES, packSize, readPackSummary, refreshPack, setPackSize, type PackSummary } from '../lib/offlinePack';
import { offlineStore } from '../lib/offlineStore';
import { useDeckSource } from '../state/source';
import { START_CHOICES, readStartChoice, saveStartChoice, type StartChoice } from '../state/startScreen';
import { NEXT_UP_CHOICES, readNextUpMode, saveNextUpMode } from '../state/nextUp';
import type { NextUpMode } from '../lib/types';
import { useEffect, useState } from 'react';
import { TidyTagsScreen } from './TidyTagsScreen';
import { ProgressCard } from '../components/ProgressCard';
import { DelightSettingsCard } from '../kit/delight/DelightSettingsCard';
import { SignalSettingsScreen } from './SignalSettingsScreen';
import { AuthError, api, isNetworkError } from '../lib/api';
import { formatDateTime } from '../lib/format';
import { backupLine } from '../lib/backupLine';
import type { AiChoice, AiStatus, PairedDevice, StatusResponse } from '../lib/types';
import { AI_CHOICES, AI_OFF_ADDS, aiLine, capShown, hidesUnprepped, parseCap } from '../lib/aiView';
import { queue } from '../state/queue';
import { OLDER_THAN_DAYS, archivePlan, archiveQuestion, broughtBackLine, clearLastBatch, nlLine, readLastBatch, saveLastBatch, type ArchiveScope, type LastBatch } from '../lib/notForLearning';
import { storage } from '../state/storage';
import type { NotForLearning } from '../lib/types';

interface Props {
  status: StatusResponse | null;
  statusError: string | null;
  online: boolean;
  queued: number;
  flushing: boolean;
  onRefresh(): void;
}

const COUNT_LABELS: [keyof StatusResponse['counts'], string][] = [
  ['inbox', 'To triage'],
  ['kept', 'Kept'],
  ['archived', 'Archived'],
  ['queued', 'Waiting for analysis'],
  ['ready', 'Ready to read'],
  ['unprepped', 'Not prepped yet'],
  ['pulled_inbox', 'Pulled from channels'],
];

/** last_sync isn't pinned down by the contract; accept a string or a sync_runs row. */
function describeSync(v: unknown): { when: string; detail: string } {
  if (!v) return { when: 'Never', detail: '' };
  if (typeof v === 'string') return { when: formatDateTime(v), detail: '' };
  if (typeof v === 'object') {
    const o = v as Record<string, unknown>;
    const at = (o.finished_at ?? o.started_at ?? o.at) as string | undefined;
    let detail = '';
    if (loginLost(syncErrors(v))) detail = LOGIN_LOST;
    else if (typeof o.error === 'string' && o.error) detail = `Failed: ${o.error}`;
    else if (!o.finished_at && o.started_at) detail = 'Running now';
    else if (o.summary && typeof o.summary === 'object') {
      detail = Object.entries(o.summary as Record<string, unknown>)
        .filter(([, val]) => typeof val === 'number' || typeof val === 'string')
        .map(([k, val]) => `${k.replace(/_/g, ' ')}: ${val}`)
        .join(' · ');
    }
    return { when: at ? formatDateTime(at) : 'Unknown', detail };
  }
  return { when: String(v), detail: '' };
}

function simpleEntries(o: Record<string, unknown> | undefined): [string, string][] {
  if (!o || typeof o !== 'object') return [];
  return Object.entries(o)
    .filter(([, v]) => v === null || ['string', 'number', 'boolean'].includes(typeof v))
    .map(([k, v]) => [k.replace(/_/g, ' '), v === null ? '—' : String(v)]);
}

export function StatusScreen({ status, statusError, online, queued, flushing, onRefresh }: Props) {
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const syncNow = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const r = await api.sync();
      setSyncMsg(r?.started === false ? 'A sync is already running.' : 'Sync started. New cards show up in a few minutes.');
      setTimeout(onRefresh, 1500);
    } catch (err) {
      if (!(err instanceof AuthError)) setSyncMsg(isNetworkError(err) ? 'Sync needs a connection.' : (err as Error).message);
    } finally {
      setSyncing(false);
    }
  };

  const [tidying, setTidying] = useState(false);
  const [signalSettings, setSignalSettings] = useState(false);
  const [mergeCounts, setMergeCounts] = useState<{ proposed: number; applied: number } | null>(null);
  useEffect(() => {
    if (tidying) return;
    const ctl = new AbortController();
    api
      .tagMerges(ctl.signal)
      .then((r) => setMergeCounts(r.counts))
      .catch(() => {});
    return () => ctl.abort();
  }, [tidying, online]);

  const sync = describeSync(status?.last_sync);
  const worker = simpleEntries(status?.worker);

  if (tidying) return <TidyTagsScreen onBack={() => setTidying(false)} online={online} />;
  if (signalSettings) return <SignalSettingsScreen onBack={() => setSignalSettings(false)} online={online} />;

  return (
    <section className="page" aria-label="Status">
      <header className="page-head">
        <h1>Status</h1>
        <button className="link-btn" onClick={onRefresh} disabled={!online}>
          Refresh
        </button>
      </header>
      <div className="scroll page-body">
        {statusError && <p className="note">{statusError}</p>}

        <div className="card-block">
          <h4>Library</h4>
          <dl className="counts">
            {COUNT_LABELS.filter(([key]) => key !== 'unprepped' || !hidesUnprepped(status)).map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{status?.counts?.[key] ?? '—'}</dd>
              </div>
            ))}
          </dl>
          <p className="muted small">{backupLine(status?.backups)}</p>
        </div>

        {status?.ai && <AiCard ai={status.ai} online={online} onChanged={onRefresh} />}
        <NotForLearningCard online={online} onChanged={onRefresh} />
        <ProgressCard online={online} />
        <OfflinePackCard online={online} />
        <StartScreenCard />
        <DevicesCard online={online} />
        <DelightSettingsCard />

        <button className="card-block tidy-link" onClick={() => setSignalSettings(true)}>
          <span>
            <h4>Signal settings</h4>
            <span className="muted small">What a high signal means, areas of life, skill map</span>
          </span>
          <span aria-hidden="true">›</span>
        </button>

        {mergeCounts && (mergeCounts.proposed > 0 || mergeCounts.applied > 0) && (
          <button className="card-block tidy-link" onClick={() => setTidying(true)}>
            <span>
              <h4>Tidy tags</h4>
              <span className="muted small">
                {mergeCounts.proposed > 0
                  ? `${mergeCounts.proposed} proposed merges to review`
                  : `${mergeCounts.applied} merges applied`}
              </span>
            </span>
            <span aria-hidden="true">›</span>
          </button>
        )}

        <div className="card-block">
          <h4>Sync</h4>
          <p>
            Last sync: <b>{status ? sync.when : '—'}</b>
          </p>
          {sync.detail && <p className="note">{sync.detail}</p>}
          <button className="primary" onClick={() => void syncNow()} disabled={!online || syncing}>
            {syncing ? 'Starting…' : 'Sync now'}
          </button>
          {syncMsg && <p className="note">{syncMsg}</p>}
        </div>

        <div className="card-block">
          <h4>This phone</h4>
          <p>
            {online ? 'Online' : 'Offline'} · {queued === 0 ? 'all swipes sent' : `${queued} waiting to send`}
            {flushing ? ' · sending…' : ''}
          </p>
          {queued > 0 && (
            <button className="secondary" onClick={() => void queue.flush()} disabled={!online || flushing}>
              Send now
            </button>
          )}
        </div>

        {worker.length > 0 && (
          <div className="card-block">
            <h4>Worker</h4>
            <dl className="counts">
              {worker.map(([k, v]) => (
                <div key={k}>
                  <dt>{k}</dt>
                  <dd>{v}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <div className="card-block">
          <h4>Pairing</h4>
          <p className="note">
            To add another phone or tablet, run <code>vm pair</code> on the Mac and open the link on that device. Then use
            Share → Add to Home Screen.
          </p>
        </div>

        <p className="version" aria-label="App version">
          VideoMentor v{__APP_VERSION__} · Build {__APP_BUILD_ID__}
          <br />
          <span className="version-full">
            commit {__APP_COMMIT__} · built {formatDateTime(__APP_BUILT__)}
          </span>
        </p>
      </div>
    </section>
  );
}

/** Which AI backend runs, the monthly cap for the API key, and a one-call check. */
function AiCard({ ai, online, onChanged }: { ai: AiStatus; online: boolean; onChanged(): void }) {
  const [current, setCurrent] = useState(ai);
  const [cap, setCap] = useState(ai.cap_usd.toFixed(2));
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => setCurrent(ai), [ai]);
  // Only a changed cap resets the field, so a status refresh doesn't wipe what's being typed.
  useEffect(() => setCap(ai.cap_usd.toFixed(2)), [ai.cap_usd]);

  const errText = (err: unknown) =>
    isNetworkError(err) ? 'This needs a connection to your Mac.' : (err as Error).message;

  // One request per user action; a refused or failed call is shown, never retried.
  const save = async (change: { backend?: AiChoice; cap_usd?: number }) => {
    setBusy(true);
    setNote(null);
    try {
      setCurrent(await api.saveAi(change));
      onChanged();
    } catch (err) {
      if (!(err instanceof AuthError)) setNote(errText(err));
    } finally {
      setBusy(false);
    }
  };
  const saveCap = () => {
    const n = parseCap(cap);
    if (n === null) {
      // Never save a blank or bad value (Number('') is 0, which would pause AI): put the saved one back.
      setCap(current.cap_usd.toFixed(2));
      if (cap.trim()) setNote('The monthly limit must be between $0 and $1000.');
      return;
    }
    if (n !== current.cap_usd) void save({ cap_usd: n });
  };
  const test = async () => {
    setBusy(true);
    setNote(null);
    try {
      setNote((await api.checkAi()).message);
    } catch (err) {
      if (!(err instanceof AuthError)) setNote(errText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-block start-card">
      <h4>AI</h4>
      <p>{aiLine({ counts: {}, last_sync: null, ai: current })}</p>
      <label className="lib-select">
        <span>Use</span>
        <select
          value={current.choice}
          disabled={!online || busy}
          onChange={(e) => void save({ backend: e.target.value as AiChoice })}
        >
          {AI_CHOICES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {capShown(current.choice) && (
        <label className="lib-select">
          <span>Monthly limit for the API key ($)</span>
          <input
            type="number"
            inputMode="decimal"
            min={0}
            max={1000}
            step="0.5"
            value={cap}
            disabled={!online || busy}
            onChange={(e) => setCap(e.target.value)}
            onBlur={saveCap}
            onKeyDown={(e) => {
              if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
            }}
          />
        </label>
      )}
      <button className="secondary" onClick={() => void test()} disabled={!online || busy}>
        {busy ? 'Working…' : 'Test'}
      </button>
      {note && <p className="note small">{note}</p>}
      {current.backend === 'off' && <p className="muted small">{AI_OFF_ADDS}</p>}
      <p className="muted small">The API key itself is set in the Mac app, under AI Settings.</p>
    </div>
  );
}

/** Which screen the app opens on. */
function StartScreenCard() {
  const [start, setStart] = useState<StartChoice>(readStartChoice);
  const [nextUp, setNextUp] = useState<NextUpMode>(readNextUpMode);
  return (
    <div className="card-block start-card">
      <h4>Start screen and Home</h4>
      <label className="lib-select">
        <span>Open the app on</span>
        <select
          value={start}
          onChange={(e) => {
            const v = e.target.value as StartChoice;
            setStart(v);
            saveStartChoice(v);
          }}
        >
          {START_CHOICES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <label className="lib-select">
        <span>Next up shows</span>
        <select
          value={nextUp}
          onChange={(e) => {
            const v = e.target.value as NextUpMode;
            setNextUp(v);
            saveNextUpMode(v);
          }}
        >
          {NEXT_UP_CHOICES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      <p className="muted small">Watch next suggests the best video in the deck. Apply next suggests a step to try, with Done and Skip.</p>
      <p className="muted small">The app turns with your phone. To keep it upright, use Rotation Lock in Control Center.</p>
    </div>
  );
}

/** Music and entertainment waiting in the inbox: archive the old ones in one step, with Undo. */
function NotForLearningCard({ online, onChanged }: { online: boolean; onChanged(): void }) {
  const [counts, setCounts] = useState<NotForLearning | null>(null);
  const [last, setLast] = useState<LastBatch | null>(() => readLastBatch(storage));
  const [confirming, setConfirming] = useState<ArchiveScope | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const load = () =>
    api
      .notForLearning()
      .then((c) => {
        setCounts(c);
        return c;
      })
      .catch(() => null);
  useEffect(() => {
    if (online) void load();
  }, [online]);

  const errText = (err: unknown) => (isNetworkError(err) ? 'This needs a connection to your Mac.' : (err as Error).message);

  const archive = async (scope: ArchiveScope) => {
    if (!counts) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await api.archiveNotForLearning(archivePlan(counts, scope).days);
      setConfirming(null);
      if (r.archived > 0) {
        const b = { batch: r.batch, archived: r.archived };
        saveLastBatch(storage, b);
        setLast(b);
      } else {
        setNote('Nothing to archive.');
      }
      onChanged();
      void load();
    } catch (err) {
      if (!(err instanceof AuthError)) setNote(errText(err));
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!last) return;
    setBusy(true);
    setNote(null);
    try {
      const r = await api.undoBatch(last.batch);
      clearLastBatch(storage);
      setLast(null);
      setNote(broughtBackLine(r.undone, r.skipped));
      onChanged();
      void load();
    } catch (err) {
      if (!(err instanceof AuthError)) setNote(errText(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card-block start-card">
      <h4>Not for learning</h4>
      <p>{counts ? nlLine(counts, OLDER_THAN_DAYS) : online ? 'Loading…' : 'Shows when you have signal.'}</p>
      {confirming && counts ? (
        <>
          <p className="note">{archiveQuestion(archivePlan(counts, confirming).count)}</p>
          <button className="primary" onClick={() => void archive(confirming)} disabled={!online || busy}>
            {busy ? 'Archiving…' : `Archive ${archivePlan(counts, confirming).count.toLocaleString()}`}
          </button>{' '}
          <button className="secondary" onClick={() => setConfirming(null)} disabled={busy}>
            Cancel
          </button>
        </>
      ) : (
        <>
          {(['older', 'all'] as const).map((scope) => (
            <button
              key={scope}
              className="secondary"
              onClick={() => {
                // The count in the question must be current: refresh it first.
                void load().then((c) => {
                  if (c && archivePlan(c, scope).count > 0) {
                    setNote(null);
                    setConfirming(scope);
                  } else if (c) {
                    setNote(scope === 'all' ? 'Nothing to archive.' : 'Nothing older than 30 days to archive.');
                  }
                });
              }}
              disabled={!online || busy || !counts || archivePlan(counts, scope).count === 0}>
              {scope === 'all' ? 'Archive all of them' : 'Archive the older ones'}
            </button>
          ))}
        </>
      )}
      {last && (
        <p className="note">
          Archived {last.archived.toLocaleString()}.{' '}
          <button className="inline-link" onClick={() => void undo()} disabled={!online || busy}>
            Undo
          </button>
        </p>
      )}
      {note && <p className="note small">{note}</p>}
      <p className="muted small">Music and entertainment you saved. Swipe them from the deck’s “Not for learning” source instead.</p>
    </div>
  );
}

/** Paired devices: each has its own sign-in, which expires after a stretch of no use. */
function DevicesCard({ online }: { online: boolean }) {
  const [list, setList] = useState<PairedDevice[] | null>(null);
  const [days, setDays] = useState(90);
  const [note, setNote] = useState<string | null>(null);
  const load = () =>
    api
      .devices()
      .then((r) => {
        setList(r.devices);
        setDays(r.expire_days);
      })
      .catch(() => {});
  useEffect(() => {
    if (online) void load();
  }, [online]);

  const signOut = async (d: PairedDevice) => {
    await api.signOutDevice(d.id).catch(() => {});
    if (d.current) window.location.reload();
    else void load();
  };
  const signOutOthers = async () => {
    const r = await api.signOutOthers().catch(() => null);
    setNote(r ? `Signed out ${r.signed_out} other device${r.signed_out === 1 ? '' : 's'}.` : 'Couldn’t sign out; try again.');
    void load();
  };

  return (
    <div className="card-block devices-card">
      <h4>Paired devices</h4>
      {!list && <p className="note small">{online ? 'Loading…' : 'Shows when you have signal.'}</p>}
      {list && (
        <ul className="rows devices">
          {list.map((d) => (
            <li key={d.id} className="device-row">
              <span>
                <b>{d.device}</b>
                {d.current && <span className="muted small"> · this device</span>}
                <br />
                <span className="muted small">Last used {formatDateTime(d.last_seen)}</span>
              </span>
              <button className="link-btn small" onClick={() => void signOut(d)}>
                Sign out
              </button>
            </li>
          ))}
        </ul>
      )}
      {list && list.length > 1 && (
        <button className="secondary" onClick={() => void signOutOthers()}>
          Sign out all other devices
        </button>
      )}
      {note && <p className="note small">{note}</p>}
      <p className="muted small">A device unused for {days} days is signed out automatically. Pair again with the pairing link from the Mac.</p>
    </div>
  );
}

/** What the phone keeps for when the Mac can't be reached, and a way to refresh it now. */
function OfflinePackCard({ online }: { online: boolean }) {
  const source = useDeckSource();
  const [summary, setSummary] = useState<PackSummary | null>(null);
  const [size, setSize] = useState(packSize);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useEffect(() => {
    void readPackSummary(offlineStore()).then(setSummary);
  }, []);
  const refresh = async (cards = size) => {
    setBusy(true);
    setNote(null);
    setPackSize(cards);
    try {
      // Cards in hand are skipped when the pack is used, so no exclusions are needed here.
      setSummary(await refreshPack(offlineStore(), { exclude: [], source: source.key }));
    } catch (err) {
      setNote(isNetworkError(err) ? 'Refreshing needs a connection to your Mac.' : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="card-block start-card">
      <h4>Offline pack</h4>
      <p className="note small">
        {summary
          ? `${summary.cards} cards · ${summary.items} notes · ${summary.modules} ${summary.modules === 1 ? 'module' : 'modules'} · ${summary.actions} actions · updated ${formatDateTime(summary.at)}`
          : 'Nothing saved yet. It fills in by itself while your Mac is reachable.'}
      </p>
      <label className="lib-select">
        <span>Cards to keep per deck</span>
        <select
          value={size}
          onChange={(e) => {
            const n = Number(e.target.value);
            setSize(n);
            void refresh(n);
          }}
        >
          {PACK_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>
      <button className="secondary" onClick={() => void refresh()} disabled={!online || busy}>
        {busy ? 'Refreshing…' : 'Refresh now'}
      </button>
      {note && <p className="note small">{note}</p>}
      <p className="muted small">With your Mac off, you can still swipe these cards, read notes, check off actions and read training. Changes sync when it's back.</p>
    </div>
  );
}
