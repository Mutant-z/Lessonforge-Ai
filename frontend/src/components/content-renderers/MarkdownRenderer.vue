<script setup lang="ts">
import { computed } from 'vue';
import MarkdownIt from 'markdown-it';
import {
  extractMath,
  normalizeAgentMarkdown,
  restoreMathPlaceholders,
} from '../../services/markdownText';

const props = defineProps<{
  content: string;
  isStreaming?: boolean;
}>();

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true
});

/**
 * 安全渲染管道：
 * 1. 提取 `$...$` / `$$...$$` 公式为占位符（代码围栏内的内容不受影响）；
 * 2. 归一化正文：统一换行、压缩空行、剥离残余 HTML 标签、LaTeX → 可读文本；
 * 3. markdown-it 渲染（html:false，原始 HTML 一律转义，不会注入执行）；
 * 4. 还原公式：优先 katex，失败时回退为可读普通文本，绝不把 LaTeX 或标签源码展示给用户。
 */
function renderExerciseMarkdown(content: string): string {
  if (!content.includes('ex_')) {
    const extracted = extractMath(content);
    const normalized = normalizeAgentMarkdown(extracted.text);
    const html = md.render(normalized);
    return restoreMathPlaceholders(html, extracted.inline, extracted.display);
  }

  // 按 ex_XX 题号进行大块切割
  const parts = content.split(/(?=ex_\d+[\s·.:])/g);

  const renderedParts = parts.map(part => {
    const trimmed = part.trim();
    if (!trimmed.startsWith('ex_')) {
      const extracted = extractMath(trimmed);
      const normalized = normalizeAgentMarkdown(extracted.text);
      const html = md.render(normalized);
      return restoreMathPlaceholders(html, extracted.inline, extracted.display);
    }

    // 提取题号 (ex_01 -> 01)
    const qNumMatch = trimmed.match(/^ex_(\d+)[\s·.:]*/);
    const qNum = qNumMatch ? qNumMatch[1] : '01';

    let body = trimmed.replace(/^ex_\d+[\s·.:]*/, '');

    // 提取答案
    let answerText = '';
    const answerMatch = body.match(/(?:\*\*|\b)答案[：:]\s*(?:\*\*)?\s*([^\n]+)/);
    if (answerMatch) {
      answerText = (answerMatch[1] || '').trim();
      body = body.replace(/(?:\*\*|\b)答案[：:]\s*(?:\*\*)?\s*[^\n]+/, '');
    }

    // 提取解析
    let analysisText = '';
    const analysisMatch = body.match(/(?:\*\*|\b)解析[：:]\s*(?:\*\*)?\s*([\s\S]+?)(?=$|\n\s*ex_\d+)/);
    if (analysisMatch) {
      analysisText = (analysisMatch[1] || '').trim();
      body = body.replace(/(?:\*\*|\b)解析[：:]\s*(?:\*\*)?\s*[\s\S]+?(?=$|\n\s*ex_\d+)/, '');
    }

    // 提取选项 (A. xx, B. xx, C. xx, D. xx)
    const options: Array<{ letter: string; text: string }> = [];
    const optRegex = /(?:^|\n)\s*([A-D])[\.\:]\s*([^\n]+)/g;
    let optMatch: RegExpExecArray | null;
    while ((optMatch = optRegex.exec(body)) !== null) {
      options.push({ letter: optMatch[1], text: optMatch[2].trim() });
    }

    // 剥离选项后的题干
    let stemText = body.replace(/(?:^|\n)\s*([A-D])[\.\:]\s*[^\n]+/g, '').trim();

    // 渲染数学公式与 Markdown
    const renderPiece = (str: string) => {
      if (!str) return '';
      const ext = extractMath(str);
      const norm = normalizeAgentMarkdown(ext.text);
      const h = md.render(norm);
      return restoreMathPlaceholders(h, ext.inline, ext.display);
    };

    const renderedStem = renderPiece(stemText);
    const renderedAnswer = renderPiece(answerText);
    const renderedAnalysis = renderPiece(analysisText);

    const typeLabel = options.length > 0 ? '单选题' : '综合问答题';

    let cardHtml = `<div class="md-question-card-block">`;
    cardHtml += `<div class="card-head-row"><span class="q-badge">${qNum}</span><span class="q-type">${typeLabel}</span></div>`;
    cardHtml += `<div class="q-stem-body">${renderedStem}</div>`;

    if (options.length > 0) {
      cardHtml += `<div class="q-options-grid">`;
      for (const opt of options) {
        cardHtml += `<div class="opt-pill"><span class="opt-letter">${opt.letter}</span><span class="opt-text">${opt.text}</span></div>`;
      }
      cardHtml += `</div>`;
    }

    const cleanAnswer = renderedAnswer.replace(/^<p>|<\/p>\s*$/gi, '').trim();
    const cleanAnalysis = renderedAnalysis.replace(/^<p>|<\/p>\s*$/gi, '').trim();

    if (cleanAnswer) {
      cardHtml += `<div class="q-callout answer-callout"><span class="callout-tag green">✓ 参考答案</span><span class="callout-val-text">${cleanAnswer}</span></div>`;
    }

    if (cleanAnalysis) {
      cardHtml += `<div class="q-callout analysis-callout"><div class="callout-header"><span class="callout-tag violet">💡 详细解析</span></div><div class="callout-body-text">${cleanAnalysis}</div></div>`;
    }

    cardHtml += `</div>`;
    return cardHtml;
  });

  return renderedParts.join('\n');
}

