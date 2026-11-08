import { useCallback, useEffect, useState } from 'react';
import { AuthError, api, isNetworkError, onAuthorized, onUnauthorized } from './lib/api';
import type { StatusResponse } from './lib/types';
import { DeckScreen } from './screens/DeckScreen';
import { ReadyScreen } from './screens/ReadyScreen';
import { LibraryScreen } from './screens/LibraryScreen';
import { StatusScreen } from './screens/StatusScreen';
import { PlaylistsScreen } from './screens/PlaylistsScreen';
import { ActionsScreen } from './screens/ActionsScreen';
import { TrainScreen } from './screens/TrainScreen';
import { HomeScreen } from './screens/HomeScreen';
import { initialTab, rememberTab } from './state/startScreen';
import { reportDevice } from './lib/deviceHint';
import { isStale, readPackSummary, refreshPack } from './lib/offlinePack';
import { offlineStore } from './lib/offlineStore';
import { onNavigate } from './state/nav';
import { PairScreen } from './screens/PairScreen';
import { TabBar, type Tab } from './components/TabBar';
import { Toast } from './components/Toast';
import { InfoSheet } from './components/InfoSheet';
import { MilestoneOverlay } from './kit/delight/MilestoneOverlay';
import { checkMilestones } from './state/milestones';
import { InfoProvider } from './state/info';
import { touches } from './state/events';
import { useOnForeground, useOnline } from './state/hooks';
import { queue, useQueueFlushing, useQueueLength } from './state/queue';
import { useTriage } from './state/useTriage';

const FLUSH_EVERY_MS = 20_000;
const STATUS_EVERY_MS = 60_000;

export function App() {
  const online = useOnline();
  const queued = useQueueLength();
  const flushing = useQueueFlushing();
  const [needsPair, setNeedsPair] = useState(false);
  const [tab, setTab] = useState<Tab>(initialTab);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [seenIds, setSeenIds] = useState<Set<string>>(new Set());
  const t = useTriage(online);

  useEffect(() => onUnauthorized(() => setNeedsPair(true)), []);
  useEffect(() => onAuthorized(() => setNeedsPair(false)), []);
  useEffect(() => onNavigate(setTab), []);
  useEffect(() => rememberTab(tab), [tab]);

  const loadStatus = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      reportDevice(); // signed in now: label an iPad correctly
      setSeenIds(new Set());
      setStatusError(null);
    } catch (err) {
      if (err instanceof AuthError) return;
      setStatusError(isNetworkError(err) ? 'Offline. Showing the last known numbers.' : (err as Error).message);
    }
  }, []);

  const flush = useCallback(() => {
    if (!navigator.onLine) return;
    if (queue.length) void queue.flush();
    if (touches.length) void touches.flush();
  }, []);

  // Start-up, then keep the queue moving and the counts fresh.
  useEffect(() => {
    void loadStatus();
    setTimeout(() => void checkMilestones(), 2500);
    flush();
    const f = setInterval(flush, FLUSH_EVERY_MS);
    const s = setInterval(() => {
      if (document.visibilityState === 'visible' && navigator.onLine) void loadStatus();
    }, STATUS_EVERY_MS);
    return () => {
      clearInterval(f);
      clearInterval(s);
    };
  }, [flush, loadStatus]);

  useEffect(() => {
    if (online) {
      flush();
      void loadStatus();
    }
  }, [online, flush, loadStatus]);

  // Keep the offline pack fresh: on start and when the app comes back, if it's over 30 minutes old.
  const refreshPackIfStale = useCallback(async () => {
    if (!navigator.onLine) return;
    const store = offlineStore();
    if (!isStale(await readPackSummary(store))) return;
    await refreshPack(store, { exclude: t.packExclude(), source: t.source.key }).catch(() => {});
  }, [t]);
  useEffect(() => {
    const timer = setTimeout(() => void refreshPackIfStale(), 4000); // after the first screen loads
    return () => clearTimeout(timer);
  }, [refreshPackIfStale]);

  const onForeground = useCallback(() => {
    void refreshPackIfStale();
    flush();
    if (navigator.onLine) void loadStatus();
  }, [flush, loadStatus]);
  useOnForeground(onForeground);

  const onSeen = useCallback((id: string) => setSeenIds((s) => new Set(s).add(id)), []);
  const readyCount = Math.max(0, (status?.counts?.ready ?? 0) - seenIds.size);

  const retryPair = useCallback(() => {
    void loadStatus();
    void t.refresh();
  }, [loadStatus, t]);

  if (needsPair) {
    return (
      <div className="app">
        <PairScreen onRetry={retryPair} />
      </div>
    );
  }

  return (
    <InfoProvider>
    <div className="app">
      <main className="screen">
        {tab === 'home' && <HomeScreen status={status} readyCount={readyCount} online={online} />}
        {tab === 'deck' && <DeckScreen t={t} online={online} queued={queued} />}
        {tab === 'ready' && <ReadyScreen online={online} onSeen={onSeen} />}
        {tab === 'library' && <LibraryScreen online={online} />}
        {tab === 'actions' && <ActionsScreen online={online} />}
        {tab === 'train' && <TrainScreen online={online} />}
        {tab === 'playlists' && <PlaylistsScreen online={online} />}
        {tab === 'status' && (
          <StatusScreen
            status={status}
            statusError={statusError}
            online={online}
            queued={queued}
            flushing={flushing}
            onRefresh={() => void loadStatus()}
          />
        )}
      </main>
      <Toast
        toast={t.toast}
        onDone={t.hideToast}
        onUndo={() => {
          // The undo itself shows the next toast ("Undid: …", maybe "Undo previous").
          void t.undo();
        }}
      />
      <TabBar tab={tab} onTab={setTab} readyCount={readyCount} />
      <InfoSheet />
      <MilestoneOverlay onShown={(id) => void api.milestonesSeen([id]).catch(() => {})} />
    </div>
    </InfoProvider>
  );
}
