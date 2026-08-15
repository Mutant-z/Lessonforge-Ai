import type { CSSProperties } from 'vue';
import type { PPTTemplate } from '../types';

export const DEFAULT_PPT_TEMPLATE: PPTTemplate = {
  id: 'lessonforge_deck_academic',
  name: '学术科研·成品微课',
  short_name: '学术科研',
  description: '沉稳蓝色学术版式，专为科研课题、论文研讨与深度概念讲解微课打造。',
  recommended_for: ['科研课题', '学术论文', '深度课程'],
  composition: 'deck',
  palette: {
    background: '#FFFFFF', surface: '#F4F7FB', primary: '#1F4E79', secondary: '#D6E4F0',
    text: '#1A1A1A', muted: '#6B7280', on_primary: '#FFFFFF',
  },
  typography: { heading: 'Microsoft YaHei', body: 'Microsoft YaHei', latin: 'Arial' },
};

export function pptTemplateStyle(template?: PPTTemplate | null): CSSProperties {
  const value = template || DEFAULT_PPT_TEMPLATE;
  return {
    '--ppt-bg': value.palette.background,
    '--ppt-surface': value.palette.surface,
    '--ppt-primary': value.palette.primary,
    '--ppt-secondary': value.palette.secondary,
    '--ppt-text': value.palette.text,
    '--ppt-muted': value.palette.muted,
    '--ppt-on-primary': value.palette.on_primary,
    '--ppt-heading-font': `${value.typography.heading}, sans-serif`,
    '--ppt-body-font': `${value.typography.body}, sans-serif`,
    '--ppt-latin-font': `${value.typography.latin}, sans-serif`,
  } as CSSProperties;
}