function formatDocumentHtml(html: string): string {
  let result = html;

  // 1. 教学设计 / 学情分析 Tag 替换：【已有知识基底】、【认知与思维特点】、【迷思概念与直觉误区】等
  result = result.replace(
    /【已有知识基底】/g,
    '<span class="md-tag-chip blue"><span class="chip-dot"></span>已有知识基底</span>'
  );
  result = result.replace(
    /【认知与思维特点】/g,
    '<span class="md-tag-chip violet"><span class="chip-dot"></span>认知与思维特点</span>'
  );
  result = result.replace(
    /【迷思概念与直觉误区】/g,
    '<span class="md-tag-chip amber"><span class="chip-dot"></span>迷思概念与直觉误区</span>'
  );
  result = result.replace(
    /【([^】]+)】/g,
    '<span class="md-tag-chip indigo"><span class="chip-dot"></span>$1</span>'
  );

  // 2. 教学设计主要 Section 标题增强 (内容分析、学情分析、教学目标、教学重点、教学难点)
  const lessonIcons: Record<string, string> = {
    '内容分析': '📖',
    '学情分析': '👥',
    '教学目标': '🎯',
    '教学重点': '💡',
    '教学难点': '🔥',
    '教学过程': '⏱️',
    '教学反思': '✨'
  };
  result = result.replace(
    /<h2>\s*(内容分析|学情分析|教学目标|教学重点|教学难点|教学过程|教学反思)\s*<\/h2>/gi,
    (_, title) => `<h2 class="lesson-section-header"><span class="section-icon">${lessonIcons[title] || '📌'}</span><span class="section-title">${title}</span></h2>`
  );

  // 3. 视频脚本时间轴标题：`## 00:00-02:00 · 趣味引入：潜水艇的困惑`
  result = result.replace(
    /<h2>\s*(\d{2}:\d{2}-\d{2}:\d{2})\s*[·.:]?\s*(.*?)\s*<\/h2>/gi,
    '<div class="script-timestamp-card"><div class="time-pill">⏱️ $1</div><h3 class="script-title">$2</h3></div>'
  );

  // 4. 视频脚本分镜列表项 (画面 / 旁白 / 动作)
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*画面[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row scene-row"><div class="script-badge-col"><span class="script-badge scene-badge">🎥 画面</span></div><div class="script-body-col">$1</div></li>'
  );
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*旁白[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row narration-row"><div class="script-badge-col"><span class="script-badge narration-badge">🎙️ 旁白</span></div><div class="script-body-col">$1</div></li>'
  );
  result = result.replace(
    /<li>\s*(?:<strong>)?\s*动作[：:]\s*(?:<\/strong>)?\s*([\s\S]+?)<\/li>/gi,
    '<li class="script-row action-row"><div class="script-badge-col"><span class="script-badge action-badge">🎬 动作</span></div><div class="script-body-col">$1</div></li>'
  );

  // 5. 教师逐字稿 Header/Masthead 增强 (`<h1>教师逐字稿</h1>` 与 `建议语速`)
  result = result.replace(
    /<h[12]>\s*教师逐字稿\s*<\/h[12]>(?:\s*<p>\s*(?:<strong>)?\s*建议语速[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)\s*<\/p>)?/gi,
    (_, speed) => {
      const speedVal = (speed || '').trim() || 'standard (120-140字/分)';
      return `
        <div class="verbatim-masthead-card">
          <div class="masthead-badge-row">
            <span class="masthead-kicker"><span class="pulse-dot"></span>教师口播逐字稿 · 提词台本</span>
            <span class="masthead-status-chip">微课 / 现场讲授</span>
          </div>
          <h1 class="masthead-main-title">教师逐字稿</h1>
          <div class="masthead-meta-grid">
            <div class="meta-pill-item speed">
              <span class="meta-icon">⚡</span>
              <span class="meta-label">建议语速:</span>
              <span class="meta-value">${speedVal}</span>
            </div>
            <div class="meta-pill-item highlight">
              <span class="meta-icon">🎯</span>
              <span class="meta-label">重点标注:</span>
              <span class="meta-value">分段时间轴 · 交互动作 · 拓展补充</span>
            </div>
          </div>
        </div>
      `;
    }
  );

  // 独立的 `建议语速： standard` 替换 (避免未跟随 h1 时遗漏)
  result = result.replace(
    /<p>\s*(?:<strong>)?\s*建议语速[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)\s*<\/p>/gi,
    (_, speed) => `<div class="verbatim-speed-chip"><span class="chip-icon">⚡</span><span class="chip-label">建议语速：</span><span class="chip-value">${(speed || '').trim()}</span></div>`
  );

  // 6. 教师逐字稿段落标题：`## seg_01 · 00:00-02:00 · slide_01,slide_02...`
  result = result.replace(
    /<h2>\s*(seg_\d+)\s*·\s*(\d{2}:\d{2}-\d{2}:\d{2})\s*·\s*([^\n<]+)\s*<\/h2>/gi,
    (_, segId, timeStr, slidesStr) => {
      const slides = slidesStr.split(',').map((s: string) => {
        const slideName = s.trim();
        return `<span class="slide-tag" title="对应 PPT 页面: ${slideName}"><span class="slide-icon">📑</span>${slideName}</span>`;
      }).join('');
      return `
        <div class="verbatim-seg-card">
          <div class="seg-head-left">
            <span class="seg-chip"><span class="seg-icon">🚀</span>${segId}</span>
            <span class="time-chip"><span class="time-icon">⏱️</span>${timeStr}</span>
          </div>
          <div class="seg-head-right">
            <span class="slides-label">关联胶片：</span>
            <div class="slides-group">${slides}</div>
          </div>
        </div>
      `;
    }
  );

  // 7. 教师逐字稿 Callout：`可选补充:` 与 `互动:` / `互动提示:`
  result = result.replace(
    /(?:<blockquote\s*>\s*)?(?:<p>|<br\s*\/?>|^)\s*(?:<strong>)?\s*(?:可选补充|补充说明)[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)(?:<\/p>|(?=<br\s*\/?>|$))(?:<\/blockquote>)?/gi,
    (_, bodyText) => {
      const cleanBody = (bodyText || '').trim();
      if (!cleanBody) return '';
      return `
        <div class="verbatim-callout supplement-callout">
          <div class="callout-header">
            <span class="callout-badge purple"><span class="badge-icon">💡</span> 可选补充</span>
            <span class="callout-hint">拓展讲解提示</span>
          </div>
          <div class="callout-body">${cleanBody}</div>
        </div>
      `;
    }
  );

  result = result.replace(
    /(?:<blockquote\s*>\s*)?(?:<p>|<br\s*\/?>|^)\s*(?:<strong>)?\s*(?:互动提示|互动)[：:]\s*(?:<\/strong>)?\s*([\s\S]*?)(?:<\/p>|(?=<br\s*\/?>|$))(?:<\/blockquote>)?/gi,
    (_, bodyText) => {
      let text = (bodyText || '').trim();
      if (!text) return '';
      // 增强渲染：动态突出动作、停顿与镜头
      text = text.replace(/(停顿\s*\d+(?:\.\d+)?\s*秒)/g, '<mark class="action-tag pause"><span class="tag-icon">⏱️</span>$1</mark>');
      text = text.replace(/((?:[^\s,，。；;]*?画中画|镜头打招呼))/g, '<span class="action-tag camera"><span class="tag-icon">📹</span>$1</span>');
      text = text.replace(/(手势[^\s,，。；;]*?|比出[^\s,，。；;]*?手势|做出[^\s,，。；;]*?状)/g, '<span class="action-tag gesture"><span class="tag-icon">👉</span>$1</span>');
      
      return `
        <div class="verbatim-callout interaction-callout">
          <div class="callout-header">
            <span class="callout-badge blue"><span class="badge-icon">🎭</span> 互动提示与台风指南</span>
            <span class="callout-hint">肢体 / 镜头 / 停顿节奏</span>
          </div>
          <div class="callout-body">${text}</div>
        </div>
      `;
    }
  );

  // 清理因替换产生的空标签
  result = result.replace(/<blockquote\s*>\s*(?:<p>\s*<\/p>)?\s*<\/blockquote>/gi, '');

  return result;
}

