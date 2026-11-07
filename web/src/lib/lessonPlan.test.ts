import { describe, expect, it } from 'vitest';
import { buildSteps, clampStep, lessonStart, spoken, videoIdOf, watchSeconds, where } from './lessonPlan';
import type { TrainingClip, TrainingModuleBody } from './types';

const clip = (video: string, start: number, end: number): TrainingClip => ({
  video,
  start,
  end,
  why: `why ${video}`,
  watch_for: `watch ${video}`,
  title: `Title ${video}`,
  channel: `Chan ${video}`,
  url: `https://youtu.be/${video}?t=${start}`,
  embed: `https://www.youtube.com/embed/${video}?start=${start}&end=${end}`,
  thumbnail: '',
});

const MOD: TrainingModuleBody = {
  title: 'Hard conversations',
  outcome: 'Say the hard thing kindly.',
  minutes: 20,
  lessons: [
    { title: 'Open', goal: 'Start well', clips: [clip('a', 10, 70), clip('b', 0, 120)], exercise: 'Practice an opener' },
    { title: 'Close', goal: 'End well', clips: [clip('a', 300, 360)], exercise: '' },
  ],
  quiz: [{ question: 'q', answer: 'a', video: 'a', t: 10, url: '', title: null }],
  gaps: [],
  dropped: 0,
  tag: 'communication',
  goal: 'Thursday talk',
};

describe('lesson plan', () => {
  const steps = buildSteps(MOD);

  it('puts a cue card before every clip and an exercise after each lesson that has one', () => {
    expect(steps.map((s) => s.kind)).toEqual(['intro', 'lesson', 'cue', 'clip', 'cue', 'clip', 'exercise', 'lesson', 'cue', 'clip', 'done']);
  });

  it('summarizes clips across videos and total watch time', () => {
    expect(watchSeconds(MOD)).toBe(240);
    const intro = steps[0];
    expect(intro.kind === 'intro' && intro.lines[1]).toBe('2 lessons · 3 clips from 2 videos · about 4 min of video');
    expect(intro.kind === 'intro' && intro.lines[2]).toBe('Your goal: Thursday talk');
  });

  it('labels positions with clip numbers across the module', () => {
    expect(where(steps, 0)).toBe('Start');
    expect(where(steps, 2)).toBe('Lesson 1 · clip 1 of 3');
    expect(where(steps, 3)).toBe('Lesson 1 · clip 1 of 3');
    expect(where(steps, 8)).toBe('Lesson 2 · clip 3 of 3');
    expect(where(steps, 10)).toBe('Finish');
  });

  it('starts a lesson at its card and keeps saved positions in range', () => {
    expect(lessonStart(steps, 1)).toBe(7);
    expect(clampStep(steps, 99)).toBe(steps.length - 1);
    expect(clampStep(steps, -3)).toBe(0);
    expect(clampStep(steps, 'x')).toBe(0);
  });

  it('reads a card aloud as one sentence run', () => {
    const cue = steps[2];
    expect(cue.kind === 'cue' && spoken(cue)).toBe('Title a. why a. Watch for: watch a. From Chan a');
  });
});

describe('videoIdOf', () => {
  it('strips the app item prefix', () => {
    expect(videoIdOf({ video: 'yt:gv0WHhKelSE' })).toBe('gv0WHhKelSE');
    expect(videoIdOf({ video: 'gv0WHhKelSE' })).toBe('gv0WHhKelSE');
  });
});
