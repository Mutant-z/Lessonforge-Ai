import type { CSSProperties } from 'vue';
import type { PPTTemplate } from '../types';

export const DEFAULT_PPT_TEMPLATE: PPTTemplate = {
  id: 'lessonforge_swiss_blue',
  name: '瑞士蓝·清晰学术',
  short_name: '瑞士蓝',
  description: '高对比蓝色导轨与清晰网格，强调概念层级和严谨表达。',
  recommended_for: ['通用课程', '数学', '物理'],
  composition: 'swiss_rail',
  palette: {
    background: '#FFFFFF', surface: '#F7F7F8', primary: '#002FA7', secondary: '#DCE7FF',
    text: '#161A22', muted: '#646B78', on_primary: '#FFFFFF',
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