function renderDocumentMarkdown(content: string): string {
  if (content.includes('ex_')) {
    return renderExerciseMarkdown(content);
  }

  const extracted = extractMath(content);
  const normalized = normalizeAgentMarkdown(extracted.text);
  const html = md.render(normalized);
  const restored = restoreMathPlaceholders(html, extracted.inline, extracted.display);

  return formatDocumentHtml(restored);
}

const renderedHtml = computed(() => {
  if (!props.content) return '';
  return renderDocumentMarkdown(props.content);
});
</script>

<template>
  <div class="markdown-rendered-body" v-html="renderedHtml"></div>
</template>

<style>
/* 统一的 Agent 输出排版规则：标题、列表、正文、公式、代码共享同一套视觉层级。 */
.markdown-rendered-body {
  font-size: 14px;
  line-height: 1.65;
  color: inherit;
  /* 覆盖父级可能残留的 pre-wrap，避免把 markdown-it 生成的换行渲染成大段空白 */
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  max-width: 100%;
  min-width: 0;
}

.markdown-rendered-body > :first-child {
  margin-top: 0;
}

.markdown-rendered-body > :last-child {
  margin-bottom: 0;
}

/* 标题层级：紧凑且与正文拉开主次 */
.markdown-rendered-body h1,
.markdown-rendered-body h2,
.markdown-rendered-body h3,
.markdown-rendered-body h4 {
  font-weight: 800;
  letter-spacing: -0.01em;
  color: inherit;
  margin: 0.75em 0 0.35em;
  line-height: 1.35;
}

