// The VideoMentor mark (docs/brand/videomentor-mark.svg): a V with a gold play inside a progress ring.
export function Logo({ size = 96, title = 'VideoMentor' }: { size?: number; title?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 512 512" role="img" aria-label={title}>
      <defs>
        <linearGradient id="vm-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#1e3a8a" />
          <stop offset="1" stopColor="#0b1224" />
        </linearGradient>
      </defs>
      <rect width="512" height="512" rx="112" fill="url(#vm-g)" />
      <circle cx="256" cy="256" r="176" fill="none" stroke="#f8fafc" strokeOpacity="0.18" strokeWidth="18" />
      <circle cx="256" cy="256" r="176" fill="none" stroke="#fbbf24" strokeWidth="18" strokeLinecap="round" strokeDasharray="760 1200" transform="rotate(-90 256 256)" />
      <path d="M168 168 L256 350 L344 168" fill="none" stroke="#f8fafc" strokeWidth="50" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M236 160 L298 196 L236 232 Z" fill="#fbbf24" />
    </svg>
  );
}
