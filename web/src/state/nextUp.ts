// What Home's "Next up" card suggests: a video to watch or a step to apply, and an optional skill.
import type { NextUpMode } from '../lib/types';
import { readJSON, writeJSON } from './storage';

const MODE_KEY = 'vm.nextUp.v1';
const SKILL_KEY = 'vm.nextUpSkill.v1';

export const NEXT_UP_CHOICES: { value: NextUpMode; label: string }[] = [
  { value: 'watch', label: 'Watch next' },
  { value: 'apply', label: 'Apply next' },
];

export function readNextUpMode(): NextUpMode {
  const v = readJSON<unknown>(MODE_KEY, 'apply');
  return v === 'watch' || v === 'apply' ? v : 'apply';
}

export function saveNextUpMode(v: NextUpMode): void {
  writeJSON(MODE_KEY, v);
}

/** The skill to focus on; empty for any skill. */
export function readNextUpSkill(): string {
  const v = readJSON<unknown>(SKILL_KEY, '');
  return typeof v === 'string' ? v : '';
}

export function saveNextUpSkill(skill: string): void {
  writeJSON(SKILL_KEY, skill);
}