.markdown-rendered-body h1 {
  font-size: 19px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 5px;
}

.markdown-rendered-body h2 { font-size: 16px; }
.markdown-rendered-body h3 { font-size: 14.5px; }
.markdown-rendered-body h4 { font-size: 14px; }

/* 正文：紧凑段落间距，避免内容被大段空白拉长 */
.markdown-rendered-body p {
  margin: 0 0 0.45em;
}

.markdown-rendered-body p:last-child {
  margin-bottom: 0;
}

.markdown-rendered-body strong {
  font-weight: 800;
  color: inherit;
}

/* 列表：紧凑排列，不产生大面积留白 */
.markdown-rendered-body ul,
.markdown-rendered-body ol {
  padding-left: 1.35em;
  margin: 0.15em 0 0.45em;
}

.markdown-rendered-body li {
  margin: 0;
}

.markdown-rendered-body li + li {
  margin-top: 2px;
}

.markdown-rendered-body li > p {
  margin: 0;
}

.markdown-rendered-body li > ul,
.markdown-rendered-body li > ol {
  margin: 2px 0;
}

.markdown-rendered-body blockquote {
  border-left: 3.5px solid #4f46e5;
  background: #f5f3ff;
  padding: 8px 14px;
  margin: 0.6em 0;
  border-radius: 0 10px 10px 0;
  color: #4338ca;
}

