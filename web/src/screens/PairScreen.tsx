import { useState, type FormEvent } from 'react';

/** Digits only, grouped 4-4-4 as you type. */
export function formatCode(v: string): string {
  // A pasted pairing link: use only its code, not the digits of the address or port.
  const fromLink = /[?&]code=([^&#\s]*)/.exec(v);
  const d = decodeURIComponent(fromLink ? fromLink[1] : v).replace(/\D/g, '').slice(0, 12);
  return [d.slice(0, 4), d.slice(4, 8), d.slice(8)].filter(Boolean).join('-');
}

export function PairScreen({ onRetry }: { onRetry(): void }) {
  const [code, setCode] = useState('');
  // A real form POST: the code goes in the request body, not the address bar or history.
  const submit = (e: FormEvent) => {
    if (code.replace(/\D/g, '').length !== 12) e.preventDefault();
  };
  return (
    <section className="pair" aria-labelledby="pair-title">
      <img src="/icons/vm-180.png" alt="" width={72} height={72} />
      <h1 id="pair-title">Pair this device</h1>
      <p>
        On the Mac, run <code>vm pair</code> and open the link it prints on this device. Or type its 12-digit code here.
      </p>
      <form method="post" action="/pair" onSubmit={submit}>
        <input
          name="code"
          value={code}
          onChange={(e) => setCode(formatCode(e.target.value))}
          placeholder="1234-5678-9012"
          aria-label="Pairing code (12 digits)"
          inputMode="numeric"
          maxLength={14}
          autoComplete="one-time-code"
          autoCorrect="off"
          spellCheck={false}
        />
        <button className="primary" type="submit" disabled={code.replace(/\D/g, '').length !== 12}>
          Pair
        </button>
      </form>
      <button className="link-btn" onClick={onRetry}>
        I’ve paired. Try again
      </button>
    </section>
  );
}
