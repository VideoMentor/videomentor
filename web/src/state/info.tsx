// The ⓘ sheet: any screen can open info for a video, tag or channel. Opening
// from inside the sheet stacks, so "Back" returns to where you were.
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import type { Card, Playlist } from '../lib/types';
import { touches } from './events';

export type InfoTarget =
  | { kind: 'video'; card: Card }
  | { kind: 'tag'; tag: string }
  | { kind: 'channel'; channel_id?: string | null; name: string | null }
  | { kind: 'playlist'; playlist: Playlist };

interface InfoApi {
  stack: InfoTarget[];
  open(target: InfoTarget): void;
  back(): void;
  close(): void;
}

const InfoContext = createContext<InfoApi>({ stack: [], open: () => {}, back: () => {}, close: () => {} });

export function InfoProvider({ children }: { children: ReactNode }) {
  const [stack, setStack] = useState<InfoTarget[]>([]);
  const open = useCallback((target: InfoTarget) => {
    if (target.kind === 'video') touches.track('info', target.card.id);
    setStack((s) => [...s, target]);
  }, []);
  const back = useCallback(() => setStack((s) => s.slice(0, -1)), []);
  const close = useCallback(() => setStack([]), []);
  const value = useMemo(() => ({ stack, open, back, close }), [stack, open, back, close]);
  return <InfoContext.Provider value={value}>{children}</InfoContext.Provider>;
}

export function useInfo(): InfoApi {
  return useContext(InfoContext);
}