.markdown-rendered-body blockquote p {
  margin: 0.2em 0;
}

/* 行内代码与代码块 */
.markdown-rendered-body code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  padding: 1px 5px;
  border-radius: 4px;
  color: #4f46e5;
  overflow-wrap: break-word;
}

.markdown-rendered-body pre {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  margin: 0.6em 0;
  overflow-x: auto;
  overflow-y: hidden;
  line-height: 1.55;
}

.markdown-rendered-body pre code {
  background: transparent;
  border: 0;
  padding: 0;
  color: #334155;
  font-size: 12.5px;
  overflow-wrap: normal;
  word-break: normal;
}

.markdown-rendered-body pre code .hljs {
  background: transparent;
}

/* 公式：katex 渲染为主；兜底为可读普通文本 */
.markdown-rendered-body .math-inline-fallback {
  font-style: italic;
  background: #eef2ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
  padding: 0 4px;
  border-radius: 4px;
  white-space: normal;
}

.markdown-rendered-body .math-display-fallback {
  font-style: italic;
  text-align: center;
  background: #f5f3ff;
  color: #3730a3;
  border: 1px solid #e0e7ff;
  padding: 8px 12px;
  margin: 0.5em 0;
  border-radius: 8px;
  overflow-x: auto;
}

/* katex 细节微调：避免过大的公式上下留白，长公式允许横向滚动 */
.markdown-rendered-body .katex-display {
  margin: 0.4em 0;
  overflow-x: auto;
  overflow-y: hidden;
  padding: 2px 0;
}

.markdown-rendered-body .katex {
  font-size: 1.04em;
}

.markdown-rendered-body table {
  width: 100%;
  border-collapse: collapse;
  margin: 0.6em 0;
}

.markdown-rendered-body th,
.markdown-rendered-body td {
  border: 1px solid #e2e8f0;
  padding: 6px 10px;
  text-align: left;
}

.markdown-rendered-body th {
  background: #f8fafc;
  font-weight: 700;
}

.markdown-rendered-body hr {
  border: 0;
  border-top: 1px solid #e2e8f0;
  margin: 0.8em 0;
}

.markdown-rendered-body a {
  color: #4f46e5;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.markdown-rendered-body img {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
}

/* 课后练习 Markdown 高保真全能大卡片样式 */
.markdown-rendered-body .md-question-card-block {
  margin-top: 24px;
  margin-bottom: 28px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  border-left: 5px solid #4f46e5;
  border-radius: 16px;
  padding: 22px 26px;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.06);
  transition: all 200ms ease;
}

.markdown-rendered-body .md-question-card-block:hover {
  border-color: #94a3b8;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.1);
  transform: translateY(-2px);
}

.markdown-rendered-body .card-head-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.markdown-rendered-body .q-badge {
  font-size: 12px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  padding: 3px 12px;
  border-radius: 999px;
  box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3);
}

.markdown-rendered-body .q-type {
  font-size: 12px;
  font-weight: 800;
  color: #4f46e5;
  background: #eef2ff;
  padding: 3px 10px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .q-stem-body {
  font-size: 15.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.7;
  margin-bottom: 16px;
}

.markdown-rendered-body .q-stem-body p {
  margin: 0;
  font-size: 15.5px;
  font-weight: 700;
  color: #0f172a;
  line-height: 1.7;
}

.markdown-rendered-body .q-options-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin: 16px 0;
}

.markdown-rendered-body .opt-pill {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 16px;
  background: #f8fafc;
  border: 1.5px solid #e2e8f0;
  border-radius: 12px;
  font-size: 14px;
  transition: all 180ms ease;
}

.markdown-rendered-body .opt-pill:hover {
  background: #ffffff;
  border-color: #818cf8;
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.1);
}

