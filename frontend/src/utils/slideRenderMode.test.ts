import { describe, expect, it } from 'vitest';
import { hasCompleteAbsoluteCoverage, hybridSemanticWidth, inferSlideRenderMode, renderedLayoutElements, visibleSemanticTexts } from './slideRenderMode';
import type { PPTSlide } from '../types/artifact';

function slide(elements: PPTSlide['elements'] = [], renderMode?: PPTSlide['render_mode']): PPTSlide {
  return {
    id: 'slide_03_km', title: '从液体压强推导至阿基米德原理', body: ['文字仍然存在'],
    visual_suggestion: '', speaker_notes: '', elements, render_mode: renderMode,
  };
}

describe('slide render mode', () => {
  it('infers historical media-only artifacts as hybrid', () => {
    const historical = slide([{ kind: 'image', x: 7.7, y: 1.5, w: 4.8, h: 3.6, asset_id: 'v34' }]);
    expect(inferSlideRenderMode(historical)).toBe('hybrid');
    expect(renderedLayoutElements(historical)).toHaveLength(1);
    expect(hybridSemanticWidth(historical, 'lessonforge_deck_academic')).toBeGreaterThan(200);
  });

  it('uses only complete absolute elements when textboxes exist', () => {
    const absolute = slide([
      { kind: 'textbox', content_ref: 'title', text: '从液体压强推导至阿基米德原理', x: 1, y: 1, w: 5, h: 1 },
      { kind: 'textbox', content_ref: 'body', text: '文字仍然存在', x: 1, y: 2, w: 5, h: 2 },
      { kind: 'image', visual_slot: 'primary_visual', x: 7, y: 1, w: 5, h: 4 },
    ]);
    expect(inferSlideRenderMode(absolute)).toBe('absolute');
    expect(renderedLayoutElements(absolute)).toHaveLength(3);
  });

  it('falls back to semantic or hybrid when absolute text coverage is incomplete', () => {
    const incomplete = slide([
      { kind: 'textbox', content_ref: 'title', text: '从模型复制的标题', x: 1, y: 1, w: 5, h: 1 },
      { kind: 'image', x: 7, y: 1, w: 5, h: 4 },
    ], 'absolute');
    expect(hasCompleteAbsoluteCoverage(incomplete)).toBe(false);
    expect(inferSlideRenderMode(incomplete)).toBe('hybrid');
    expect(renderedLayoutElements(incomplete)).toEqual([expect.objectContaining({ kind: 'image' })]);
  });

  it('keeps visual-only shapes from hiding semantic content', () => {
    const visualOnly = slide([
      { kind: 'shape', x: 6.8, y: 1, w: 5.5, h: 4 },
      { kind: 'image', x: 7, y: 1.2, w: 5, h: 3.6 },
    ]);
    expect(inferSlideRenderMode(visualOnly)).toBe('hybrid');
  });

  it('includes step details and quote citations in visible semantic coverage', () => {
    const structured = {
      ...slide(),
      blocks: [
        { kind: 'steps' as const, steps: [{ title: '观察压强', detail: 'p=ρgh' }] },
        { kind: 'quote' as const, text: 'F浮=G排', citation: '阿基米德原理' },
      ],
    };
    expect(visibleSemanticTexts(structured)).toEqual(expect.arrayContaining([
      '观察压强', 'p=ρgh', 'F浮=G排', '阿基米德原理',
    ]));
  });

  it('does not manufacture a 3.2in text region over a left-edge image', () => {
    const leftImage = slide([{ kind: 'image', x: 0, y: 1, w: 6, h: 4 }]);
    expect(hybridSemanticWidth(leftImage, 'lessonforge_deck_academic')).toBeUndefined();
  });
});
