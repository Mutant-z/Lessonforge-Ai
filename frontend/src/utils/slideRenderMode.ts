import type { PPTLayoutElement, PPTSlide } from '../types/artifact';

export type SlideRenderMode = 'semantic' | 'hybrid' | 'absolute';

const VALID_RENDER_MODES = new Set<SlideRenderMode>(['semantic', 'hybrid', 'absolute']);

function normalizeText(value: unknown): string {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

export function blockTexts(block: Record<string, any>): string[] {
  if (block.kind === 'lead') return [block.text, block.sub].filter(Boolean);
  if (block.kind === 'bullets') return (block.items || []).map((item: any) => item.text).filter(Boolean);
  if (block.kind === 'steps') return (block.steps || []).flatMap((step: any) => [step.title, step.detail]).filter(Boolean);
  if (block.kind === 'compare') {
    return ['left', 'right'].flatMap(side => {
      const column = block[side] || {};
      return [column.heading, ...(column.items || [])].filter(Boolean);
    });
  }
  if (block.kind === 'quote') return [block.text, block.citation].filter(Boolean);
  if (block.kind === 'visual') return [block.caption].filter(Boolean);
  if (block.kind === 'note') return [block.text].filter(Boolean);
  return [];
}

export function visibleSemanticTexts(slide: PPTSlide): string[] {
  const texts: unknown[] = [slide.title, ...(slide.body || [])];
  if (slide.blocks?.length) texts.push(...slide.blocks.flatMap(block => blockTexts(block as unknown as Record<string, any>)));
  if (slide.page_type === 'cover' && slide.purpose) texts.push(slide.purpose);
  return [...new Set(texts.map(normalizeText).filter(Boolean))];
}

export function hasCompleteAbsoluteCoverage(slide: PPTSlide): boolean {
  const rendered = normalizeText(
    (slide.elements || [])
      .filter(element => element.kind === 'textbox')
      .map(element => element.text || '')
      .join('\n'),
  );
  const expected = visibleSemanticTexts(slide);
  return expected.length > 0 && expected.every(text => rendered.includes(text));
}

export function inferSlideRenderMode(slide: PPTSlide): SlideRenderMode {
  const declared = VALID_RENDER_MODES.has(slide.render_mode as SlideRenderMode)
    ? slide.render_mode as SlideRenderMode
    : undefined;
  if (declared === 'semantic' || declared === 'hybrid') return declared;
  const elements = slide.elements || [];
  if (!elements.length) return 'semantic';
  const hasMedia = elements.some(element => ['image', 'chart'].includes(element.kind));
  const hasTextbox = elements.some(element => element.kind === 'textbox');
  if (!hasTextbox) return hasMedia ? 'hybrid' : 'semantic';
  if (hasCompleteAbsoluteCoverage(slide)) return 'absolute';
  // Safety fallback for old or partial drafts: incomplete text geometry must
  // never hide the still-authoritative semantic layer.
  return hasMedia ? 'hybrid' : 'semantic';
}

export function renderedLayoutElements(slide: PPTSlide): PPTLayoutElement[] {
  const mode = inferSlideRenderMode(slide);
  if (mode === 'semantic') return [];
  if (mode === 'hybrid') return (slide.elements || []).filter(element => ['image', 'chart'].includes(element.kind));
  return slide.elements || [];
}

export function hybridSemanticWidth(slide: PPTSlide, templateId: string): number | undefined {
  if (inferSlideRenderMode(slide) !== 'hybrid') return undefined;
  const media = (slide.elements || []).filter(element => ['image', 'chart'].includes(element.kind));
  if (!media.length) return undefined;
  const startX = templateId === 'lessonforge_deck_smart_ai'
    ? 176 / 72
    : templateId === 'lessonforge_deck_academic'
      ? 158 / 72
      : 97.2 / 72;
  const mediaX = Math.min(...media.map(element => Number(element.x ?? 13.333)));
  const available = mediaX - startX - 0.3;
  return available >= 3.2 ? available * 72 : undefined;
}