.markdown-rendered-body .opt-letter {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e0e7ff;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 900;
  display: grid;
  place-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.markdown-rendered-body .opt-text {
  color: #1e293b;
  font-weight: 600;
  line-height: 1.5;
}

.markdown-rendered-body .q-callout {
  margin-top: 14px;
  padding: 14px 18px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.65;
}

.markdown-rendered-body .q-callout.answer-callout {
  display: flex;
  align-items: center;
  gap: 12px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-left: 4px solid #10b981;
  border-radius: 10px;
  padding: 10px 16px;
  margin-top: 14px;
}

.markdown-rendered-body .q-callout.answer-callout .callout-tag.green {
  margin-bottom: 0;
  font-size: 11px;
  font-weight: 800;
  color: #047857;
  background: #d1fae5;
  padding: 3px 10px;
  border-radius: 999px;
  white-space: nowrap;
  flex-shrink: 0;
}

.markdown-rendered-body .q-callout.answer-callout .callout-val-text {
  font-size: 14px;
  font-weight: 800;
  color: #065f46;
}

.markdown-rendered-body .q-callout.analysis-callout {
  background: #f5f3ff;
  border: 1px solid #ddd6fe;
  border-left: 4px solid #8b5cf6;
  border-radius: 10px;
  padding: 12px 16px;
  margin-top: 10px;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-header {
  margin-bottom: 6px;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-tag.violet {
  margin-bottom: 0;
  font-size: 11px;
  font-weight: 800;
  color: #6d28d9;
  background: #ede9fe;
  padding: 3px 10px;
  border-radius: 999px;
  display: inline-block;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-body-text {
  font-size: 13.5px;
  color: #3b0764;
  line-height: 1.65;
  font-weight: 600;
}

.markdown-rendered-body .q-callout.analysis-callout .callout-body-text p {
  margin: 0;
}

/* -------------------------------------------------------------
   1. 教学设计 & 学情分析 标签徽章样式
   ------------------------------------------------------------- */
.markdown-rendered-body .md-tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  padding: 2px 10px;
  border-radius: 999px;
  margin: 0 4px 2px 0;
  vertical-align: baseline;
}

.markdown-rendered-body .md-tag-chip .chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.markdown-rendered-body .md-tag-chip.blue {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}
.markdown-rendered-body .md-tag-chip.blue .chip-dot { background: #2563eb; }

.markdown-rendered-body .md-tag-chip.violet {
  background: #f5f3ff;
  color: #6d28d9;
  border: 1px solid #ddd6fe;
}
.markdown-rendered-body .md-tag-chip.violet .chip-dot { background: #7c3aed; }

.markdown-rendered-body .md-tag-chip.amber {
  background: #fffbeb;
  color: #b45309;
  border: 1px solid #fde68a;
}
.markdown-rendered-body .md-tag-chip.amber .chip-dot { background: #d97706; }

.markdown-rendered-body .md-tag-chip.indigo {
  background: #eef2ff;
  color: #4338ca;
  border: 1px solid #c7d2fe;
}
.markdown-rendered-body .md-tag-chip.indigo .chip-dot { background: #4f46e5; }

.markdown-rendered-body .lesson-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 900;
  color: #0f172a;
  margin: 22px 0 12px;
  padding-bottom: 6px;
  border-bottom: 2.5px solid #e2e8f0;
}

.markdown-rendered-body .lesson-section-header .section-icon {
  font-size: 18px;
}

/* -------------------------------------------------------------
   2. 视频脚本制作时间轴卡片 & 画面/旁白/动作结构行
   ------------------------------------------------------------- */
.markdown-rendered-body .script-timestamp-card {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 24px 0 12px;
  padding: 10px 16px;
  background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
  border-radius: 12px;
  color: #ffffff;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.12);
}

.markdown-rendered-body .script-timestamp-card .time-pill {
  font-size: 12px;
  font-weight: 900;
  background: rgba(255, 255, 255, 0.18);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #38bdf8;
  padding: 3px 12px;
  border-radius: 999px;
  white-space: nowrap;
  letter-spacing: 0.05em;
}

.markdown-rendered-body .script-timestamp-card .script-title {
  margin: 0;
  font-size: 15px;
  font-weight: 800;
  color: #f8fafc;
}

.markdown-rendered-body .script-row {
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 12px;
  align-items: start;
  list-style: none;
  margin: 8px 0;
  padding: 12px 16px;
  border-radius: 10px;
  border: 1.5px solid #e2e8f0;
  background: #ffffff;
  transition: all 150ms ease;
}

.markdown-rendered-body .script-row:hover {
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}

.markdown-rendered-body .script-row.scene-row {
  background: #f8fafc;
  border-color: #cbd5e1;
  border-left: 4px solid #64748b;
}

.markdown-rendered-body .script-row.narration-row {
  background: #f0f9ff;
  border-color: #bae6fd;
  border-left: 4px solid #0284c7;
}

.markdown-rendered-body .script-row.action-row {
  background: #fffbe6;
  border-color: #ffe58f;
  border-left: 4px solid #d4b106;
}

.markdown-rendered-body .script-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 800;
  padding: 4px 10px;
  border-radius: 8px;
  white-space: nowrap;
}

.markdown-rendered-body .scene-badge { background: #e2e8f0; color: #334155; }
.markdown-rendered-body .narration-badge { background: #e0f2fe; color: #0369a1; }
.markdown-rendered-body .action-badge { background: #fff1b8; color: #873800; }

.markdown-rendered-body .script-body-col {
  font-size: 13.5px;
  line-height: 1.65;
  color: #1e293b;
  font-weight: 600;
}

/* -------------------------------------------------------------
   3. 教师逐字稿 (Verbatim Script) Ultra-Modern Visual System
   ------------------------------------------------------------- */

/* Header / Masthead Card */
.markdown-rendered-body .verbatim-masthead-card {
  margin: 0 0 24px 0;
  padding: 24px 28px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
  border: 1.5px solid #e2e8f0;
  border-left: 6px solid #4f46e5;
  border-radius: 16px;
  box-shadow: 0 4px 20px -4px rgba(79, 70, 229, 0.08), 0 2px 6px rgba(15, 23, 42, 0.03);
  position: relative;
  overflow: hidden;
}

.markdown-rendered-body .verbatim-masthead-card::after {
  content: '';
  position: absolute;
  top: -40px;
  right: -40px;
  width: 140px;
  height: 140px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.12) 0%, rgba(255, 255, 255, 0) 70%);
  pointer-events: none;
}

.markdown-rendered-body .masthead-badge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.markdown-rendered-body .masthead-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 700;
  color: #4f46e5;
  letter-spacing: 0.04em;
  background: #eef2ff;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .pulse-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #6366f1;
  box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.7);
  animation: pulse-ring 2s infinite;
}

@keyframes pulse-ring {
  0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.7); }
  70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(99, 102, 241, 0); }
  100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(99, 102, 241, 0); }
}

