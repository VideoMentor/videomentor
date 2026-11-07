// Haptics. Android and others: the Vibration API. iPhone Safari has no Vibration API;
// since iOS 18, toggling a native <input type="checkbox" switch> gives a light tap,
// which is the only way a web page can produce one. Must run inside a user gesture.
let iosSwitch: HTMLLabelElement | null = null;

function iosTap(): void {
  if (typeof document === 'undefined') return;
  if (!iosSwitch) {
    iosSwitch = document.createElement('label');
    iosSwitch.setAttribute('aria-hidden', 'true');
    Object.assign(iosSwitch.style, { position: 'fixed', left: '-9999px', top: '0', opacity: '0', pointerEvents: 'none' });
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.setAttribute('switch', '');
    input.tabIndex = -1;
    iosSwitch.appendChild(input);
    document.body.appendChild(iosSwitch);
  }
  iosSwitch.click();
}

export function haptic(strength: 'light' | 'strong' = 'light'): void {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      navigator.vibrate(strength === 'strong' ? [12, 40, 18] : 10);
    } else {
      iosTap();
    }
  } catch {
    // never let a haptic break a swipe
  }
}
