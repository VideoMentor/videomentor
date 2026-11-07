import { useEffect, useState } from 'react';

export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  }, []);
  return online;
}

/** Run `fn` when the app comes back to the foreground. */
export function useOnForeground(fn: () => void): void {
  useEffect(() => {
    const vis = () => {
      if (document.visibilityState === 'visible') fn();
    };
    window.addEventListener('focus', fn);
    document.addEventListener('visibilitychange', vis);
    return () => {
      window.removeEventListener('focus', fn);
      document.removeEventListener('visibilitychange', vis);
    };
  }, [fn]);
}

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export function vibrate(pattern: number | number[]): void {
  try {
    if (typeof navigator.vibrate === 'function') navigator.vibrate(pattern);
  } catch {
    // unsupported (iOS Safari); silently skip
  }
}

/** True while a CSS media query matches (re-renders on change, e.g. iPad rotation). */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia(query);
    const on = () => setMatches(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, [query]);
  return matches;
}

/** Wide enough for side-by-side panes: iPad landscape, a Mac window. */
export const WIDE = '(min-width: 1100px)';