.markdown-rendered-body .masthead-status-chip {
  font-size: 11px;
  font-weight: 700;
  color: #64748b;
  background: #f1f5f9;
  padding: 3px 10px;
  border-radius: 6px;
}

.markdown-rendered-body .masthead-main-title {
  margin: 4px 0 16px;
  font-size: 24px;
  font-weight: 900;
  color: #0f172a;
  letter-spacing: -0.02em;
  border: none;
  padding: 0;
}

.markdown-rendered-body .masthead-meta-grid {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.markdown-rendered-body .meta-pill-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 10px;
  font-size: 12px;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
}

.markdown-rendered-body .meta-pill-item.speed {
  background: #faf5ff;
  border-color: #e9d5ff;
}

.markdown-rendered-body .meta-pill-item.speed .meta-value {
  color: #7e22ce;
  font-weight: 800;
}

.markdown-rendered-body .meta-pill-item.highlight {
  background: #f0fdf4;
  border-color: #bbf7d0;
}

.markdown-rendered-body .meta-pill-item.highlight .meta-value {
  color: #15803d;
  font-weight: 700;
}

.markdown-rendered-body .meta-icon {
  font-size: 13px;
}

.markdown-rendered-body .meta-label {
  color: #64748b;
  font-weight: 600;
}

.markdown-rendered-body .verbatim-speed-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0 16px;
  padding: 6px 14px;
  background: #faf5ff;
  border: 1.5px solid #e9d5ff;
  border-radius: 10px;
  font-size: 13px;
}

