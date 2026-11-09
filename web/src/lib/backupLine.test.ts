import { describe, expect, it } from 'vitest';
import { backupLine, formatBytes } from './backupLine';

const now = new Date(2026, 10, 9, 15, 0).getTime();
const at = (d: number, h: number, m = 0) => new Date(2026, 10, d, h, m).toISOString();

describe('formatBytes', () => {
  it('uses KB and MB', () => {
    expect(formatBytes(512)).toBe('1 KB');
    expect(formatBytes(92 * 1024 * 1024)).toBe('92 MB');
    expect(formatBytes(1.5 * 1024 * 1024 * 1024)).toBe('1.5 GB');
  });
});

describe('backupLine', () => {
  it('says so when there is no backup', () => {
    expect(backupLine(undefined, now)).toBe('No backup yet');
    expect(backupLine({ last_at: null, count: 0, bytes: 0 }, now)).toBe('No backup yet');
  });
  it('shows today with time, count and size', () => {
    const s = { last_at: at(9, 3), count: 14, bytes: 92 * 1024 * 1024 };
    expect(backupLine(s, now)).toMatch(/^Backups: daily, last 3:00\s?AM today, 14 kept \(92 MB\)$/);
  });
  it('shows yesterday and older days', () => {
    const s = { last_at: at(8, 15, 30), count: 1, bytes: 2048 };
    expect(backupLine(s, now)).toMatch(/^Backups: daily, last 3:30\s?PM yesterday, 1 kept \(2 KB\)$/);
    expect(backupLine({ ...s, last_at: at(5, 3) }, now)).toMatch(/last 3:00\s?AM Nov 5,/);
  });
});
