import { describe, expect, it } from 'vitest';
import { normalizeSlideIndex, updateSlideSelection } from './slideNavigation';

describe('slide navigation', () => {
  it('keeps page zero as a valid controlled index', () => {
    expect(normalizeSlideIndex(0, 15)).toBe(0);
    expect(normalizeSlideIndex(1, 15)).toBe(1);
  });

  it('clamps stale indexes when slide content changes', () => {
    expect(normalizeSlideIndex(-1, 15)).toBe(0);
    expect(normalizeSlideIndex(99, 15)).toBe(14);
    expect(normalizeSlideIndex(undefined, 15)).toBe(0);
  });

  it('replaces selection when navigating back to the first page', () => {
    const next = updateSlideSelection(new Set([1]), 0, false);
    expect([...next]).toEqual([0]);
  });
});