.markdown-rendered-body .verbatim-speed-chip .chip-label {
  color: #6b21a8;
  font-weight: 600;
}

.markdown-rendered-body .verbatim-speed-chip .chip-value {
  color: #7e22ce;
  font-weight: 800;
}

/* Segment Header (seg_01 / seg_02) Card */
.markdown-rendered-body .verbatim-seg-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin: 28px 0 16px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border: 1.5px solid #cbd5e1;
  border-left: 5px solid #4f46e5;
  border-radius: 14px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.markdown-rendered-body .verbatim-seg-card:hover {
  border-color: #a5b4fc;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.1);
}

.markdown-rendered-body .seg-head-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.markdown-rendered-body .seg-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 900;
  color: #ffffff;
  background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
  padding: 4px 12px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  box-shadow: 0 2px 6px rgba(79, 70, 229, 0.3);
}

.markdown-rendered-body .time-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 800;
  color: #3730a3;
  background: #e0e7ff;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .seg-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.markdown-rendered-body .slides-label {
  color: #475569;
  font-weight: 700;
  white-space: nowrap;
}

.markdown-rendered-body .slides-group {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.markdown-rendered-body .slide-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  font-weight: 700;
  color: #1e293b;
  background: #ffffff;
  border: 1.5px solid #cbd5e1;
  padding: 3px 9px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
  transition: all 0.15s ease;
}

.markdown-rendered-body .slide-tag:hover {
  border-color: #6366f1;
  color: #4f46e5;
  transform: translateY(-1px);
}

.markdown-rendered-body .slide-icon {
  font-size: 11px;
}

/* Callout Cards (可选补充 & 互动提示) */
.markdown-rendered-body .verbatim-callout {
  margin: 16px 0;
  padding: 16px 20px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.7;
  transition: all 0.2s ease;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.03);
}

.markdown-rendered-body .verbatim-callout .callout-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.markdown-rendered-body .verbatim-callout .callout-hint {
  font-size: 11px;
  font-weight: 700;
  opacity: 0.75;
}

.markdown-rendered-body .supplement-callout {
  background: linear-gradient(135deg, #f5f3ff 0%, #faf5ff 100%);
  border: 1.5px solid #ddd6fe;
  border-left: 5px solid #8b5cf6;
  color: #4c1d95;
}

.markdown-rendered-body .supplement-callout:hover {
  box-shadow: 0 4px 16px rgba(139, 92, 246, 0.12);
}

.markdown-rendered-body .supplement-callout .callout-badge.purple {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 900;
  color: #6d28d9;
  background: #ede9fe;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #ddd6fe;
}

.markdown-rendered-body .interaction-callout {
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  border: 1.5px solid #bae6fd;
  border-left: 5px solid #0284c7;
  color: #0369a1;
}

.markdown-rendered-body .interaction-callout:hover {
  box-shadow: 0 4px 16px rgba(2, 132, 199, 0.12);
}

.markdown-rendered-body .interaction-callout .callout-badge.blue {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  font-weight: 900;
  color: #0369a1;
  background: #e0f2fe;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid #bae6fd;
}

.markdown-rendered-body .callout-body {
  font-size: 14px;
  line-height: 1.75;
}

/* Action Tags in Interaction Guidance */
.markdown-rendered-body .action-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  font-weight: 800;
  padding: 2px 8px;
  border-radius: 6px;
  margin: 0 2px;
  vertical-align: baseline;
}

.markdown-rendered-body .action-tag.pause {
  background: #fef3c7;
  color: #92400e;
  border: 1px solid #fde68a;
}

.markdown-rendered-body .action-tag.camera {
  background: #e0e7ff;
  color: #3730a3;
  border: 1px solid #c7d2fe;
}

.markdown-rendered-body .action-tag.gesture {
  background: #dcfce7;
  color: #166534;
  border: 1px solid #bbf7d0;
}

.markdown-rendered-body .tag-icon {
  font-size: 11px;
}
</style>
