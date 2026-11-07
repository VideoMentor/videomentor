// Search field with a clear (×) button that shows while there's text.
import { useRef } from 'react';

export function SearchBox({ value, onChange, placeholder, label }: { value: string; onChange(v: string): void; placeholder: string; label: string }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="searchbox">
      <input
        ref={input}
        type="search"
        inputMode="search"
        enterKeyHint="search"
        placeholder={placeholder}
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && value) onChange('');
        }}
      />
      {value && (
        <button
          type="button"
          className="search-clear"
          aria-label="Clear search"
          onClick={() => {
            onChange('');
            input.current?.focus();
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}
