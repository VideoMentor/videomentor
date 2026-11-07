// Settings card for sounds, effects and milestones. Generic: no app imports.
import { decision, round } from './celebrate';
import { setDelight, useDelight, type EffectsLevel } from './settings';

export function DelightSettingsCard() {
  const s = useDelight();
  return (
    <div className="card-block delight-card">
      <h4>Sounds and effects</h4>
      <label className="switch-row">
        <span>
          Calm mode
          <small className="muted"> · no sounds, effects or pop-ups</small>
        </span>
        <span className="switch">
          <input type="checkbox" checked={s.calm} onChange={(e) => setDelight({ calm: e.target.checked })} />
          <span aria-hidden="true" />
        </span>
      </label>
      <fieldset className="delight-fields" disabled={s.calm}>
        <label className="switch-row">
          <span>Sounds</span>
          <span className="switch">
            <input type="checkbox" checked={s.sound} onChange={(e) => setDelight({ sound: e.target.checked })} />
            <span aria-hidden="true" />
          </span>
        </label>
        <label className="delight-volume">
          <span>Volume</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={s.volume}
            disabled={!s.sound}
            onChange={(e) => setDelight({ volume: Number(e.target.value) })}
          />
        </label>
        <div className="delight-row">
          <span>Effects</span>
          <div className="segmented" role="tablist" aria-label="Effects">
            {(['full', 'subtle', 'off'] as EffectsLevel[]).map((k) => (
              <button key={k} role="tab" aria-selected={s.effects === k} className={s.effects === k ? 'on' : ''} onClick={() => setDelight({ effects: k })}>
                {k === 'full' ? 'Full' : k === 'subtle' ? 'Subtle' : 'Off'}
              </button>
            ))}
          </div>
        </div>
        <label className="switch-row">
          <span>Milestone celebrations</span>
          <span className="switch">
            <input type="checkbox" checked={s.milestones} onChange={(e) => setDelight({ milestones: e.target.checked })} />
            <span aria-hidden="true" />
          </span>
        </label>
        <div className="delight-try">
          <button className="secondary" onClick={() => decision('keep', { x: innerWidth / 2, y: innerHeight / 2 })}>
            Try a swipe
          </button>
          <button className="secondary" onClick={round}>
            Try a cleared deck
          </button>
        </div>
      </fieldset>
      <p className="note small">Effects follow your device's Reduce Motion setting. On iPhone, the silent switch may mute sounds.</p>
    </div>
  );
}
