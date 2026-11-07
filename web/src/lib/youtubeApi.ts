// Loads YouTube's IFrame Player API once, so a clip can tell us when it reaches its end time.

export interface YTPlayer {
  loadVideoById(o: { videoId: string; startSeconds: number; endSeconds: number }): void;
  playVideo(): void;
  pauseVideo(): void;
  destroy(): void;
}

interface YTNamespace {
  Player: new (
    el: HTMLElement,
    opts: {
      videoId: string;
      playerVars: Record<string, number | string>;
      events: { onReady?(): void; onStateChange?(e: { data: number }): void; onError?(e: { data: number }): void };
    },
  ) => YTPlayer;
  PlayerState: { ENDED: number; PLAYING: number };
}

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

let loading: Promise<YTNamespace> | null = null;

export function loadYouTubeApi(): Promise<YTNamespace> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (loading) return loading;
  loading = new Promise((resolve, reject) => {
    const s = document.createElement('script');
    // iframe_api loads a second script; if that one is blocked or offline, nothing fires. Give up after 10 s.
    const fail = () => {
      clearTimeout(timer);
      s.remove();
      loading = null;
      reject(new Error('YouTube player could not load'));
    };
    const timer = setTimeout(fail, 10_000);
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      prev?.();
      if (window.YT?.Player) {
        clearTimeout(timer);
        resolve(window.YT);
      } else fail();
    };
    s.src = 'https://www.youtube.com/iframe_api';
    s.async = true;
    s.onerror = fail;
    document.head.appendChild(s);
  });
  return loading;
}
