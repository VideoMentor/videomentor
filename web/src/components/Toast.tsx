import { useEffect } from 'react';
import type { ToastState } from '../state/useTriage';

export const TOAST_MS = 4000;

export function Toast({ toast, onUndo, onDone }: { toast: ToastState | null; onUndo(): void; onDone(): void }) {
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(onDone, TOAST_MS);
    return () => clearTimeout(t);
  }, [toast, onDone]);

  return (
    <div className={`toast${toast ? ' show' : ''}`} role="status" aria-live="polite">
      <span>{toast?.message}</span>
      {toast?.undo && (
        <button className="toast-undo" onClick={onUndo} aria-label={toast.undoLabel === 'Undo previous' ? 'Undo the step before' : 'Undo last decision'}>
          {toast.undoLabel ?? 'Undo'}
        </button>
      )}
    </div>
  );
}
