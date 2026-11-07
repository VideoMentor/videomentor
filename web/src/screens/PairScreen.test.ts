import { describe, expect, it } from 'vitest';
import { formatCode } from './PairScreen';

describe('formatCode', () => {
  it('groups digits 4-4-4 and drops everything else', () => {
    expect(formatCode('123456789012')).toBe('1234-5678-9012');
    expect(formatCode('1234 5678')).toBe('1234-5678');
    expect(formatCode('12a3')).toBe('123');
    expect(formatCode('1234-5678-9012-99')).toBe('1234-5678-9012');
    expect(formatCode('https://mac.tail1.ts.net:8791/pair?code=1234-5678-9012')).toBe('1234-5678-9012');
  });
});
